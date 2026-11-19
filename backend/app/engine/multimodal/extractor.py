"""Secure document text extraction engine for BrandShield AI (Phase 0B).

Features:
- Pure-Python text extraction from PDF and DOCX.
- Scanned PDF detection (zero or negligible text in page streams, triggers OCR requirement).
- Encrypted/password-protected PDF safe handling without crashing.
- Malformed document exception isolation and error classification.
- Robust paragraph and page-level mapping for guideline auditing.
"""

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET
import zipfile

import pypdf
from pypdf.errors import PdfReadError

from app.engine.multimodal.validator import MimeType

logger = logging.getLogger("brandshield.engine.multimodal.extractor")


class DocumentExtractionError(Exception):
    """Raised when document extraction encounters a fatal parsing failure."""

    def __init__(self, message: str, error_code: str = "EXTRACTION_FAILED") -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code


class MalformedDocumentError(DocumentExtractionError):
    """Raised when a document is syntactically invalid or corrupted."""

    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="MALFORMED_DOCUMENT")


@dataclass
class DocumentExtractionResult:
    """Structured result of document text and metadata extraction."""

    text: str
    page_count: int
    is_scanned: bool = False
    requires_ocr: bool = False
    is_encrypted: bool = False
    character_count: int = 0
    page_texts: Dict[int, str] = field(default_factory=dict)
    paragraphs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def _extract_pdf(file_path: Path) -> DocumentExtractionResult:
    """Extract text from a PDF file with scanned and encryption detection."""
    try:
        reader = pypdf.PdfReader(str(file_path))
    except Exception as e:
        raise MalformedDocumentError(f"Failed to parse PDF structure: {e}")

    # Check for encryption
    if reader.is_encrypted:
        try:
            # Some standard PDFs indicate encryption but have empty default passwords
            decrypted = reader.decrypt("")
            if decrypted == 0:
                logger.info("PDF %s is password-protected/encrypted", file_path.name)
                return DocumentExtractionResult(
                    text="",
                    page_count=len(reader.pages) if hasattr(reader, "pages") else 0,
                    is_encrypted=True,
                    is_scanned=False,
                    requires_ocr=False,
                    metadata={"error": "Password-protected or encrypted PDF"},
                )
        except Exception as e:
            logger.info("Cannot decrypt PDF %s: %s", file_path.name, e)
            return DocumentExtractionResult(
                text="",
                page_count=0,
                is_encrypted=True,
                is_scanned=False,
                requires_ocr=False,
                metadata={"error": f"Encrypted PDF cannot be read without password: {e}"},
            )

    page_texts: Dict[int, str] = {}
    paragraphs: List[str] = []
    total_chars = 0
    page_count = len(reader.pages)

    for idx, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as e:
            logger.warning("Failed to extract text from PDF page %d: %s", idx, e)
            page_text = ""

        page_texts[idx] = page_text
        total_chars += len(page_text.strip())

        for line in page_text.splitlines():
            cleaned = line.strip()
            if cleaned:
                paragraphs.append(cleaned)

    # Scanned PDF detection: if non-whitespace character count is negligible
    # (less than 15 characters total across document), flag as scanned / requires OCR
    is_scanned = total_chars < 15
    requires_ocr = is_scanned

    full_text = "\n\n".join(
        txt.strip() for txt in page_texts.values() if txt.strip()
    )

    return DocumentExtractionResult(
        text=full_text,
        page_count=page_count,
        is_scanned=is_scanned,
        requires_ocr=requires_ocr,
        is_encrypted=False,
        character_count=len(full_text),
        page_texts=page_texts,
        paragraphs=paragraphs,
        metadata={"total_raw_characters": total_chars},
    )


def _extract_docx(file_path: Path) -> DocumentExtractionResult:
    """Extract text from a DOCX file using pure XML parsing."""
    try:
        zf = zipfile.ZipFile(str(file_path), "r")
    except Exception as e:
        raise MalformedDocumentError(f"Invalid DOCX zip archive: {e}")

    with zf:
        if "word/document.xml" not in zf.namelist():
            raise MalformedDocumentError("DOCX archive is missing word/document.xml")

        try:
            xml_bytes = zf.read("word/document.xml")
            root = ET.fromstring(xml_bytes)
        except Exception as e:
            raise MalformedDocumentError(f"Corrupt XML inside DOCX: {e}")

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: List[str] = []

    for p in root.findall(".//w:p", ns):
        text_runs = p.findall(".//w:t", ns)
        para_text = "".join(t.text for t in text_runs if t.text is not None)
        cleaned = para_text.strip()
        if cleaned:
            paragraphs.append(cleaned)

    full_text = "\n\n".join(paragraphs)

    return DocumentExtractionResult(
        text=full_text,
        page_count=1,
        is_scanned=False,
        requires_ocr=False,
        is_encrypted=False,
        character_count=len(full_text),
        page_texts={1: full_text},
        paragraphs=paragraphs,
        metadata={"total_paragraphs": len(paragraphs)},
    )


def extract_document_text(
    file_path: Path,
    mime_type: MimeType,
) -> DocumentExtractionResult:
    """Extract text from supported document types (PDF and DOCX).

    Guarantees:
    - Pure-Python text extraction with memory safety.
    - Scanned PDF detection with OCR flag.
    - Safe handling of encrypted documents without crashing.
    - Safe error boundaries for malformed or corrupted documents.
    """
    if not file_path.exists() or not file_path.is_file():
        raise DocumentExtractionError(f"File not found: {file_path}", "FILE_NOT_FOUND")

    if mime_type == MimeType.PDF:
        return _extract_pdf(file_path)
    elif mime_type == MimeType.DOCX:
        return _extract_docx(file_path)
    else:
        raise DocumentExtractionError(
            f"Unsupported document format for text extraction: {mime_type}. Only PDF and DOCX are supported.",
            "UNSUPPORTED_DOCUMENT_TYPE",
        )
