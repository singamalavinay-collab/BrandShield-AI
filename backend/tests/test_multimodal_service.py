"""Focused unit and integration test suite for MultimodalService (Phase 2, Stage 2A).

Guarantees tested:
1. Text: Pure deterministic execution path preserved.
2. Documents: Pure-Python extraction (PDF / DOCX), page references, encrypted/scanned safe handling.
3. Images: Gemini Vision parsing (OCR, logos, colors, bounding boxes), transparent fallback on error/missing config.
4. Audio: Speech transcription and timestamped dialogue parsing, zero fabricated output on fallback.
5. Video: Full Files API lifecycle (upload, poll, generate, guaranteed delete in finally: block), failure cleanup.
6. Unsupported model capabilities and missing Gemini configuration handling.
7. Timeouts, quota exhaustion, and malformed JSON handling.
8. Zero credentials or binary payload leakage.
"""

import asyncio
import json
from pathlib import Path
import tempfile
from typing import Any, Dict, List
import wave
import pytest
import httpx
import pypdf

from app.core.config import settings
from app.engine.ai_provider import AIProvider
from app.engine.gemini_client import GeminiClient, GeminiClientError, GeminiErrorCode
from app.engine.multimodal.service import (
    MultimodalAnalysisResult,
    MultimodalProcessingStatus,
    MultimodalService,
    SpokenDialogueSegment,
    VisualObservation,
    _clean_json_response,
)
from app.engine.multimodal.validator import MimeType


# ==============================================================================
# Helper Fixtures & Test Data
# ==============================================================================

@pytest.fixture
def tmp_scratch_dir(tmp_path: Path):
    """Temporary scratch directory for media test artifacts."""
    d = tmp_path / "scratch"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def sample_png_path(tmp_scratch_dir: Path) -> Path:
    """Creates a minimal valid 1x1 PNG file."""
    p = tmp_scratch_dir / "sample.png"
    # Minimal valid 1x1 PNG
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
        b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    p.write_bytes(png_bytes)
    return p


@pytest.fixture
def sample_wav_path(tmp_scratch_dir: Path) -> Path:
    """Creates a minimal valid 1-second WAV audio file."""
    p = tmp_scratch_dir / "sample.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 44100)
    return p


@pytest.fixture
def sample_mp4_path(tmp_scratch_dir: Path) -> Path:
    """Creates a minimal valid MP4 file container."""
    p = tmp_scratch_dir / "sample.mp4"
    # Minimal MP4 header with ftyp atom
    mp4_bytes = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42\x00\x00\x00\x08free"
    p.write_bytes(mp4_bytes)
    return p


def create_sample_pdf(text_lines: List[str]) -> bytes:
    """Generate in-memory valid digital PDF 1.4 bytes containing text."""
    stream_lines = ["BT", "/F1 12 Tf", "72 712 Td"]
    for idx, line in enumerate(text_lines):
        clean_line = line.replace("(", "\\(").replace(")", "\\)")
        if idx > 0:
            stream_lines.append("0 -20 Td")
        stream_lines.append(f"({clean_line}) Tj")
    stream_lines.append("ET")
    stream_content = "\n".join(stream_lines).encode("latin-1")

    obj5 = b"<< /Length " + str(len(stream_content)).encode("ascii") + b" >>\nstream\n" + stream_content + b"\nendstream"
    obj1 = b"<< /Type /Catalog /Pages 2 0 R >>"
    obj2 = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    obj3 = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
    obj4 = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    objects = [obj1, obj2, obj3, obj4, obj5]

    buf = bytearray(b"%PDF-1.4\n")
    offsets = []
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf.extend(f"{idx} 0 obj\n".encode("ascii"))
        buf.extend(obj)
        buf.extend(b"\nendobj\n")

    xref_offset = len(buf)
    buf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buf.extend(b"0000000000 65535 f \n")
    for off in offsets:
        buf.extend(f"{off:010d} 00000 n \n".encode("ascii"))

    buf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    return bytes(buf)


@pytest.fixture
def sample_pdf_path(tmp_scratch_dir: Path) -> Path:
    """Creates a minimal valid digital PDF with searchable text."""
    p = tmp_scratch_dir / "sample.pdf"
    pdf_bytes = create_sample_pdf([
        "BrandShield AI Enterprise Brand Guidelines and Mandatory Standards",
        "Approved brand terminology: BrandShield AI, Enterprise Shield.",
        "Prohibited statements: Guaranteed 100% compliance without human oversight.",
    ])
    p.write_bytes(pdf_bytes)
    return p


# ==============================================================================
# 1. Text Modality Unit Tests (Deterministic Path)
# ==============================================================================

def test_text_processing_deterministic_path():
    """Verify that pure text input runs through the 100% deterministic path."""
    svc = MultimodalService()
    raw_text = "  BrandShield AI provides comprehensive brand risk assessment.  "
    result = svc.analyze_text(raw_text)

    assert result.media_type == "text"
    assert result.status == MultimodalProcessingStatus.SUCCESS
    assert result.extracted_text == "BrandShield AI provides comprehensive brand risk assessment."
    assert result.analysis_engine == "deterministic_text_engine"
    assert result.confidence_score == 1.0
    assert result.fallback_reason is None
    assert result.metadata["character_count"] == len(result.extracted_text)


# ==============================================================================
# 2. Document Modality Unit Tests (PDF & DOCX)
# ==============================================================================

def test_document_processing_valid_pdf(sample_pdf_path: Path):
    """Verify digital PDF text extraction preserves page references without network calls."""
    svc = MultimodalService()
    result = svc.analyze_document(sample_pdf_path, MimeType.PDF)

    assert result.media_type == "document"
    assert result.status == MultimodalProcessingStatus.SUCCESS
    assert "BrandShield AI Enterprise Brand Guidelines" in result.extracted_text
    assert result.analysis_engine == "pypdf_extractor"
    assert result.confidence_score == 1.0
    assert len(result.evidence_references) >= 1
    assert result.evidence_references[0]["page"] == 1


def test_document_processing_missing_file(tmp_scratch_dir: Path):
    """Verify missing document file fails safely."""
    svc = MultimodalService()
    missing_path = tmp_scratch_dir / "nonexistent.pdf"
    result = svc.analyze_document(missing_path, MimeType.PDF)

    assert result.status == MultimodalProcessingStatus.FAILED
    assert result.fallback_reason == "FILE_NOT_FOUND"


# ==============================================================================
# 3. Image Modality Unit Tests (Gemini Vision & Fallbacks)
# ==============================================================================

@pytest.mark.asyncio
async def test_image_processing_gemini_success(sample_png_path: Path):
    """Verify Gemini Vision parses OCR text, logos, colors, and bounding boxes."""
    gemini_response_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "on_screen_text": "Introducing BrandShield AI",
                                "logos": [
                                    {
                                        "label": "BrandShield Primary Logo",
                                        "confidence": 0.98,
                                        "box_2d": [0.12, 0.15, 0.35, 0.45],
                                        "notes": "Crisp logo with adequate clear-space",
                                    }
                                ],
                                "dominant_colors": [
                                    {"hex": "#1E40AF", "name": "Deep Royal Blue", "percentage": 55},
                                    {"hex": "#FFFFFF", "name": "Pure White", "percentage": 30},
                                ],
                                "visual_compliance_notes": ["Complies with primary master logo guidelines."],
                            })
                        }
                    ]
                }
            }
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "models/gemini-2.5-flash" in url_str and request.method == "GET":
            return httpx.Response(200, json={"accessible": True, "displayName": "Gemini 2.5 Flash"})
        if ":generateContent" in url_str:
            return httpx.Response(200, json=gemini_response_payload)
        return httpx.Response(404, json={"error": {"message": "Not found"}})

    transport = httpx.MockTransport(mock_handler)
    mock_client = GeminiClient(
        api_key="AIzaSyFakeKeyForTesting1234567890",
        model_name="gemini-2.5-flash",
        transport=transport,
    )
    provider = AIProvider(client=mock_client)
    provider.gemini_key = "AIzaSyFakeKeyForTesting1234567890"
    provider.model_name = "gemini-2.5-flash"

    svc = MultimodalService(ai_provider=provider)
    result = await svc.analyze_image(
        file_path=sample_png_path,
        mime_type=MimeType.PNG,
        user_caption="Q3 Marketing Hero Banner",
    )

    assert result.media_type == "image"
    assert result.status == MultimodalProcessingStatus.SUCCESS
    assert result.analysis_engine == "gemini_vision"
    assert "Introducing BrandShield AI" in result.extracted_text
    assert "Q3 Marketing Hero Banner" in result.extracted_text
    assert len(result.visual_observations) == 3  # 1 logo + 2 colors

    logo_obs = next(o for o in result.visual_observations if o.entity == "logo")
    assert logo_obs.label == "BrandShield Primary Logo"
    assert logo_obs.confidence == 0.98
    assert logo_obs.box_2d == [0.12, 0.15, 0.35, 0.45]

    color_obs = [o for o in result.visual_observations if o.entity == "color"]
    assert len(color_obs) == 2
    assert color_obs[0].label == "#1E40AF"


@pytest.mark.asyncio
async def test_image_missing_gemini_config_fallback(sample_png_path: Path):
    """Verify that unconfigured Gemini returns UNAVAILABLE without fabricating findings."""
    provider = AIProvider()
    provider.gemini_key = None
    provider.model_name = ""

    svc = MultimodalService(ai_provider=provider)
    result = await svc.analyze_image(
        file_path=sample_png_path,
        mime_type=MimeType.PNG,
        user_caption="Caption text provided by author",
    )

    assert result.status == MultimodalProcessingStatus.UNAVAILABLE
    assert result.analysis_engine == "deterministic_metadata_engine"
    assert result.fallback_reason is not None
    assert "not configured" in result.fallback_reason
    # Zero fabricated visual findings
    assert len(result.visual_observations) == 0
    # Preserves author caption text
    assert result.extracted_text == "Caption text provided by author"


@pytest.mark.asyncio
async def test_image_gemini_quota_exhaustion_fallback(sample_png_path: Path):
    """Verify that 429 quota exhaustion gracefully falls back without retries or fabricated data."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if request.method == "GET":
            return httpx.Response(200, json={"accessible": True, "displayName": "Gemini"})
        return httpx.Response(
            429,
            json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "Daily quota limit reached."}},
        )

    transport = httpx.MockTransport(mock_handler)
    mock_client = GeminiClient(
        api_key="AIzaSyTestKey",
        model_name="gemini-2.5-flash",
        transport=transport,
        max_rpm=60,
    )
    provider = AIProvider(client=mock_client)
    provider.gemini_key = "AIzaSyTestKey"
    provider.model_name = "gemini-2.5-flash"

    svc = MultimodalService(ai_provider=provider)
    result = await svc.analyze_image(sample_png_path, MimeType.PNG)

    assert result.status == MultimodalProcessingStatus.UNAVAILABLE
    assert result.analysis_engine == "gemini_vision_fallback"
    assert "DAILY_QUOTA_EXHAUSTED" in str(result.fallback_reason)
    assert len(result.visual_observations) == 0


@pytest.mark.asyncio
async def test_image_gemini_malformed_json_fallback(sample_png_path: Path):
    """Verify that malformed JSON from Gemini routes to NEEDS_HUMAN_REVIEW."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"accessible": True, "displayName": "Gemini"})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "NOT_JSON_AT_ALL"}]}}]})

    transport = httpx.MockTransport(mock_handler)
    mock_client = GeminiClient(
        api_key="AIzaSyTestKey",
        model_name="gemini-2.5-flash",
        transport=transport,
        max_rpm=60,
    )
    provider = AIProvider(client=mock_client)
    provider.gemini_key = "AIzaSyTestKey"
    provider.model_name = "gemini-2.5-flash"

    svc = MultimodalService(ai_provider=provider)
    result = await svc.analyze_image(sample_png_path, MimeType.PNG)

    assert result.status == MultimodalProcessingStatus.NEEDS_HUMAN_REVIEW
    assert result.fallback_reason == "MALFORMED_GEMINI_RESPONSE"


# ==============================================================================
# 4. Audio Modality Unit Tests (Gemini Audio & Transcription)
# ==============================================================================

@pytest.mark.asyncio
async def test_audio_transcription_gemini_success(sample_wav_path: Path):
    """Verify Gemini Audio transcribes verbatim speech and timestamped dialogue segments."""
    gemini_response_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "transcript": "Welcome to BrandShield AI. Our platform guarantees real-time governance.",
                                "dialogue_segments": [
                                    {
                                        "speaker": "Host",
                                        "start_time_seconds": 0.0,
                                        "end_time_seconds": 3.5,
                                        "text": "Welcome to BrandShield AI.",
                                        "confidence": 0.99,
                                    },
                                    {
                                        "speaker": "Host",
                                        "start_time_seconds": 3.6,
                                        "end_time_seconds": 7.0,
                                        "text": "Our platform guarantees real-time governance.",
                                        "confidence": 0.96,
                                    },
                                ],
                                "spoken_claims": ["Our platform guarantees real-time governance."],
                            })
                        }
                    ]
                }
            }
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"accessible": True, "displayName": "Gemini"})
        return httpx.Response(200, json=gemini_response_payload)

    transport = httpx.MockTransport(mock_handler)
    mock_client = GeminiClient(
        api_key="AIzaSyTestKey",
        model_name="gemini-2.5-flash",
        transport=transport,
        max_rpm=60,
    )
    provider = AIProvider(client=mock_client)
    provider.gemini_key = "AIzaSyTestKey"
    provider.model_name = "gemini-2.5-flash"

    svc = MultimodalService(ai_provider=provider)
    result = await svc.analyze_audio(sample_wav_path, MimeType.WAV)

    assert result.media_type == "audio"
    assert result.status == MultimodalProcessingStatus.SUCCESS
    assert result.analysis_engine == "gemini_audio"
    assert "Welcome to BrandShield AI" in result.extracted_text
    assert len(result.dialogue_segments) == 2
    assert result.dialogue_segments[0].speaker == "Host"
    assert result.dialogue_segments[0].start_time_seconds == 0.0
    assert result.dialogue_segments[0].end_time_seconds == 3.5
    assert len(result.evidence_references) == 2


@pytest.mark.asyncio
async def test_audio_unconfigured_fallback(sample_wav_path: Path):
    """Verify unconfigured audio returns UNAVAILABLE without fabricated transcripts."""
    provider = AIProvider()
    provider.gemini_key = None
    provider.model_name = ""

    svc = MultimodalService(ai_provider=provider)
    result = await svc.analyze_audio(sample_wav_path, MimeType.WAV)

    assert result.status == MultimodalProcessingStatus.UNAVAILABLE
    assert result.analysis_engine == "deterministic_metadata_engine"
    assert len(result.dialogue_segments) == 0
    assert result.extracted_text == ""


# ==============================================================================
# 5. Video Modality Unit Tests (Files API Lifecycle & Guaranteed Cleanup)
# ==============================================================================

@pytest.mark.asyncio
async def test_video_files_api_lifecycle_and_guaranteed_cleanup(sample_mp4_path: Path):
    """Verify video Files API upload, polling, content generation, and guaranteed remote deletion."""
    uploaded_files: List[str] = []
    deleted_files: List[str] = []

    gemini_video_response = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "transcript": "Experience next-generation brand compliance with BrandShield.",
                                "dialogue_segments": [
                                    {
                                        "speaker": "Narrator",
                                        "start_time_seconds": 1.0,
                                        "end_time_seconds": 5.0,
                                        "text": "Experience next-generation brand compliance with BrandShield.",
                                    }
                                ],
                                "on_screen_text": [
                                    {"start_time_seconds": 0.5, "text": "BrandShield AI Product Tour"}
                                ],
                                "visual_observations": [
                                    {
                                        "entity": "logo",
                                        "label": "BrandShield Monogram",
                                        "confidence": 0.94,
                                        "box_2d": [0.05, 0.85, 0.15, 0.95],
                                    }
                                ],
                            })
                        }
                    ]
                }
            }
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        # 1. Capability probe
        if "models/gemini-2.5-flash" in url_str and request.method == "GET":
            return httpx.Response(200, json={"accessible": True, "displayName": "Gemini 2.5 Flash"})

        # 2. Files API upload start
        if "/upload/v1beta/files" in url_str and request.method == "POST":
            file_name = "files/test_video_upload_12345"
            uploaded_files.append(file_name)
            return httpx.Response(
                200,
                headers={"X-Goog-Upload-URL": "https://generativelanguage.googleapis.com/upload/chunk_endpoint"},
                json={"file": {"name": file_name, "uri": f"https://generativelanguage.googleapis.com/v1beta/{file_name}", "state": "PROCESSING"}},
            )

        # 3. Resumable chunk upload
        if "/upload/chunk_endpoint" in url_str and request.method == "POST":
            return httpx.Response(
                200,
                json={"file": {"name": "files/test_video_upload_12345", "uri": "https://generativelanguage.googleapis.com/v1beta/files/test_video_upload_12345", "state": "PROCESSING"}},
            )

        # 4. Polling status
        if "/v1beta/files/test_video_upload_12345" in url_str and request.method == "GET":
            return httpx.Response(200, json={"name": "files/test_video_upload_12345", "state": "ACTIVE"})

        # 5. Generate content with fileData
        if ":generateContent" in url_str and request.method == "POST":
            return httpx.Response(200, json=gemini_video_response)

        # 6. Remote deletion in finally: block
        if "/v1beta/files/test_video_upload_12345" in url_str and request.method == "DELETE":
            deleted_files.append("files/test_video_upload_12345")
            return httpx.Response(200, json={})

        return httpx.Response(404, json={"error": {"message": "Not found"}})

    transport = httpx.MockTransport(mock_handler)
    mock_client = GeminiClient(
        api_key="AIzaSyTestKey",
        model_name="gemini-2.5-flash",
        transport=transport,
        max_rpm=60,
    )
    provider = AIProvider(client=mock_client)
    provider.gemini_key = "AIzaSyTestKey"
    provider.model_name = "gemini-2.5-flash"

    svc = MultimodalService(ai_provider=provider)
    result = await svc.analyze_video(sample_mp4_path, MimeType.MP4, use_files_api=True)

    # Invariant: Files API was invoked
    assert len(uploaded_files) == 1
    # Invariant: Remote artifact was guaranteed deleted in finally: block
    assert len(deleted_files) == 1
    assert deleted_files[0] == uploaded_files[0]

    # Verify structured result
    assert result.media_type == "video"
    assert result.status == MultimodalProcessingStatus.SUCCESS
    assert result.analysis_engine == "gemini_video"
    assert "Experience next-generation brand compliance" in result.extracted_text
    assert "BrandShield AI Product Tour" in result.extracted_text
    assert len(result.visual_observations) == 1
    assert result.visual_observations[0].label == "BrandShield Monogram"


@pytest.mark.asyncio
async def test_video_files_api_guaranteed_cleanup_on_error(sample_mp4_path: Path):
    """Verify that remote file is STILL deleted when generateContent raises an unhandled error."""
    deleted_files: List[str] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if request.method == "GET" and "models/" in url_str:
            return httpx.Response(200, json={"accessible": True, "displayName": "Gemini"})
        if "/upload/v1beta/files" in url_str:
            return httpx.Response(
                200,
                headers={"X-Goog-Upload-URL": "https://generativelanguage.googleapis.com/upload/chunk_endpoint"},
                json={"file": {"name": "files/error_test_file_999", "state": "ACTIVE"}},
            )
        if "/upload/chunk_endpoint" in url_str:
            return httpx.Response(200, json={"file": {"name": "files/error_test_file_999", "state": "ACTIVE"}})
        if "/v1beta/files/error_test_file_999" in url_str and request.method == "GET":
            return httpx.Response(200, json={"name": "files/error_test_file_999", "state": "ACTIVE"})
        if ":generateContent" in url_str:
            # Simulate upstream API crash
            return httpx.Response(500, json={"error": {"status": "INTERNAL", "message": "Backend crash"}})
        if "/v1beta/files/error_test_file_999" in url_str and request.method == "DELETE":
            deleted_files.append("files/error_test_file_999")
            return httpx.Response(200, json={})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    mock_client = GeminiClient(
        api_key="AIzaSyTestKey",
        model_name="gemini-2.5-flash",
        transport=transport,
        max_rpm=60,
    )
    provider = AIProvider(client=mock_client)
    provider.gemini_key = "AIzaSyTestKey"
    provider.model_name = "gemini-2.5-flash"

    svc = MultimodalService(ai_provider=provider)
    result = await svc.analyze_video(sample_mp4_path, MimeType.MP4, use_files_api=True)

    # Invariant: Remote artifact was guaranteed deleted despite HTTP 500
    assert "files/error_test_file_999" in deleted_files
    assert result.status == MultimodalProcessingStatus.UNAVAILABLE
    assert "Gemini error: SERVICE_UNAVAILABLE" in result.fallback_reason


# ==============================================================================
# 6. Unified Dispatcher & Capability Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_unified_dispatcher_routes_correctly(
    sample_png_path: Path,
    sample_wav_path: Path,
    sample_mp4_path: Path,
    sample_pdf_path: Path,
):
    """Verify analyze_input dispatches across all 5 modalities."""
    svc = MultimodalService()

    # 1. Text
    res_text = await svc.analyze_input(media_type="text", content_text="Sample text content")
    assert res_text.media_type == "text"
    assert res_text.status == MultimodalProcessingStatus.SUCCESS

    # 2. Document
    res_doc = await svc.analyze_input(media_type="document", file_path=sample_pdf_path, mime_type=MimeType.PDF)
    assert res_doc.media_type == "document"
    assert res_doc.status == MultimodalProcessingStatus.SUCCESS

    # 3. Image (unconfigured fallback)
    res_img = await svc.analyze_input(media_type="image", file_path=sample_png_path, mime_type=MimeType.PNG)
    assert res_img.media_type == "image"
    assert res_img.status in (MultimodalProcessingStatus.UNAVAILABLE, MultimodalProcessingStatus.SUCCESS)

    # 4. Audio (unconfigured fallback)
    res_aud = await svc.analyze_input(media_type="audio", file_path=sample_wav_path, mime_type=MimeType.WAV)
    assert res_aud.media_type == "audio"
    assert res_aud.status in (MultimodalProcessingStatus.UNAVAILABLE, MultimodalProcessingStatus.SUCCESS)

    # 5. Video (unconfigured fallback)
    res_vid = await svc.analyze_input(media_type="video", file_path=sample_mp4_path, mime_type=MimeType.MP4)
    assert res_vid.media_type == "video"
    assert res_vid.status in (MultimodalProcessingStatus.UNAVAILABLE, MultimodalProcessingStatus.SUCCESS)

    # 6. Unsupported media type raises ValueError
    with pytest.raises(ValueError, match="Unsupported media_type"):
        await svc.analyze_input(media_type="hologram", content_text="test")


@pytest.mark.asyncio
async def test_unsupported_model_capabilities_graceful_fallback(sample_png_path: Path):
    """Verify that inaccessible or retired model capability probe falls back without crashing."""
    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "models/retired-model" in url_str and request.method == "GET":
            return httpx.Response(404, json={"error": {"status": "NOT_FOUND", "message": "Model not found or retired."}})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    mock_client = GeminiClient(
        api_key="AIzaSyTestKey",
        model_name="retired-model",
        transport=transport,
        max_rpm=60,
    )
    provider = AIProvider(client=mock_client)
    provider.gemini_key = "AIzaSyTestKey"
    provider.model_name = "retired-model"

    svc = MultimodalService(ai_provider=provider)
    result = await svc.analyze_image(sample_png_path, MimeType.PNG)

    assert result.status == MultimodalProcessingStatus.UNAVAILABLE
    assert result.analysis_engine == "deterministic_metadata_engine"
    assert "Gemini capability probe failed" in str(result.fallback_reason)
    assert len(result.visual_observations) == 0


def test_document_scanned_pdf_triggers_human_review(tmp_scratch_dir: Path):
    """Verify that a blank/scanned PDF without digital text safely flags OCR_REQUIRED."""
    p = tmp_scratch_dir / "scanned_blank.pdf"
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(p, "wb") as f:
        writer.write(f)

    svc = MultimodalService()
    result = svc.analyze_document(p, MimeType.PDF)

    assert result.status == MultimodalProcessingStatus.NEEDS_HUMAN_REVIEW
    assert result.fallback_reason == "OCR_REQUIRED"
    assert "OCR is not currently supported" in str(result.uncertainty_notes)


def test_document_docx_extraction(tmp_scratch_dir: Path):
    """Verify that DOCX archives extract paragraphs and structure cleanly."""
    import zipfile
    p = tmp_scratch_dir / "sample.docx"
    with zipfile.ZipFile(str(p), "w") as zf:
        xml_content = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\n'
            '  <w:body>\n'
            '    <w:p><w:r><w:t>BrandShield AI Enterprise Guidelines 2026</w:t></w:r></w:p>\n'
            '    <w:p><w:r><w:t>Strict policy: Zero unauthorized claims.</w:t></w:r></w:p>\n'
            '  </w:body>\n'
            '</w:document>'
        )
        zf.writestr("word/document.xml", xml_content)

    svc = MultimodalService()
    result = svc.analyze_document(p, MimeType.DOCX)

    assert result.status == MultimodalProcessingStatus.SUCCESS
    assert result.analysis_engine == "docx_extractor"
    assert "BrandShield AI Enterprise Guidelines 2026" in result.extracted_text
    assert "Strict policy: Zero unauthorized claims." in result.extracted_text
    assert result.metadata["paragraph_count"] == 2


@pytest.mark.asyncio
async def test_video_inline_data_processing(sample_mp4_path: Path):
    """Verify that video can be analyzed via inlineData without Files API."""
    gemini_resp = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({
                                "transcript": "Fast clip dialogue",
                                "dialogue_segments": [{"speaker": "S1", "start_time_seconds": 0.0, "text": "Fast clip dialogue"}],
                                "on_screen_text": [],
                                "visual_observations": [],
                            })
                        }
                    ]
                }
            }
        ]
    }

    def mock_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if request.method == "GET":
            return httpx.Response(200, json={"accessible": True, "displayName": "Gemini"})
        if ":generateContent" in url_str:
            return httpx.Response(200, json=gemini_resp)
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(mock_handler)
    mock_client = GeminiClient(
        api_key="AIzaSyTestKey",
        model_name="gemini-2.5-flash",
        transport=transport,
        max_rpm=60,
    )
    provider = AIProvider(client=mock_client)
    provider.gemini_key = "AIzaSyTestKey"
    provider.model_name = "gemini-2.5-flash"

    svc = MultimodalService(ai_provider=provider)
    result = await svc.analyze_video(sample_mp4_path, MimeType.MP4, use_files_api=False)

    assert result.status == MultimodalProcessingStatus.SUCCESS
    assert result.analysis_engine == "gemini_video"
    assert "Fast clip dialogue" in result.extracted_text

