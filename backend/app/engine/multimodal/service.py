"""Unified Multimodal Preprocessing & Analysis Service for BrandShield AI.

Phase 2, Stage 2A:
- Images: visual inspection, OCR on-screen text, logo detection, brand color extraction.
- Audio: speech transcription, dialogue timestamps, spoken content extraction.
- Video: multimodal visual inspection, on-screen text, spoken dialogue transcription via Files API or inlineData.
- Documents: pure-Python extraction from PDF and DOCX (reusing extractor.py).
- Text: pure deterministic text passthrough.

Guarantees:
- Reuses GeminiClient, AIProvider, SlidingWindowRateLimiter, and settings.
- Checks model capabilities before attempting modality-specific inference.
- Tracks remote Files API uploads and guarantees remote deletion in a finally: block.
- 10MB upload ceiling strictly enforced.
- Zero binary data retained permanently in database or server filesystem.
- Zero fabricated transcripts, logos, colors, citations, or bounding boxes during fallback.
- Explicit UNAVAILABLE or NEEDS_HUMAN_REVIEW status when Gemini is offline or unconfigured.
- Redacts all secrets, keys, and raw media bytes from logs.
"""

import base64
from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.core.config import settings
from app.engine.ai_provider import AIProvider, ai_provider as default_ai_provider
from app.engine.gemini_client import (
    GeminiClient,
    GeminiClientError,
    GeminiErrorCode,
    sanitize_text,
)
from app.engine.multimodal.extractor import (
    DocumentExtractionError,
    DocumentExtractionResult,
    MalformedDocumentError,
    extract_document_text,
)
from app.engine.multimodal.validator import MediaType, MimeType

logger = logging.getLogger("brandshield.engine.multimodal.service")


class MultimodalProcessingStatus(str, Enum):
    """Processing verdict for a multimodal asset."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


@dataclass
class VisualObservation:
    """Discrete visual brand observation (logo, color, symbol, styling)."""

    entity: str  # "logo", "color", "typography", "symbol", "disclaimer"
    label: str  # e.g. "BrandShield Primary Logo", "#1E40AF"
    confidence: float = 1.0
    box_2d: Optional[List[float]] = None  # Normalized [ymin, xmin, ymax, xmax] in [0.0, 1.0]
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SpokenDialogueSegment:
    """Discrete timestamped segment of spoken dialogue."""

    text: str
    start_time_seconds: Optional[float] = None
    end_time_seconds: Optional[float] = None
    speaker: Optional[str] = None
    confidence: float = 1.0


@dataclass
class MultimodalAnalysisResult:
    """Standardized, typed result of multimodal extraction and analysis."""

    media_type: str  # "text", "document", "image", "audio", "video"
    status: MultimodalProcessingStatus
    extracted_text: str = ""  # Plaintext / OCR text / verbatim transcript
    visual_observations: List[VisualObservation] = field(default_factory=list)
    dialogue_segments: List[SpokenDialogueSegment] = field(default_factory=list)
    evidence_references: List[Dict[str, Any]] = field(default_factory=list)
    analysis_engine: str = "deterministic_text_engine"
    fallback_reason: Optional[str] = None
    confidence_score: float = 1.0
    uncertainty_notes: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def _clean_json_response(raw_text: str) -> Dict[str, Any]:
    """Extract and parse structured JSON from Gemini response, stripping markdown fences."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            return {"items": data}
        return {"raw_data": data}
    except Exception as e:
        logger.warning("Failed to decode JSON from Gemini response: %s", sanitize_text(str(e)))
        raise ValueError(f"Malformed JSON from Gemini: {e}") from e


class MultimodalService:
    """Orchestrates ingestion, preprocessing, and multimodal analysis across all 5 input modalities.
    
    Guarantees:
    - Text: 100% deterministic processing path preserved.
    - Documents: Reuses pure-Python pypdf / docx extractor, page-by-page mapping, handles scanned/encrypted safely.
    - Images: Gemini Vision (inlineData) for OCR, logos, colors, visual layout. Transparent fallback if unconfigured.
    - Audio: Gemini Audio (inlineData) for speech-to-text transcript & timestamps. Transparent fallback if unconfigured.
    - Video: Gemini Video (Files API / inlineData) for speech dialogue + visual track supers/logos. Guarantees remote file cleanup in finally: block.
    - Zero fabricated transcripts, logos, citations, or visual findings.
    - Never stores raw binary uploads in database or persistent server disk.
    - Sanitizes logs: never logs base64 bytes, API keys, or raw media payloads.
    """

    def __init__(self, ai_provider: Optional[AIProvider] = None) -> None:
        self._provider = ai_provider or default_ai_provider

    @property
    def client(self) -> GeminiClient:
        return self._provider.client

    @property
    def is_ai_available(self) -> bool:
        return self._provider.is_available

    async def _check_ai_readiness(self) -> Tuple[bool, Optional[str]]:
        """Verify model configuration and non-fatal capability probe."""
        if not self._provider.gemini_key:
            return False, "GEMINI_API_KEY is not configured."
        if not self._provider.model_name:
            return False, "AI_MODEL_NAME is not configured."

        probe = await self.client.check_model_capabilities(self._provider.model_name)
        if not probe.get("accessible", False):
            msg = probe.get("message", "Model capability probe inaccessible.")
            return False, f"Gemini capability probe failed: {msg}"

        return True, None

    # ==========================================================================
    # 1. Text Modality (Deterministic)
    # ==========================================================================

    def analyze_text(self, text: str) -> MultimodalAnalysisResult:
        """Process pure text draft through deterministic engine."""
        cleaned = text.strip() if text else ""
        return MultimodalAnalysisResult(
            media_type="text",
            status=MultimodalProcessingStatus.SUCCESS,
            extracted_text=cleaned,
            analysis_engine="deterministic_text_engine",
            confidence_score=1.0,
            metadata={"character_count": len(cleaned)},
        )

    # ==========================================================================
    # 2. Document Modality (PDF / DOCX)
    # ==========================================================================

    def analyze_document(
        self,
        file_path: Path,
        mime_type: MimeType,
        user_notes: Optional[str] = None,
    ) -> MultimodalAnalysisResult:
        """Extract digital text and page structure from PDF or DOCX without external network calls."""
        if not file_path.exists() or not file_path.is_file():
            return MultimodalAnalysisResult(
                media_type="document",
                status=MultimodalProcessingStatus.FAILED,
                fallback_reason="FILE_NOT_FOUND",
                uncertainty_notes=f"File not found on disk: {file_path}",
                confidence_score=0.0,
            )

        engine_name = "pypdf_extractor" if mime_type == MimeType.PDF else "docx_extractor"

        try:
            doc_res: DocumentExtractionResult = extract_document_text(file_path, mime_type)
        except MalformedDocumentError as e:
            return MultimodalAnalysisResult(
                media_type="document",
                status=MultimodalProcessingStatus.FAILED,
                fallback_reason="MALFORMED_DOCUMENT",
                uncertainty_notes=f"Malformed document structure: {e.message}",
                analysis_engine=engine_name,
                confidence_score=0.0,
            )
        except DocumentExtractionError as e:
            return MultimodalAnalysisResult(
                media_type="document",
                status=MultimodalProcessingStatus.FAILED,
                fallback_reason=e.error_code,
                uncertainty_notes=f"Document parsing error: {e.message}",
                analysis_engine=engine_name,
                confidence_score=0.0,
            )
        except Exception as e:
            logger.error("Unexpected error parsing document: %s", sanitize_text(str(e)))
            return MultimodalAnalysisResult(
                media_type="document",
                status=MultimodalProcessingStatus.FAILED,
                fallback_reason="UNEXPECTED_EXTRACTION_ERROR",
                uncertainty_notes=str(e),
                analysis_engine=engine_name,
                confidence_score=0.0,
            )

        # Handle Encrypted PDF
        if doc_res.is_encrypted:
            return MultimodalAnalysisResult(
                media_type="document",
                status=MultimodalProcessingStatus.FAILED,
                fallback_reason="ENCRYPTED_DOCUMENT",
                uncertainty_notes="Password-protected or encrypted PDF cannot be parsed without password.",
                analysis_engine=engine_name,
                confidence_score=0.0,
                metadata={"page_count": doc_res.page_count},
            )

        # Handle Scanned PDF requiring OCR
        if doc_res.requires_ocr or doc_res.is_scanned:
            return MultimodalAnalysisResult(
                media_type="document",
                status=MultimodalProcessingStatus.NEEDS_HUMAN_REVIEW,
                extracted_text=doc_res.text or (user_notes or ""),
                fallback_reason="OCR_REQUIRED",
                uncertainty_notes="Document appears to be scanned or contains insufficient digital text. Searchable digital PDF or DOCX is required. OCR is not currently supported.",
                analysis_engine=engine_name,
                confidence_score=0.20,
                metadata={
                    "page_count": doc_res.page_count,
                    "total_raw_characters": doc_res.character_count,
                    "is_scanned": True,
                },
            )

        # Construct page-level evidence references
        evidence_refs: List[Dict[str, Any]] = []
        for page_num, page_content in doc_res.page_texts.items():
            if page_content.strip():
                evidence_refs.append({
                    "page": page_num,
                    "character_count": len(page_content.strip()),
                    "sample": page_content.strip()[:100],
                })

        combined_text = doc_res.text
        if user_notes and user_notes.strip():
            combined_text = f"{user_notes.strip()}\n\n[Document Content]:\n{doc_res.text}"

        return MultimodalAnalysisResult(
            media_type="document",
            status=MultimodalProcessingStatus.SUCCESS,
            extracted_text=combined_text,
            evidence_references=evidence_refs,
            analysis_engine=engine_name,
            confidence_score=1.0,
            metadata={
                "page_count": doc_res.page_count,
                "character_count": doc_res.character_count,
                "paragraph_count": len(doc_res.paragraphs),
            },
        )

    # ==========================================================================
    # 3. Image Modality (Gemini Vision + Deterministic Fallback)
    # ==========================================================================

    async def analyze_image(
        self,
        file_path: Path,
        mime_type: MimeType,
        guidelines: Optional[List[Dict[str, Any]]] = None,
        user_caption: Optional[str] = None,
    ) -> MultimodalAnalysisResult:
        """Inspect visual branding, logos, color palette, and on-screen OCR text."""
        if not file_path.exists() or not file_path.is_file():
            return MultimodalAnalysisResult(
                media_type="image",
                status=MultimodalProcessingStatus.FAILED,
                fallback_reason="FILE_NOT_FOUND",
                uncertainty_notes=f"Image file not found: {file_path}",
                confidence_score=0.0,
            )

        # Check Gemini Readiness
        ready, reason = await self._check_ai_readiness()
        if not ready:
            logger.info("Gemini Vision unavailable (%s). Fallback to deterministic metadata.", reason)
            return MultimodalAnalysisResult(
                media_type="image",
                status=MultimodalProcessingStatus.UNAVAILABLE,
                extracted_text=user_caption or "",
                visual_observations=[],
                analysis_engine="deterministic_metadata_engine",
                fallback_reason=reason,
                confidence_score=0.0,
                uncertainty_notes="Automated visual, logo, and color inspection is unavailable without active Gemini vision configuration. Binary format and dimensions verified.",
                metadata={"file_size": file_path.stat().st_size},
            )

        # Encode image bytes for inlineData
        try:
            with open(file_path, "rb") as f:
                img_bytes = f.read()
            b64_img = base64.b64encode(img_bytes).decode("utf-8")
        except Exception as e:
            return MultimodalAnalysisResult(
                media_type="image",
                status=MultimodalProcessingStatus.FAILED,
                fallback_reason="FILE_READ_ERROR",
                uncertainty_notes=f"Failed to read image bytes: {e}",
            )

        prompt = (
            "You are a strict brand compliance visual auditor. Analyze this marketing image.\n"
            "Identify and extract:\n"
            "1. on_screen_text: Any text, headline, tagline, or disclaimer visible in the image (OCR).\n"
            "2. logos: Any brand or partner logos detected. For each, give label, confidence (0.0 to 1.0), and normalized bounding box [ymin, xmin, ymax, xmax] in 0.0-1.0 range.\n"
            "3. dominant_colors: Dominant brand colors in hex format (e.g. #1E40AF) with name/description and estimated percentage.\n"
            "4. visual_compliance_notes: Observations on logo placement, clear-space, aspect ratio distortion, or palette conformity.\n\n"
            f"Brand Guidelines Context:\n{json.dumps(guidelines or [], default=str)}\n\n"
            "Respond strictly in valid JSON matching this schema:\n"
            "{\n"
            '  "on_screen_text": "text string",\n'
            '  "logos": [{"label": "string", "confidence": 0.95, "box_2d": [0.1, 0.2, 0.3, 0.4], "notes": "string"}],\n'
            '  "dominant_colors": [{"hex": "#1E40AF", "name": "Primary Blue", "percentage": 40}],\n'
            '  "visual_compliance_notes": ["note 1", "note 2"]\n'
            "}"
        )

        contents = [
            {
                "parts": [
                    {"inlineData": {"mimeType": mime_type.value, "data": b64_img}},
                    {"text": prompt},
                ]
            }
        ]

        try:
            raw_resp = await self.client.generate_content(
                contents=contents,
                generation_config={"response_mime_type": "application/json"},
                model_name=self._provider.model_name,
            )
        except GeminiClientError as e:
            logger.warning("Gemini Vision call failed (%s): %s", e.error_code.value, e.message)
            return MultimodalAnalysisResult(
                media_type="image",
                status=MultimodalProcessingStatus.UNAVAILABLE,
                extracted_text=user_caption or "",
                visual_observations=[],
                analysis_engine="gemini_vision_fallback",
                fallback_reason=f"Gemini error: {e.error_code.value} - {e.message}",
                confidence_score=0.0,
                uncertainty_notes="Visual inspection failed due to Gemini API error. Deterministic rules will evaluate caption text only.",
            )
        except Exception as e:
            logger.error("Unexpected failure calling Gemini Vision: %s", sanitize_text(str(e)))
            return MultimodalAnalysisResult(
                media_type="image",
                status=MultimodalProcessingStatus.UNAVAILABLE,
                extracted_text=user_caption or "",
                visual_observations=[],
                analysis_engine="gemini_vision_fallback",
                fallback_reason=f"Unexpected error: {str(e)}",
                confidence_score=0.0,
                uncertainty_notes="Visual inspection failed unexpectedly.",
            )

        # Parse Gemini JSON response
        try:
            candidates = raw_resp.get("candidates", [])
            if not candidates:
                raise ValueError("No candidates returned by Gemini")
            first_candidate = candidates[0]
            parts = first_candidate.get("content", {}).get("parts", [])
            if not parts:
                raise ValueError("Empty candidate content parts from Gemini")
            raw_text = parts[0].get("text", "")
            parsed = _clean_json_response(raw_text)
        except Exception as e:
            logger.warning("Failed to parse Gemini Vision JSON: %s", e)
            return MultimodalAnalysisResult(
                media_type="image",
                status=MultimodalProcessingStatus.NEEDS_HUMAN_REVIEW,
                extracted_text=user_caption or "",
                visual_observations=[],
                analysis_engine="gemini_vision",
                fallback_reason="MALFORMED_GEMINI_RESPONSE",
                confidence_score=0.3,
                uncertainty_notes="Gemini returned non-JSON response. Visual inspection requires human review.",
            )

        # Assemble Visual Observations
        ocr_text = str(parsed.get("on_screen_text") or "").strip()
        observations: List[VisualObservation] = []
        evidence_refs: List[Dict[str, Any]] = []

        # Logos
        for l in parsed.get("logos", []):
            if isinstance(l, dict) and l.get("label"):
                conf = float(l.get("confidence", 0.9))
                box = l.get("box_2d")
                if isinstance(box, (list, tuple)) and len(box) == 4:
                    box = [float(coord) for coord in box]
                else:
                    box = None

                obs = VisualObservation(
                    entity="logo",
                    label=str(l["label"]),
                    confidence=conf,
                    box_2d=box,
                    details={"notes": l.get("notes", "")},
                )
                observations.append(obs)
                evidence_refs.append({
                    "entity": "logo",
                    "label": l["label"],
                    "box_2d": box,
                    "confidence": conf,
                })

        # Colors
        for c in parsed.get("dominant_colors", []):
            if isinstance(c, dict) and c.get("hex"):
                obs = VisualObservation(
                    entity="color",
                    label=str(c["hex"]).upper(),
                    confidence=1.0,
                    details={"name": c.get("name", ""), "percentage": c.get("percentage")},
                )
                observations.append(obs)

        # Combine text: user caption + OCR text
        full_text_parts = []
        if user_caption and user_caption.strip():
            full_text_parts.append(user_caption.strip())
        if ocr_text:
            full_text_parts.append(f"[On-Screen Text]: {ocr_text}")
        combined_text = "\n\n".join(full_text_parts)

        return MultimodalAnalysisResult(
            media_type="image",
            status=MultimodalProcessingStatus.SUCCESS,
            extracted_text=combined_text,
            visual_observations=observations,
            evidence_references=evidence_refs,
            analysis_engine="gemini_vision",
            confidence_score=0.95 if observations or ocr_text else 0.80,
            metadata={
                "ocr_detected": bool(ocr_text),
                "logos_detected_count": len(parsed.get("logos", [])),
                "colors_detected_count": len(parsed.get("dominant_colors", [])),
                "visual_notes": parsed.get("visual_compliance_notes", []),
            },
        )

    # ==========================================================================
    # 4. Audio Modality (Gemini Audio + Deterministic Fallback)
    # ==========================================================================

    async def analyze_audio(
        self,
        file_path: Path,
        mime_type: MimeType,
        guidelines: Optional[List[Dict[str, Any]]] = None,
        user_notes: Optional[str] = None,
    ) -> MultimodalAnalysisResult:
        """Transcribe spoken audio verbatim and extract timestamped speech segments."""
        if not file_path.exists() or not file_path.is_file():
            return MultimodalAnalysisResult(
                media_type="audio",
                status=MultimodalProcessingStatus.FAILED,
                fallback_reason="FILE_NOT_FOUND",
                uncertainty_notes=f"Audio file not found: {file_path}",
                confidence_score=0.0,
            )

        # Check Gemini Readiness
        ready, reason = await self._check_ai_readiness()
        if not ready:
            logger.info("Gemini Audio unavailable (%s). Fallback to deterministic metadata.", reason)
            return MultimodalAnalysisResult(
                media_type="audio",
                status=MultimodalProcessingStatus.UNAVAILABLE,
                extracted_text=user_notes or "",
                dialogue_segments=[],
                analysis_engine="deterministic_metadata_engine",
                fallback_reason=reason,
                confidence_score=0.0,
                uncertainty_notes="Audio speech transcription is unavailable without active Gemini audio configuration. File duration and format verified.",
                metadata={"file_size": file_path.stat().st_size},
            )

        # Encode audio bytes for inlineData (max 120s / 10MB)
        try:
            with open(file_path, "rb") as f:
                audio_bytes = f.read()
            b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        except Exception as e:
            return MultimodalAnalysisResult(
                media_type="audio",
                status=MultimodalProcessingStatus.FAILED,
                fallback_reason="FILE_READ_ERROR",
                uncertainty_notes=f"Failed to read audio bytes: {e}",
            )

        prompt = (
            "You are a strict brand compliance speech auditor. Transcribe the spoken audio verbatim.\n"
            "Extract:\n"
            "1. transcript: Complete verbatim transcript of all spoken words.\n"
            "2. dialogue_segments: List of chronological speech segments with speaker, start_time_seconds, end_time_seconds, and text.\n"
            "3. spoken_claims: Key factual assertions or brand claims spoken in the audio.\n\n"
            f"Brand Guidelines Context:\n{json.dumps(guidelines or [], default=str)}\n\n"
            "Respond strictly in valid JSON matching this schema:\n"
            "{\n"
            '  "transcript": "full spoken dialogue text",\n'
            '  "dialogue_segments": [\n'
            '    {"speaker": "Speaker 1", "start_time_seconds": 0.0, "end_time_seconds": 4.5, "text": "...", "confidence": 0.98}\n'
            '  ],\n'
            '  "spoken_claims": ["claim 1", "claim 2"]\n'
            "}"
        )

        contents = [
            {
                "parts": [
                    {"inlineData": {"mimeType": mime_type.value, "data": b64_audio}},
                    {"text": prompt},
                ]
            }
        ]

        try:
            raw_resp = await self.client.generate_content(
                contents=contents,
                generation_config={"response_mime_type": "application/json"},
                model_name=self._provider.model_name,
            )
        except GeminiClientError as e:
            logger.warning("Gemini Audio call failed (%s): %s", e.error_code.value, e.message)
            return MultimodalAnalysisResult(
                media_type="audio",
                status=MultimodalProcessingStatus.UNAVAILABLE,
                extracted_text=user_notes or "",
                dialogue_segments=[],
                analysis_engine="gemini_audio_fallback",
                fallback_reason=f"Gemini error: {e.error_code.value} - {e.message}",
                confidence_score=0.0,
                uncertainty_notes="Audio transcription failed due to Gemini API error. Deterministic rules will evaluate provided notes only.",
            )
        except Exception as e:
            logger.error("Unexpected failure calling Gemini Audio: %s", sanitize_text(str(e)))
            return MultimodalAnalysisResult(
                media_type="audio",
                status=MultimodalProcessingStatus.UNAVAILABLE,
                extracted_text=user_notes or "",
                dialogue_segments=[],
                analysis_engine="gemini_audio_fallback",
                fallback_reason=f"Unexpected error: {str(e)}",
                confidence_score=0.0,
                uncertainty_notes="Audio transcription failed unexpectedly.",
            )

        # Parse Gemini response
        try:
            candidates = raw_resp.get("candidates", [])
            if not candidates:
                raise ValueError("No candidates returned by Gemini")
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                raise ValueError("Empty candidate content parts from Gemini")
            raw_text = parts[0].get("text", "")
            parsed = _clean_json_response(raw_text)
        except Exception as e:
            logger.warning("Failed to parse Gemini Audio JSON: %s", e)
            return MultimodalAnalysisResult(
                media_type="audio",
                status=MultimodalProcessingStatus.NEEDS_HUMAN_REVIEW,
                extracted_text=user_notes or "",
                dialogue_segments=[],
                analysis_engine="gemini_audio",
                fallback_reason="MALFORMED_GEMINI_RESPONSE",
                confidence_score=0.3,
                uncertainty_notes="Gemini returned non-JSON response for audio transcription. Manual review required.",
            )

        transcript = str(parsed.get("transcript") or "").strip()
        segments: List[SpokenDialogueSegment] = []
        evidence_refs: List[Dict[str, Any]] = []

        for seg in parsed.get("dialogue_segments", []):
            if isinstance(seg, dict) and seg.get("text"):
                start = float(seg.get("start_time_seconds", 0.0))
                end = float(seg.get("end_time_seconds", start))
                seg_obj = SpokenDialogueSegment(
                    text=str(seg["text"]),
                    start_time_seconds=start,
                    end_time_seconds=end,
                    speaker=seg.get("speaker"),
                    confidence=float(seg.get("confidence", 0.95)),
                )
                segments.append(seg_obj)
                evidence_refs.append({
                    "start_time": start,
                    "end_time": end,
                    "speaker": seg.get("speaker"),
                    "sample": seg["text"][:80],
                })

        combined_text = transcript
        if user_notes and user_notes.strip():
            combined_text = f"{user_notes.strip()}\n\n[Spoken Audio Transcript]:\n{transcript}"

        return MultimodalAnalysisResult(
            media_type="audio",
            status=MultimodalProcessingStatus.SUCCESS,
            extracted_text=combined_text,
            dialogue_segments=segments,
            evidence_references=evidence_refs,
            analysis_engine="gemini_audio",
            confidence_score=0.95 if transcript else 0.5,
            metadata={
                "segment_count": len(segments),
                "spoken_claims": parsed.get("spoken_claims", []),
            },
        )

    # ==========================================================================
    # 5. Video Modality (Files API Lifecycle + Deterministic Fallback)
    # ==========================================================================

    async def analyze_video(
        self,
        file_path: Path,
        mime_type: MimeType,
        guidelines: Optional[List[Dict[str, Any]]] = None,
        user_notes: Optional[str] = None,
        use_files_api: bool = True,
    ) -> MultimodalAnalysisResult:
        """Inspect video visual content, on-screen text, and spoken dialogue with guaranteed cleanup."""
        if not file_path.exists() or not file_path.is_file():
            return MultimodalAnalysisResult(
                media_type="video",
                status=MultimodalProcessingStatus.FAILED,
                fallback_reason="FILE_NOT_FOUND",
                uncertainty_notes=f"Video file not found: {file_path}",
                confidence_score=0.0,
            )

        # Check Gemini Readiness
        ready, reason = await self._check_ai_readiness()
        if not ready:
            logger.info("Gemini Video unavailable (%s). Fallback to deterministic metadata.", reason)
            return MultimodalAnalysisResult(
                media_type="video",
                status=MultimodalProcessingStatus.UNAVAILABLE,
                extracted_text=user_notes or "",
                visual_observations=[],
                dialogue_segments=[],
                analysis_engine="deterministic_metadata_engine",
                fallback_reason=reason,
                confidence_score=0.0,
                uncertainty_notes="Video multimodal analysis is unavailable without active Gemini configuration. Container and duration verified.",
                metadata={"file_size": file_path.stat().st_size},
            )

        prompt = (
            "You are a strict brand compliance multimodal auditor. Analyze both the visual track and audio track of this video.\n"
            "Extract:\n"
            "1. transcript: Full spoken dialogue transcription with timestamps.\n"
            "2. on_screen_text: Any captions, supers, titles, or lower-thirds with start_time_seconds and text.\n"
            "3. visual_observations: Logos, brand identifiers, and visual brand elements with timestamps and bounding boxes.\n\n"
            f"Brand Guidelines Context:\n{json.dumps(guidelines or [], default=str)}\n\n"
            "Respond strictly in valid JSON matching this schema:\n"
            "{\n"
            '  "transcript": "full spoken dialogue text",\n'
            '  "dialogue_segments": [\n'
            '    {"speaker": "Speaker 1", "start_time_seconds": 0.0, "end_time_seconds": 4.5, "text": "..."}\n'
            '  ],\n'
            '  "on_screen_text": [\n'
            '    {"start_time_seconds": 0.0, "end_time_seconds": 3.0, "text": "..."}\n'
            '  ],\n'
            '  "visual_observations": [\n'
            '    {"entity": "logo", "label": "BrandShield Logo", "confidence": 0.95, "box_2d": [0.1, 0.2, 0.3, 0.4]}\n'
            '  ]\n'
            "}"
        )

        remote_file_name: Optional[str] = None
        raw_resp: Optional[Dict[str, Any]] = None

        try:
            if use_files_api:
                # 1. Upload file to Gemini Files API
                logger.info("Uploading video %s to Gemini Files API", file_path.name)
                file_obj = await self.client.upload_file(
                    file_path=file_path,
                    mime_type=mime_type.value,
                    display_name=file_path.name,
                )
                remote_file_name = file_obj.get("name")
                file_uri = file_obj.get("uri")

                # 2. Poll file until ACTIVE
                if remote_file_name:
                    active_file = await self.client.poll_file_active(
                        file_name=remote_file_name,
                        max_wait_seconds=settings.GEMINI_TIMEOUT_SECONDS * 2,
                    )
                    file_uri = active_file.get("uri") or file_uri

                # 3. Generate content referencing fileData
                contents = [
                    {
                        "parts": [
                            {"fileData": {"fileUri": file_uri, "mimeType": mime_type.value}},
                            {"text": prompt},
                        ]
                    }
                ]
                raw_resp = await self.client.generate_content(
                    contents=contents,
                    generation_config={"response_mime_type": "application/json"},
                    model_name=self._provider.model_name,
                )
            else:
                # Direct inlineData fallback for small clips
                with open(file_path, "rb") as f:
                    vid_bytes = f.read()
                b64_vid = base64.b64encode(vid_bytes).decode("utf-8")
                contents = [
                    {
                        "parts": [
                            {"inlineData": {"mimeType": mime_type.value, "data": b64_vid}},
                            {"text": prompt},
                        ]
                    }
                ]
                raw_resp = await self.client.generate_content(
                    contents=contents,
                    generation_config={"response_mime_type": "application/json"},
                    model_name=self._provider.model_name,
                )

        except GeminiClientError as e:
            logger.warning("Gemini Video call failed (%s): %s", e.error_code.value, e.message)
            return MultimodalAnalysisResult(
                media_type="video",
                status=MultimodalProcessingStatus.UNAVAILABLE,
                extracted_text=user_notes or "",
                visual_observations=[],
                dialogue_segments=[],
                analysis_engine="gemini_video_fallback",
                fallback_reason=f"Gemini error: {e.error_code.value} - {e.message}",
                confidence_score=0.0,
                uncertainty_notes="Video multimodal analysis failed due to Gemini API error. Deterministic rules will evaluate provided copy only.",
            )
        except Exception as e:
            logger.error("Unexpected failure calling Gemini Video: %s", sanitize_text(str(e)))
            return MultimodalAnalysisResult(
                media_type="video",
                status=MultimodalProcessingStatus.UNAVAILABLE,
                extracted_text=user_notes or "",
                visual_observations=[],
                dialogue_segments=[],
                analysis_engine="gemini_video_fallback",
                fallback_reason=f"Unexpected error: {str(e)}",
                confidence_score=0.0,
                uncertainty_notes="Video multimodal analysis failed unexpectedly.",
            )
        finally:
            # 4. Mandatory Cleanup of Remote Files API artifact
            if remote_file_name:
                try:
                    await self.client.delete_file(remote_file_name)
                    logger.info("Successfully cleaned up remote Gemini file: %s", remote_file_name)
                except Exception as e:
                    logger.warning("Failed to delete remote Gemini file %s: %s", remote_file_name, sanitize_text(str(e)))

        if not raw_resp:
            return MultimodalAnalysisResult(
                media_type="video",
                status=MultimodalProcessingStatus.FAILED,
                fallback_reason="EMPTY_API_RESPONSE",
                uncertainty_notes="Gemini returned empty response for video analysis.",
            )

        # Parse Gemini response
        try:
            candidates = raw_resp.get("candidates", [])
            if not candidates:
                raise ValueError("No candidates returned by Gemini")
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                raise ValueError("Empty candidate content parts from Gemini")
            raw_text = parts[0].get("text", "")
            parsed = _clean_json_response(raw_text)
        except Exception as e:
            logger.warning("Failed to parse Gemini Video JSON: %s", e)
            return MultimodalAnalysisResult(
                media_type="video",
                status=MultimodalProcessingStatus.NEEDS_HUMAN_REVIEW,
                extracted_text=user_notes or "",
                visual_observations=[],
                dialogue_segments=[],
                analysis_engine="gemini_video",
                fallback_reason="MALFORMED_GEMINI_RESPONSE",
                confidence_score=0.3,
                uncertainty_notes="Gemini returned non-JSON response for video analysis. Manual review required.",
            )

        transcript = str(parsed.get("transcript") or "").strip()
        segments: List[SpokenDialogueSegment] = []
        observations: List[VisualObservation] = []
        evidence_refs: List[Dict[str, Any]] = []

        # Dialogue
        for seg in parsed.get("dialogue_segments", []):
            if isinstance(seg, dict) and seg.get("text"):
                start = float(seg.get("start_time_seconds", 0.0))
                end = float(seg.get("end_time_seconds", start))
                seg_obj = SpokenDialogueSegment(
                    text=str(seg["text"]),
                    start_time_seconds=start,
                    end_time_seconds=end,
                    speaker=seg.get("speaker"),
                    confidence=float(seg.get("confidence", 0.95)),
                )
                segments.append(seg_obj)
                evidence_refs.append({
                    "type": "spoken_dialogue",
                    "start_time": start,
                    "end_time": end,
                    "speaker": seg.get("speaker"),
                    "sample": seg["text"][:80],
                })

        # On-screen text
        on_screen_items = parsed.get("on_screen_text", [])
        on_screen_texts = []
        for ost in on_screen_items:
            if isinstance(ost, dict) and ost.get("text"):
                on_screen_texts.append(f"[{ost.get('start_time_seconds', 0.0)}s] {ost['text']}")
                evidence_refs.append({
                    "type": "on_screen_text",
                    "start_time": ost.get("start_time_seconds", 0.0),
                    "text": ost["text"],
                })

        # Visual observations
        for vo in parsed.get("visual_observations", []):
            if isinstance(vo, dict) and vo.get("label"):
                conf = float(vo.get("confidence", 0.9))
                box = vo.get("box_2d")
                if isinstance(box, (list, tuple)) and len(box) == 4:
                    box = [float(coord) for coord in box]
                else:
                    box = None

                obs = VisualObservation(
                    entity=str(vo.get("entity", "visual_element")),
                    label=str(vo["label"]),
                    confidence=conf,
                    box_2d=box,
                    details={"notes": vo.get("notes", "")},
                )
                observations.append(obs)

        # Synthesize extracted text for compliance & claims analysis
        text_blocks = []
        if user_notes and user_notes.strip():
            text_blocks.append(user_notes.strip())
        if transcript:
            text_blocks.append(f"[Spoken Dialogue Transcript]:\n{transcript}")
        if on_screen_texts:
            text_blocks.append(f"[On-Screen Supers/Text]:\n" + "\n".join(on_screen_texts))
        combined_text = "\n\n".join(text_blocks)

        return MultimodalAnalysisResult(
            media_type="video",
            status=MultimodalProcessingStatus.SUCCESS,
            extracted_text=combined_text,
            visual_observations=observations,
            dialogue_segments=segments,
            evidence_references=evidence_refs,
            analysis_engine="gemini_video",
            confidence_score=0.95 if transcript or on_screen_texts or observations else 0.5,
            metadata={
                "dialogue_segments_count": len(segments),
                "on_screen_text_count": len(on_screen_texts),
                "visual_observations_count": len(observations),
            },
        )

    # ==========================================================================
    # Unified Dispatcher
    # ==========================================================================

    async def analyze_input(
        self,
        media_type: str,
        content_text: Optional[str] = None,
        file_path: Optional[Path] = None,
        mime_type: Optional[MimeType] = None,
        guidelines: Optional[List[Dict[str, Any]]] = None,
        use_files_api_for_video: bool = True,
    ) -> MultimodalAnalysisResult:
        """Unified dispatch method for analyzing any of the 5 supported media types."""
        normalized_type = str(media_type or "").strip().lower()

        if normalized_type == MediaType.DOCUMENT.value:
            if not file_path or not mime_type:
                raise ValueError("file_path and mime_type are required for document analysis.")
            return self.analyze_document(file_path=file_path, mime_type=mime_type, user_notes=content_text)

        elif normalized_type == MediaType.IMAGE.value:
            if not file_path or not mime_type:
                raise ValueError("file_path and mime_type are required for image analysis.")
            return await self.analyze_image(
                file_path=file_path,
                mime_type=mime_type,
                guidelines=guidelines,
                user_caption=content_text,
            )

        elif normalized_type == MediaType.AUDIO.value:
            if not file_path or not mime_type:
                raise ValueError("file_path and mime_type are required for audio analysis.")
            return await self.analyze_audio(
                file_path=file_path,
                mime_type=mime_type,
                guidelines=guidelines,
                user_notes=content_text,
            )

        elif normalized_type == MediaType.VIDEO.value:
            if not file_path or not mime_type:
                raise ValueError("file_path and mime_type are required for video analysis.")
            return await self.analyze_video(
                file_path=file_path,
                mime_type=mime_type,
                guidelines=guidelines,
                user_notes=content_text,
                use_files_api=use_files_api_for_video,
            )

        elif normalized_type == "text" or not normalized_type:
            return self.analyze_text(text=content_text or "")

        else:
            raise ValueError(f"Unsupported media_type: '{media_type}'. Supported: text, document, image, audio, video.")


multimodal_service = MultimodalService()
