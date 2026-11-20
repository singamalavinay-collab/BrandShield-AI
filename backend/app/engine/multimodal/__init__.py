"""Multimodal file ingestion, validation, and document extraction engine (Phase 0B)."""

from app.engine.multimodal.validator import (
    MediaType,
    MimeType,
    ValidationResult,
    UploadValidationError,
    validate_file_content,
)
from app.engine.multimodal.extractor import (
    DocumentExtractionResult,
    DocumentExtractionError,
    MalformedDocumentError,
    extract_document_text,
)
from app.engine.multimodal.temp_manager import (
    managed_temp_file,
    write_stream_to_temp,
    safe_cleanup_file,
    get_upload_temp_dir,
)
from app.engine.multimodal.service import (
    MultimodalAnalysisResult,
    MultimodalProcessingStatus,
    MultimodalService,
    SpokenDialogueSegment,
    VisualObservation,
    multimodal_service,
)

__all__ = [
    "MediaType",
    "MimeType",
    "ValidationResult",
    "UploadValidationError",
    "validate_file_content",
    "DocumentExtractionResult",
    "DocumentExtractionError",
    "MalformedDocumentError",
    "extract_document_text",
    "managed_temp_file",
    "write_stream_to_temp",
    "safe_cleanup_file",
    "get_upload_temp_dir",
    "MultimodalAnalysisResult",
    "MultimodalProcessingStatus",
    "MultimodalService",
    "SpokenDialogueSegment",
    "VisualObservation",
    "multimodal_service",
]
