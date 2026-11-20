"""Comprehensive test suite for Phase 2 Stage 2B: Backend Upload API & Compliance Pipeline Integration.

Validates:
1. Text-only submission via upload form (backward-compatible draft creation).
2. Document submission (PDF extraction, metadata, and optional immediate inspection).
3. Document submission (DOCX paragraph extraction as draft).
4. Image submission with accompanying copy and mocked Gemini Vision.
5. Audio submission with mocked speech transcription and dialogue segments.
6. Video submission with mocked Gemini Files API lifecycle and guaranteed cleanup.
7. Media type mismatch enforcement (e.g. PDF declared as image -> HTTP 400).
8. Content sniffing & extension spoofing defense (e.g. bash script renamed as .png -> HTTP 400).
9. Empty (0 bytes) file rejection -> HTTP 400.
10. Oversized file ceiling enforcement (> 10MB) -> HTTP 400.
11. Corrupted document handling -> HTTP 400.
12. Graceful fallback when Gemini is unavailable (honest status, no 500 crash).
13. Strict multi-tenant isolation (Org B cannot view or analyze Org A's upload).
14. Atomic transaction & duplicate ComplianceReport prevention on re-analysis.
15. Full backward compatibility of existing JSON POST /api/v1/submissions.
16. Immutable audit log entry creation with multimodal details.
"""

import io
import json
from pathlib import Path
import struct
from typing import Any, Dict, List
import uuid
import wave
import zipfile

import pypdf
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import create_access_token, get_password_hash
from app.engine.gemini_client import GeminiClientError, GeminiErrorCode
from app.engine.multimodal.service import (
    multimodal_service,
)
from app.main import app
from app.models.compliance import ComplianceReport
from app.models.guideline import BrandGuideline
from app.models.organization import Organization
from app.models.submission import ContentSubmission
from app.models.user import User


# ==============================================================================
# In-Memory Binary Helpers
# ==============================================================================

def make_png_bytes(width: int = 100, height: int = 100) -> bytes:
    """Generate minimal valid PNG bytes."""
    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    ihdr_crc = b"\x00\x00\x00\x00"
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc
    idat_chunk = struct.pack(">I", 0) + b"IDAT" + b"\x00\x00\x00\x00"
    iend_chunk = struct.pack(">I", 0) + b"IEND" + b"\xaeB`\x82"
    return header + ihdr_chunk + idat_chunk + iend_chunk


def make_mp4_bytes(duration_sec: float = 5.0, timescale: int = 1000) -> bytes:
    """Generate minimal MP4 container bytes."""
    ftyp_data = b"isom\x00\x00\x02\x00mp41"
    ftyp = struct.pack(">I", 8 + len(ftyp_data)) + b"ftyp" + ftyp_data
    duration_units = int(duration_sec * timescale)
    mvhd_body = b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, timescale, duration_units) + (b"\x00" * 80)
    mvhd_atom = struct.pack(">I", 8 + len(mvhd_body)) + b"mvhd" + mvhd_body
    moov_atom = struct.pack(">I", 8 + len(mvhd_atom)) + b"moov" + mvhd_atom
    return ftyp + moov_atom


def make_wav_bytes(duration_sec: float = 1.0, sample_rate: int = 8000) -> bytes:
    """Generate minimal WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        total_frames = int(sample_rate * duration_sec)
        w.writeframes(b"\x00\x00" * total_frames)
    return buf.getvalue()


def create_sample_pdf_bytes(text_lines: List[str]) -> bytes:
    """Generate in-memory valid digital PDF 1.4 bytes containing text."""
    writer = pypdf.PdfWriter()
    for text in text_lines:
        page = writer.add_blank_page(width=400, height=400)
        content_stream = DecodedStreamObject()
        content_stream.set_data(f"BT /F1 12 Tf 50 350 Td ({text}) Tj ET".encode("latin-1"))
        font_dict = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        fonts = DictionaryObject({NameObject("/F1"): font_dict})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): fonts})
        page[NameObject("/Contents")] = writer._add_object(content_stream)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def create_sample_docx_bytes(paragraphs: List[str]) -> bytes:
    """Generate in-memory valid DOCX bytes."""
    p_xml = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{p_xml}</w:body>
</w:document>"""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        zf.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


# ==============================================================================
# Database & Auth Fixtures
# ==============================================================================

@pytest_asyncio.fixture
async def multi_session():
    """Isolated async SQLite database session with 2 pre-seeded organizations."""
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with test_engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON;")
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with session_maker() as session:
        # 1. Organization A
        org_a = Organization(
            id=uuid.uuid4(),
            name="BrandShield Org A",
            slug="brandshield-org-a",
            is_active=True,
        )
        session.add(org_a)
        await session.flush()

        # Users for Org A
        user_a = User(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            email="author.a@brandshield.ai",
            hashed_password=get_password_hash("Password123!"),
            full_name="Alice Author (Org A)",
            role="CREATOR",
            is_active=True,
        )
        session.add(user_a)

        admin_a = User(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            email="admin.a@brandshield.ai",
            hashed_password=get_password_hash("Password123!"),
            full_name="Adam Admin (Org A)",
            role="ADMIN",
            is_active=True,
        )
        session.add(admin_a)

        # Active guideline for Org A
        gl_a = BrandGuideline(
            id=uuid.uuid4(),
            organization_id=org_a.id,
            name="BrandShield Naming Standard",
            rule_type="trademark_usage",
            severity="critical",
            description="Always write BrandShield AI with proper casing.",
            directive="The product name must strictly be 'BrandShield AI'. Never use 'Brandshield' or 'BrandShield'.",
            examples_approved=["BrandShield AI protects your brand."],
            examples_prohibited=["Brandshield protects your brand."],
            tags=["trademark", "product_name"],
            is_active=True,
        )
        session.add(gl_a)

        # 2. Organization B (for multi-tenant isolation testing)
        org_b = Organization(
            id=uuid.uuid4(),
            name="Competitor Org B",
            slug="competitor-org-b",
            is_active=True,
        )
        session.add(org_b)
        await session.flush()

        user_b = User(
            id=uuid.uuid4(),
            organization_id=org_b.id,
            email="bob.user@competitor.com",
            hashed_password=get_password_hash("Password123!"),
            full_name="Bob User (Org B)",
            role="CREATOR",
            is_active=True,
        )
        session.add(user_b)
        await session.commit()

        yield session

    await test_engine.dispose()


@pytest_asyncio.fixture
async def user_a_token(multi_session: AsyncSession) -> str:
    stmt = select(User).where(User.email == "author.a@brandshield.ai")
    user = (await multi_session.execute(stmt)).scalar_one()
    return create_access_token(
        subject=str(user.id),
        org_id=str(user.organization_id),
        role=user.role,
        email=user.email,
        full_name=user.full_name,
    )


@pytest_asyncio.fixture
async def user_b_token(multi_session: AsyncSession) -> str:
    stmt = select(User).where(User.email == "bob.user@competitor.com")
    user = (await multi_session.execute(stmt)).scalar_one()
    return create_access_token(
        subject=str(user.id),
        org_id=str(user.organization_id),
        role=user.role,
        email=user.email,
        full_name=user.full_name,
    )


@pytest_asyncio.fixture
async def async_client(multi_session: AsyncSession, user_a_token: str):
    async def override_get_db():
        yield multi_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {user_a_token}"},
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ==============================================================================
# Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_upload_text_only_submission_success(async_client: AsyncClient):
    """Multipart upload without file creates a valid text submission draft."""
    form_data = {
        "title": "Social Campaign Post",
        "content": "BrandShield AI protects your brand reputation across all digital channels.",
        "media_type": "text",
        "target_channel": "linkedin",
        "target_audience": "Enterprise Compliance Leaders",
        "submit_for_inspection": "false",
    }
    response = await async_client.post("/api/v1/submissions/upload", data=form_data)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Social Campaign Post"
    assert data["media_type"] == "text"
    assert data["status"] == "draft"
    assert data["file_hash_sha256"] is None
    assert data["file_size_bytes"] is None
    assert data["multimodal_metadata"] == {}


@pytest.mark.asyncio
async def test_upload_text_only_submission_missing_content(async_client: AsyncClient):
    """Uploading text media_type without content text or file is rejected with HTTP 400."""
    form_data = {
        "title": "Empty Post",
        "media_type": "text",
        "target_channel": "linkedin",
    }
    response = await async_client.post("/api/v1/submissions/upload", data=form_data)
    assert response.status_code == 400
    err_msg = response.json().get("message") or response.json().get("detail", "")
    assert "Content text is required when no media file is uploaded" in err_msg


@pytest.mark.asyncio
async def test_upload_media_type_without_file_rejected(async_client: AsyncClient):
    """Declaring media_type='image' without attaching a file is rejected with HTTP 400."""
    form_data = {
        "title": "Missing Image File",
        "content": "Caption here",
        "media_type": "image",
        "target_channel": "twitter_x",
    }
    response = await async_client.post("/api/v1/submissions/upload", data=form_data)
    assert response.status_code == 400
    err_msg = response.json().get("message") or response.json().get("detail", "")
    assert "A media file must be uploaded when media_type is 'image'" in err_msg


@pytest.mark.asyncio
async def test_upload_pdf_document_extraction_and_immediate_inspection(async_client: AsyncClient):
    """Valid PDF upload extracts text, calculates SHA-256, and executes automated compliance inspection."""
    pdf_bytes = create_sample_pdf_bytes([
        "BrandShield AI Enterprise Brand Guidelines and Mandatory Standards",
        "Approved brand terminology: BrandShield AI, Enterprise Shield.",
        "Prohibited statements: Brandshield protects your brand automatically.",
    ])

    files = {
        "file": ("guidelines.pdf", pdf_bytes, "application/pdf")
    }
    form_data = {
        "title": "PDF Document Ingestion Test",
        "media_type": "document",
        "target_channel": "blog_post",
        "submit_for_inspection": "true",
    }

    response = await async_client.post(
        "/api/v1/submissions/upload",
        data=form_data,
        files=files,
    )
    assert response.status_code == 201
    data = response.json()

    assert data["media_type"] == "document"
    assert data["mime_type"] == "application/pdf"
    assert data["file_hash_sha256"] is not None
    assert len(data["file_hash_sha256"]) == 64
    assert data["file_size_bytes"] == len(pdf_bytes)
    assert "BrandShield AI" in data["content"]

    meta = data["multimodal_metadata"]
    assert meta["page_count"] >= 1
    assert meta["processing_status"] == "SUCCESS"
    assert meta["analysis_engine"] in ["pypdf_extractor", "pure_python_document_extractor"]
    assert meta["original_filename"] == "guidelines.pdf"

    # Since prohibited text 'Brandshield' matches our guideline, status must be VIOLATIONS_FOUND
    assert data["status"] == "violations_found"

    # Verify report is created and retrievable via reports API
    report_res = await async_client.get(f"/api/v1/submissions/{data['id']}/report")
    assert report_res.status_code == 200
    report_data = report_res.json()
    assert report_data["total_violations"] >= 1
    assert len(report_data["violations"]) >= 1


@pytest.mark.asyncio
async def test_upload_docx_document_extraction_as_draft(async_client: AsyncClient):
    """Valid DOCX upload extracts paragraph content and saves draft without running inspection."""
    docx_bytes = create_sample_docx_bytes([
        "BrandShield AI Q4 Announcement",
        "We are pleased to introduce new security features for enterprise clients.",
        "Contact sales for enterprise licensing details.",
    ])

    files = {
        "file": ("announcement.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    }
    form_data = {
        "title": "Q4 Announcement DOCX",
        "media_type": "document",
        "target_channel": "email_newsletter",
        "submit_for_inspection": "false",
    }

    response = await async_client.post(
        "/api/v1/submissions/upload",
        data=form_data,
        files=files,
    )
    assert response.status_code == 201
    data = response.json()

    assert data["status"] == "draft"
    assert data["media_type"] == "document"
    assert "BrandShield AI Q4 Announcement" in data["content"]
    assert data["multimodal_metadata"]["paragraph_count"] >= 3
    assert data["compliance_report"] is None


@pytest.mark.asyncio
async def test_upload_image_with_caption_and_mock_gemini(async_client: AsyncClient):
    """Image upload merges OCR text with accompanying caption and stores visual observations."""
    png_bytes = make_png_bytes(width=800, height=600)

    mock_gemini_res = {
        "on_screen_text": "BrandShield AI - The Gold Standard in Governance",
        "dominant_colors": [{"hex": "#0052CC", "name": "Primary Blue", "percentage": 80}],
        "logos": [
            {
                "label": "BrandShield AI Primary Logo",
                "confidence": 0.96,
                "box_2d": [0.1, 0.1, 0.5, 0.5],
                "notes": "Correct vector representation",
            }
        ],
        "visual_compliance_notes": ["Proper clear space observed"],
    }

    with patch.object(
        multimodal_service,
        "_check_ai_readiness",
        new=AsyncMock(return_value=(True, None)),
    ), patch.object(
        multimodal_service.client,
        "generate_content",
        new=AsyncMock(return_value={"candidates": [{"content": {"parts": [{"text": json.dumps(mock_gemini_res)}]}}]}),
    ):
        files = {
            "file": ("campaign_banner.png", png_bytes, "image/png")
        }
        form_data = {
            "title": "Q4 Twitter Banner Graphic",
            "content": "Accompanying promotional tweet copy.",
            "media_type": "image",
            "target_channel": "twitter_x",
            "submit_for_inspection": "false",
        }

        response = await async_client.post(
            "/api/v1/submissions/upload",
            data=form_data,
            files=files,
        )
        assert response.status_code == 201
        data = response.json()

        assert data["media_type"] == "image"
        assert data["mime_type"] == "image/png"
        assert "Accompanying promotional tweet copy." in data["content"]
        assert "BrandShield AI - The Gold Standard in Governance" in data["content"]

        meta = data["multimodal_metadata"]
        assert meta["processing_status"] == "SUCCESS"
        assert meta["dimensions"] == [800, 600]
        assert len(meta["visual_observations"]) >= 1
        assert any(o["label"] == "BrandShield AI Primary Logo" for o in meta["visual_observations"])


@pytest.mark.asyncio
async def test_upload_audio_with_mock_transcription(async_client: AsyncClient):
    """Audio upload produces transcript and dialogue segments from Gemini analysis."""
    wav_bytes = make_wav_bytes(duration_sec=2.0)

    mock_audio_res = {
        "transcript": "Welcome to the BrandShield AI compliance briefing.",
        "dialogue_segments": [
            {
                "speaker": "Speaker 1",
                "start_time_seconds": 0.0,
                "end_time_seconds": 2.0,
                "text": "Welcome to the BrandShield AI compliance briefing.",
                "confidence": 0.95,
            }
        ],
        "spoken_claims": ["BrandShield AI provides governance"],
    }

    with patch.object(
        multimodal_service,
        "_check_ai_readiness",
        new=AsyncMock(return_value=(True, None)),
    ), patch.object(
        multimodal_service.client,
        "generate_content",
        new=AsyncMock(return_value={"candidates": [{"content": {"parts": [{"text": json.dumps(mock_audio_res)}]}}]}),
    ):
        files = {
            "file": ("podcast_clip.wav", wav_bytes, "audio/wav")
        }
        form_data = {
            "title": "Podcast Episode 1 Audio",
            "media_type": "audio",
            "target_channel": "other",
            "submit_for_inspection": "false",
        }

        response = await async_client.post(
            "/api/v1/submissions/upload",
            data=form_data,
            files=files,
        )
        assert response.status_code == 201
        data = response.json()

        assert data["media_type"] == "audio"
        assert "Welcome to the BrandShield AI compliance briefing." in data["content"]

        meta = data["multimodal_metadata"]
        assert meta["processing_status"] == "SUCCESS"
        assert len(meta["dialogue_segments"]) == 1
        assert meta["dialogue_segments"][0]["speaker"] == "Speaker 1"


@pytest.mark.asyncio
async def test_upload_video_files_api_lifecycle(async_client: AsyncClient):
    """Video upload routes through Gemini Files API lifecycle and deletes remote asset."""
    mp4_bytes = make_mp4_bytes(duration_sec=5.0)

    mock_video_res = {
        "transcript": "BrandShield AI stops brand risks.",
        "dialogue_segments": [
            {
                "speaker": "Presenter",
                "start_time_seconds": 0.0,
                "end_time_seconds": 4.5,
                "text": "See how BrandShield AI stops brand risks.",
            }
        ],
        "on_screen_text": [
            {"start_time_seconds": 0.0, "end_time_seconds": 3.0, "text": "BrandShield AI Enterprise Demo"}
        ],
        "visual_observations": [
            {
                "entity": "screencast",
                "label": "Product Dashboard",
                "confidence": 0.91,
                "box_2d": [0.0, 0.0, 1.0, 1.0],
            }
        ],
    }

    mock_upload = AsyncMock(return_value={"name": "files/test_video_123", "uri": "https://gemini/files/123", "state": "PROCESSING"})
    mock_poll = AsyncMock(return_value={"name": "files/test_video_123", "uri": "https://gemini/files/123", "state": "ACTIVE"})
    mock_gen = AsyncMock(return_value={"candidates": [{"content": {"parts": [{"text": json.dumps(mock_video_res)}]}}]})
    mock_del = AsyncMock(return_value=True)

    with patch.object(multimodal_service, "_check_ai_readiness", new=AsyncMock(return_value=(True, None))), \
         patch.object(multimodal_service.client, "upload_file", mock_upload), \
         patch.object(multimodal_service.client, "poll_file_active", mock_poll), \
         patch.object(multimodal_service.client, "generate_content", mock_gen), \
         patch.object(multimodal_service.client, "delete_file", mock_del):

        files = {
            "file": ("demo.mp4", mp4_bytes, "video/mp4")
        }
        form_data = {
            "title": "Product Demo Video",
            "media_type": "video",
            "target_channel": "other",
            "submit_for_inspection": "false",
        }

        response = await async_client.post(
            "/api/v1/submissions/upload",
            data=form_data,
            files=files,
        )
        assert response.status_code == 201
        data = response.json()

        assert data["media_type"] == "video"
        assert "BrandShield AI stops brand risks." in data["content"]
        assert mock_upload.called
        assert mock_poll.called
        assert mock_del.called
        assert mock_del.call_args[0][0] == "files/test_video_123"


@pytest.mark.asyncio
async def test_upload_media_type_mismatch_rejected(async_client: AsyncClient):
    """Sending a PDF file while declaring media_type='image' returns HTTP 400."""
    pdf_bytes = create_sample_pdf_bytes(["Sample text"])
    files = {
        "file": ("doc.pdf", pdf_bytes, "application/pdf")
    }
    form_data = {
        "title": "Mismatched Upload",
        "media_type": "image",
        "target_channel": "twitter_x",
    }

    response = await async_client.post(
        "/api/v1/submissions/upload",
        data=form_data,
        files=files,
    )
    assert response.status_code == 400
    err_msg = response.json().get("message") or response.json().get("detail", "")
    assert "Mismatch between selected media_type 'image' and detected file format 'document'" in err_msg


@pytest.mark.asyncio
async def test_upload_invalid_mime_type_spoofing(async_client: AsyncClient):
    """Uploading a bash script disguised as a PNG file returns HTTP 400."""
    script_bytes = b"#!/bin/bash\necho 'malicious shell script'\n"
    files = {
        "file": ("exploit.png", script_bytes, "image/png")
    }
    form_data = {
        "title": "Spoofed Extension Attempt",
        "media_type": "image",
        "target_channel": "twitter_x",
    }

    response = await async_client.post(
        "/api/v1/submissions/upload",
        data=form_data,
        files=files,
    )
    assert response.status_code == 400
    err_msg = response.json().get("message") or response.json().get("detail", "")
    assert "Upload validation failed" in err_msg


@pytest.mark.asyncio
async def test_upload_empty_file_rejected(async_client: AsyncClient):
    """Uploading a 0-byte file is rejected with HTTP 400."""
    files = {
        "file": ("empty.png", b"", "image/png")
    }
    form_data = {
        "title": "Empty File Upload",
        "media_type": "image",
        "target_channel": "twitter_x",
    }

    response = await async_client.post(
        "/api/v1/submissions/upload",
        data=form_data,
        files=files,
    )
    assert response.status_code == 400
    err_msg = response.json().get("message") or response.json().get("detail", "")
    assert "Uploaded file is empty (0 bytes)" in err_msg


@pytest.mark.asyncio
async def test_upload_oversized_file_rejected(async_client: AsyncClient, monkeypatch):
    """Streaming file larger than configured ceiling raises HTTP 400."""
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_BYTES", 1024)  # 1KB ceiling for testing

    large_bytes = b"X" * 2048
    files = {
        "file": ("oversized.pdf", large_bytes, "application/pdf")
    }
    form_data = {
        "title": "Oversized Document",
        "media_type": "document",
        "target_channel": "blog_post",
    }

    response = await async_client.post(
        "/api/v1/submissions/upload",
        data=form_data,
        files=files,
    )
    assert response.status_code == 400
    err_msg = response.json().get("message") or response.json().get("detail", "")
    assert "Uploaded file exceeds maximum limit" in err_msg


@pytest.mark.asyncio
async def test_upload_corrupted_document_rejected(async_client: AsyncClient):
    """Corrupted document payload returns HTTP 400 without crashing backend."""
    corrupted_pdf = b"%PDF-1.4\nCorrupted content completely invalid"
    files = {
        "file": ("corrupt.pdf", corrupted_pdf, "application/pdf")
    }
    form_data = {
        "title": "Corrupted Document",
        "media_type": "document",
        "target_channel": "blog_post",
    }

    response = await async_client.post(
        "/api/v1/submissions/upload",
        data=form_data,
        files=files,
    )
    assert response.status_code == 400
    err_msg = response.json().get("message") or response.json().get("detail", "")
    assert "Upload validation failed" in err_msg


@pytest.mark.asyncio
async def test_upload_gemini_unavailable_graceful_fallback(async_client: AsyncClient):
    """When Gemini is offline or unconfigured, media upload succeeds with honest status and caption."""
    png_bytes = make_png_bytes(width=400, height=300)

    with patch.object(
        multimodal_service,
        "_check_ai_readiness",
        new=AsyncMock(return_value=(True, None)),
    ), patch.object(
        multimodal_service.client,
        "generate_content",
        side_effect=GeminiClientError(
            message="Connection refused to Google AI API",
            error_code=GeminiErrorCode.SERVICE_UNAVAILABLE,
            is_retryable=True,
        ),
    ):
        files = {
            "file": ("offline_test.png", png_bytes, "image/png")
        }
        form_data = {
            "title": "Gemini Fallback Test",
            "content": "Manual caption submitted with image asset.",
            "media_type": "image",
            "target_channel": "twitter_x",
            "submit_for_inspection": "false",
        }

        response = await async_client.post(
            "/api/v1/submissions/upload",
            data=form_data,
            files=files,
        )
        assert response.status_code == 201
        data = response.json()

        assert data["title"] == "Gemini Fallback Test"
        assert "Manual caption submitted with image asset." in data["content"]

        meta = data["multimodal_metadata"]
        assert meta["processing_status"] == "UNAVAILABLE"
        assert meta["analysis_engine"] == "gemini_vision_fallback"
        assert "Connection refused" in meta["fallback_reason"]


@pytest.mark.asyncio
async def test_upload_tenant_isolation(async_client: AsyncClient, user_b_token: str):
    """Submissions uploaded in Org A cannot be read or analyzed by users in Org B."""
    # 1. Upload in Org A
    form_data = {
        "title": "Org A Confidential Campaign",
        "content": "Proprietary announcement for Org A stakeholders only.",
        "media_type": "text",
        "target_channel": "email_newsletter",
        "submit_for_inspection": "false",
    }
    response = await async_client.post("/api/v1/submissions/upload", data=form_data)
    assert response.status_code == 201
    submission_id = response.json()["id"]

    # 2. User B in Org B attempts to retrieve submission
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {user_b_token}"},
    ) as client_b:
        get_res = await client_b.get(f"/api/v1/submissions/{submission_id}")
        assert get_res.status_code == 404

        analyze_res = await client_b.post(f"/api/v1/submissions/{submission_id}/analyze")
        assert analyze_res.status_code == 404


@pytest.mark.asyncio
async def test_upload_atomic_transaction_and_duplicate_report_prevention(
    async_client: AsyncClient,
    multi_session: AsyncSession,
):
    """Running inspection and then re-analyzing produces exactly one ComplianceReport record."""
    pdf_bytes = create_sample_pdf_bytes([
        "BrandShield AI Enterprise standard documentation.",
        "Compliance statement for automated checks.",
    ])

    files = {
        "file": ("inspection_test.pdf", pdf_bytes, "application/pdf")
    }
    form_data = {
        "title": "Deduplication Verification",
        "media_type": "document",
        "target_channel": "blog_post",
        "submit_for_inspection": "true",
    }

    # 1. Upload and inspect immediately
    response = await async_client.post(
        "/api/v1/submissions/upload",
        data=form_data,
        files=files,
    )
    assert response.status_code == 201
    sub_id = uuid.UUID(response.json()["id"])

    # 2. Trigger re-analysis via analyze endpoint
    reanalyze_res = await async_client.post(f"/api/v1/submissions/{sub_id}/analyze")
    assert reanalyze_res.status_code == 200

    # 3. Verify exactly 1 ComplianceReport exists for this submission and version
    report_stmt = select(ComplianceReport).where(
        ComplianceReport.submission_id == sub_id,
        ComplianceReport.submission_version == 1,
    )
    reports = (await multi_session.execute(report_stmt)).scalars().all()
    assert len(reports) == 1


@pytest.mark.asyncio
async def test_existing_json_submission_endpoint_backward_compatibility(async_client: AsyncClient):
    """The existing JSON POST /api/v1/submissions continues to operate with complete fidelity."""
    json_payload = {
        "title": "Legacy JSON API Draft",
        "content": "BrandShield AI safeguards trademark and brand consistency.",
        "target_channel": "linkedin",
        "target_audience": "Enterprise Compliance Officers",
        "metadata": {"campaign_id": "LEGACY_01"},
    }

    response = await async_client.post(
        "/api/v1/submissions",
        json=json_payload,
        params={"submit_for_inspection": False},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Legacy JSON API Draft"
    assert data["media_type"] == "text"
    assert data["status"] == "draft"
    assert data["metadata"] == {"campaign_id": "LEGACY_01"}


@pytest.mark.asyncio
async def test_audit_entry_recorded_on_upload(async_client: AsyncClient):
    """Audit entry records accurate multimodal details and user attribution."""
    pdf_bytes = create_sample_pdf_bytes(["BrandShield AI Audit Verification Document"])
    files = {
        "file": ("audit_sample.pdf", pdf_bytes, "application/pdf")
    }
    form_data = {
        "title": "Audit Trail Inspection",
        "media_type": "document",
        "target_channel": "blog_post",
        "submit_for_inspection": "false",
    }

    response = await async_client.post(
        "/api/v1/submissions/upload",
        data=form_data,
        files=files,
    )
    assert response.status_code == 201
    sub_id = response.json()["id"]

    # Retrieve audit logs
    audit_res = await async_client.get("/api/v1/submissions/audit-trail")
    assert audit_res.status_code == 200
    entries = audit_res.json()
    assert len(entries) >= 1

    entry = next(e for e in entries if e["submission_id"] == str(sub_id))
    assert entry["action_type"] == "create_multimodal_draft"
    assert entry["actor_name"] == "Alice Author (Org A)"
    assert entry["details"]["media_type"] == "document"
    assert entry["details"]["file_hash_sha256"] is not None
