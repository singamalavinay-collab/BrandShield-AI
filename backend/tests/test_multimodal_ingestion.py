"""Unit test suite for Phase 0B Multimodal File Ingestion, Validation & Document Extraction.

Validates:
- Strict 10MB ceiling and 0-byte rejection.
- Magic-byte content inspection (JPEG, PNG, WebP, PDF, DOCX, MP3, WAV, MP4, WebM).
- Extension-spoofing defense (e.g. bash scripts renamed as .png).
- Image dimension enforcement (<=4096px).
- PDF page limit enforcement (<=20 pages).
- DOCX paragraph count limit enforcement (<=500 paragraphs).
- Audio and video duration boundaries (<=120s audio, <=60s video).
- DOCX decompression bomb / expansion ceiling protection (>25MB rejected).
- Robust document text extraction for PDF and DOCX.
- Scanned / image-only PDF detection with OCR flag requirement.
- Safe handling of encrypted / password-protected documents.
- Ephemeral temporary file lifecycle: guaranteed unlinking on success, exceptions, and task cancellation.
"""

import asyncio
import io
from pathlib import Path
import struct
import tempfile
from typing import AsyncIterator, List
import wave
import zipfile

import pytest
import pypdf
from pypdf.generic import (
    DictionaryObject,
    NameObject,
    DecodedStreamObject,
)

from app.core.config import settings
from app.engine.multimodal.validator import (
    MediaType,
    MimeType,
    ValidationResult,
    UploadValidationError,
    detect_mime_type_from_bytes,
    get_image_dimensions,
    get_audio_duration,
    get_video_duration,
    validate_file_content,
)
from app.engine.multimodal.extractor import (
    DocumentExtractionResult,
    DocumentExtractionError,
    MalformedDocumentError,
    extract_document_text,
)
from app.engine.multimodal.temp_manager import (
    get_upload_temp_dir,
    safe_cleanup_file,
    managed_temp_file,
    write_stream_to_temp,
)


# ==============================================================================
# Binary Asset Generators (Synthetic In-Memory Payloads)
# ==============================================================================

def make_png_bytes(width: int = 800, height: int = 600) -> bytes:
    """Generate a minimal valid PNG header with specified dimensions."""
    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    ihdr_crc = b"\x00\x00\x00\x00"
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc
    return header + ihdr_chunk


def make_jpeg_bytes(width: int = 800, height: int = 600) -> bytes:
    """Generate a minimal valid JPEG header with specified dimensions."""
    soi = b"\xff\xd8"
    # SOF0 marker (baseline DCT) with precision, height, width, 3 components
    sof0_body = b"\x08" + struct.pack(">HH", height, width) + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    sof0 = b"\xff\xc0" + struct.pack(">H", 2 + len(sof0_body)) + sof0_body
    eoi = b"\xff\xd9"
    return soi + sof0 + eoi


def make_webp_bytes(width: int = 640, height: int = 480) -> bytes:
    """Generate a minimal valid WebP lossy keyframe header."""
    riff = b"RIFF"
    riff_size = struct.pack("<I", 30)
    webp_magic = b"WEBPVP8 "
    chunk_size = struct.pack("<I", 14)
    # VP8 keyframe: 3-byte frame tag, 3-byte start code (0x9D 0x01 0x2A), 2-byte width, 2-byte height
    vp8_data = b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", width, height)
    return riff + riff_size + webp_magic + chunk_size + vp8_data


def make_mp4_bytes(duration_sec: float = 10.0, timescale: int = 1000) -> bytes:
    """Generate a minimal MP4 container with ftyp, moov, and mvhd atoms."""
    ftyp_data = b"isom\x00\x00\x02\x00mp41"
    ftyp = struct.pack(">I", 8 + len(ftyp_data)) + b"ftyp" + ftyp_data

    duration_units = int(duration_sec * timescale)
    # mvhd version 0: 4 bytes version+flags, 4 create, 4 mod, 4 timescale, 4 duration, 80 bytes padding
    mvhd_body = b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, timescale, duration_units) + (b"\x00" * 80)
    mvhd_atom = struct.pack(">I", 8 + len(mvhd_body)) + b"mvhd" + mvhd_body
    moov_atom = struct.pack(">I", 8 + len(mvhd_atom)) + b"moov" + mvhd_atom
    return ftyp + moov_atom


def create_wav_file(path: Path, duration_sec: float = 2.0, sample_rate: int = 8000) -> None:
    """Write a minimal valid WAV audio file."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        total_frames = int(sample_rate * duration_sec)
        w.writeframes(b"\x00\x00" * total_frames)


def create_pdf_with_text(path: Path, pages_text: List[str]) -> None:
    """Generate a valid multi-page PDF with extractable text."""
    writer = pypdf.PdfWriter()
    for text in pages_text:
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

    with open(path, "wb") as f:
        writer.write(f)


def create_blank_pdf(path: Path, page_count: int = 1) -> None:
    """Generate a scanned/blank PDF containing only empty pages."""
    writer = pypdf.PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=300, height=300)
    with open(path, "wb") as f:
        writer.write(f)


def create_encrypted_pdf(path: Path, password: str = "secret") -> None:
    """Generate an encrypted password-protected PDF."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(password)
    with open(path, "wb") as f:
        writer.write(f)


def create_docx_file(path: Path, paragraphs: List[str]) -> None:
    """Generate a valid DOCX file with specified paragraphs."""
    p_xml = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{p_xml}</w:body>
</w:document>"""

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        zf.writestr("word/document.xml", doc_xml)


# ==============================================================================
# 1. Magic-Byte Detection & Sniffing Tests
# ==============================================================================

def test_detect_mime_type_from_bytes_all_supported_types():
    assert detect_mime_type_from_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01") == MimeType.JPEG
    assert detect_mime_type_from_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR") == MimeType.PNG
    assert detect_mime_type_from_bytes(b"RIFF\x20\x00\x00\x00WEBPVP8 ") == MimeType.WEBP
    assert detect_mime_type_from_bytes(b"%PDF-1.7\r\n%\xb5\xed\xae\xfb") == MimeType.PDF
    assert detect_mime_type_from_bytes(b"PK\x03\x04\x14\x00\x06\x00\x08\x00") == MimeType.DOCX
    assert detect_mime_type_from_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ") == MimeType.WAV
    assert detect_mime_type_from_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x20") == MimeType.MP3
    assert detect_mime_type_from_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00") == MimeType.MP4
    assert detect_mime_type_from_bytes(b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01\x42\xf7\x81") == MimeType.WEBM


def test_detect_mime_type_from_bytes_unsupported_and_spoofs():
    # Plain text / script
    assert detect_mime_type_from_bytes(b"#!/bin/bash\necho 'hacked'") is None
    assert detect_mime_type_from_bytes(b"Plain text note without binary header") is None
    # Truncated header (< 12 bytes)
    assert detect_mime_type_from_bytes(b"\xff\xd8\xff") is None
    # ELF binary
    assert detect_mime_type_from_bytes(b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00") is None


# ==============================================================================
# 2. File Size & Boundary Validations
# ==============================================================================

def test_validate_file_content_file_not_found(tmp_path: Path):
    missing_path = tmp_path / "non_existent.png"
    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(missing_path, "non_existent.png")
    assert exc.value.error_code == "FILE_NOT_FOUND"


def test_validate_file_content_empty_file(tmp_path: Path):
    empty_file = tmp_path / "zero.png"
    empty_file.write_bytes(b"")
    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(empty_file, "zero.png")
    assert exc.value.error_code == "EMPTY_FILE"


def test_validate_file_content_exceeds_10mb(tmp_path: Path, monkeypatch):
    # Temporarily set MAX_UPLOAD_SIZE_BYTES to 1024 bytes for lightweight test
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_BYTES", 1024)
    oversized = tmp_path / "huge.pdf"
    oversized.write_bytes(b"%PDF-" + b"0" * 2000)

    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(oversized, "huge.pdf")
    assert exc.value.error_code == "FILE_TOO_LARGE"


def test_validate_file_content_extension_spoofing(tmp_path: Path):
    # Extension says .png but content is plain shell script
    spoofed = tmp_path / "logo.png"
    spoofed.write_bytes(b"rm -rf / # not a real png image")

    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(spoofed, "logo.png")
    assert exc.value.error_code == "UNSUPPORTED_MIME_TYPE"


# ==============================================================================
# 3. Image Dimension Limits
# ==============================================================================

def test_validate_file_content_valid_png(tmp_path: Path):
    png_path = tmp_path / "brand_logo.png"
    png_path.write_bytes(make_png_bytes(width=1200, height=800))

    result = validate_file_content(png_path, "brand_logo.png")
    assert result.media_type == MediaType.IMAGE
    assert result.mime_type == MimeType.PNG
    assert result.dimensions == (1200, 800)
    assert len(result.file_sha256) == 64


def test_validate_file_content_oversized_png_dimension(tmp_path: Path):
    png_path = tmp_path / "giant_banner.png"
    png_path.write_bytes(make_png_bytes(width=5000, height=2000))

    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(png_path, "giant_banner.png")
    assert exc.value.error_code == "IMAGE_DIMENSIONS_EXCEEDED"
    assert "5000x2000" in exc.value.message


def test_validate_file_content_valid_jpeg(tmp_path: Path):
    jpg_path = tmp_path / "campaign.jpg"
    jpg_path.write_bytes(make_jpeg_bytes(width=1920, height=1080))

    result = validate_file_content(jpg_path, "campaign.jpg")
    assert result.media_type == MediaType.IMAGE
    assert result.mime_type == MimeType.JPEG
    assert result.dimensions == (1920, 1080)


def test_validate_file_content_oversized_jpeg_dimension(tmp_path: Path):
    jpg_path = tmp_path / "giant_poster.jpg"
    jpg_path.write_bytes(make_jpeg_bytes(width=1000, height=6000))

    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(jpg_path, "giant_poster.jpg")
    assert exc.value.error_code == "IMAGE_DIMENSIONS_EXCEEDED"


def test_validate_file_content_valid_webp(tmp_path: Path):
    webp_path = tmp_path / "banner.webp"
    webp_path.write_bytes(make_webp_bytes(width=640, height=480))

    result = validate_file_content(webp_path, "banner.webp")
    assert result.media_type == MediaType.IMAGE
    assert result.mime_type == MimeType.WEBP
    assert result.dimensions == (640, 480)


# ==============================================================================
# 4. Audio Duration Limits
# ==============================================================================

def test_validate_file_content_valid_wav(tmp_path: Path):
    wav_path = tmp_path / "jingle.wav"
    create_wav_file(wav_path, duration_sec=5.0)

    result = validate_file_content(wav_path, "jingle.wav")
    assert result.media_type == MediaType.AUDIO
    assert result.mime_type == MimeType.WAV
    assert result.duration_seconds is not None
    assert abs(result.duration_seconds - 5.0) < 0.1


def test_validate_file_content_oversized_wav_duration(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_AUDIO_DURATION_SECONDS", 10.0)
    wav_path = tmp_path / "long_podcast.wav"
    create_wav_file(wav_path, duration_sec=15.0)

    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(wav_path, "long_podcast.wav")
    assert exc.value.error_code == "AUDIO_DURATION_EXCEEDED"


# ==============================================================================
# 5. Video Duration Limits
# ==============================================================================

def test_validate_file_content_valid_mp4(tmp_path: Path):
    mp4_path = tmp_path / "ad_spot.mp4"
    mp4_path.write_bytes(make_mp4_bytes(duration_sec=15.0))

    result = validate_file_content(mp4_path, "ad_spot.mp4")
    assert result.media_type == MediaType.VIDEO
    assert result.mime_type == MimeType.MP4
    assert result.duration_seconds == 15.0


def test_validate_file_content_oversized_mp4_duration(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_VIDEO_DURATION_SECONDS", 30.0)
    mp4_path = tmp_path / "movie_trailer.mp4"
    mp4_path.write_bytes(make_mp4_bytes(duration_sec=75.0))

    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(mp4_path, "movie_trailer.mp4")
    assert exc.value.error_code == "VIDEO_DURATION_EXCEEDED"


# ==============================================================================
# 6. PDF Page Limits & Document Validation
# ==============================================================================

def test_validate_file_content_valid_pdf(tmp_path: Path):
    pdf_path = tmp_path / "guidelines.pdf"
    create_pdf_with_text(pdf_path, ["Brand Identity Page 1", "Typography Page 2"])

    result = validate_file_content(pdf_path, "guidelines.pdf")
    assert result.media_type == MediaType.DOCUMENT
    assert result.mime_type == MimeType.PDF
    assert result.page_count == 2


def test_validate_file_content_oversized_pdf_pages(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_PDF_PAGES", 5)
    pdf_path = tmp_path / "giant_annual_report.pdf"
    create_blank_pdf(pdf_path, page_count=8)

    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(pdf_path, "giant_annual_report.pdf")
    assert exc.value.error_code == "PDF_PAGE_COUNT_EXCEEDED"
    assert "Found: 8" in exc.value.message


# ==============================================================================
# 7. DOCX Security, Paragraph Limits & Bomb Protection
# ==============================================================================

def test_validate_file_content_valid_docx(tmp_path: Path):
    docx_path = tmp_path / "style_guide.docx"
    create_docx_file(docx_path, ["Brand Tone of Voice", "Color Palette Requirements"])

    result = validate_file_content(docx_path, "style_guide.docx")
    assert result.media_type == MediaType.DOCUMENT
    assert result.mime_type == MimeType.DOCX
    assert result.paragraph_count == 2


def test_validate_file_content_oversized_docx_paragraphs(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_DOCX_PARAGRAPHS", 50)
    docx_path = tmp_path / "novel.docx"
    create_docx_file(docx_path, [f"Paragraph {i}" for i in range(75)])

    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(docx_path, "novel.docx")
    assert exc.value.error_code == "DOCX_PARAGRAPHS_EXCEEDED"


def test_validate_file_content_docx_zip_bomb_protection(tmp_path: Path):
    bomb_path = tmp_path / "bomb.docx"
    # Create an archive with inflated uncompressed header claim > 25MB
    with zipfile.ZipFile(bomb_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", b"x" * (26 * 1024 * 1024))

    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(bomb_path, "bomb.docx")
    assert exc.value.error_code == "ZIP_EXPANSION_LIMIT_EXCEEDED"


def test_validate_file_content_malformed_docx_missing_part(tmp_path: Path):
    corrupt_docx = tmp_path / "empty_zip.docx"
    with zipfile.ZipFile(corrupt_docx, "w") as zf:
        zf.writestr("unrelated.txt", "not a real docx")

    with pytest.raises(UploadValidationError) as exc:
        validate_file_content(corrupt_docx, "empty_zip.docx")
    assert exc.value.error_code == "MALFORMED_DOCX"


# ==============================================================================
# 8. Document Text Extraction & OCR / Encryption Detection
# ==============================================================================

def test_extract_document_text_valid_pdf(tmp_path: Path):
    pdf_path = tmp_path / "audit_rules.pdf"
    create_pdf_with_text(
        pdf_path,
        [
            "Primary Rule: Logo minimum clearance 20px.",
            "Secondary Rule: High contrast accessibility compliance.",
        ],
    )

    result = extract_document_text(pdf_path, MimeType.PDF)
    assert not result.is_scanned
    assert not result.requires_ocr
    assert not result.is_encrypted
    assert result.page_count == 2
    assert "Logo minimum clearance" in result.text
    assert "contrast accessibility" in result.text
    assert 1 in result.page_texts
    assert 2 in result.page_texts


def test_extract_document_text_scanned_pdf_detection(tmp_path: Path):
    pdf_path = tmp_path / "scanned_invoice.pdf"
    create_blank_pdf(pdf_path, page_count=2)

    result = extract_document_text(pdf_path, MimeType.PDF)
    assert result.is_scanned is True
    assert result.requires_ocr is True
    assert result.text == ""
    assert result.page_count == 2


def test_extract_document_text_encrypted_pdf(tmp_path: Path):
    pdf_path = tmp_path / "protected.pdf"
    create_encrypted_pdf(pdf_path, password="admin_secure_key")

    result = extract_document_text(pdf_path, MimeType.PDF)
    assert result.is_encrypted is True
    assert result.text == ""


def test_extract_document_text_malformed_pdf(tmp_path: Path):
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"%PDF-1.4\nTRUNCATED_GARBAGE_PAYLOAD")

    with pytest.raises(MalformedDocumentError):
        extract_document_text(corrupt_pdf, MimeType.PDF)


def test_extract_document_text_valid_docx(tmp_path: Path):
    docx_path = tmp_path / "brand_manual.docx"
    create_docx_file(
        docx_path,
        [
            "Header 1: Brand Guidelines Overview",
            "Rule 1: Always use official logo vector assets.",
            "Rule 2: Do not alter brand typography or colors.",
        ],
    )

    result = extract_document_text(docx_path, MimeType.DOCX)
    assert not result.is_scanned
    assert not result.requires_ocr
    assert not result.is_encrypted
    assert result.page_count == 1
    assert len(result.paragraphs) == 3
    assert "Header 1: Brand Guidelines Overview" in result.paragraphs[0]
    assert "Rule 2: Do not alter" in result.text


def test_extract_document_text_unsupported_type(tmp_path: Path):
    img_path = tmp_path / "image.png"
    img_path.write_bytes(make_png_bytes())

    with pytest.raises(DocumentExtractionError) as exc:
        extract_document_text(img_path, MimeType.PNG)
    assert exc.value.error_code == "UNSUPPORTED_DOCUMENT_TYPE"


# ==============================================================================
# 9. Ephemeral Temporary File Lifecycle & Stream Ingestion
# ==============================================================================

@pytest.mark.asyncio
async def test_managed_temp_file_lifecycle_normal():
    temp_target: Path
    async with managed_temp_file(suffix=".tmp") as p:
        temp_target = p
        assert p.exists()
        assert p.is_file()
        p.write_bytes(b"ephemeral upload data")
        assert p.stat().st_size > 0

    # Must be unlinked upon exit
    assert not temp_target.exists()


@pytest.mark.asyncio
async def test_managed_temp_file_lifecycle_exception():
    temp_target: Path
    try:
        async with managed_temp_file(suffix=".tmp") as p:
            temp_target = p
            assert p.exists()
            raise RuntimeError("Simulated mid-processing failure")
    except RuntimeError:
        pass

    # Must be unlinked even upon exception
    assert not temp_target.exists()


@pytest.mark.asyncio
async def test_managed_temp_file_lifecycle_cancellation():
    temp_target: Path

    async def cancelled_worker():
        nonlocal temp_target
        async with managed_temp_file(suffix=".tmp") as p:
            temp_target = p
            assert p.exists()
            # Simulate cancellation
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await cancelled_worker()

    # Must be unlinked even upon task cancellation
    assert not temp_target.exists()


@pytest.mark.asyncio
async def test_write_stream_to_temp_success():
    async def sample_stream() -> AsyncIterator[bytes]:
        yield b"Chunk 1: Brand guidelines. "
        yield b"Chunk 2: Color code #002D62. "
        yield b"Chunk 3: End of file."

    temp_path, digest, total_bytes = await write_stream_to_temp(sample_stream())
    try:
        assert temp_path.exists()
        assert total_bytes == len(b"Chunk 1: Brand guidelines. Chunk 2: Color code #002D62. Chunk 3: End of file.")
        assert len(digest) == 64
        # Verify content matches on disk
        assert temp_path.read_bytes() == b"Chunk 1: Brand guidelines. Chunk 2: Color code #002D62. Chunk 3: End of file."
    finally:
        safe_cleanup_file(temp_path)
        assert not temp_path.exists()


@pytest.mark.asyncio
async def test_write_stream_to_temp_oversized_cleanup():
    async def oversized_stream() -> AsyncIterator[bytes]:
        for _ in range(10):
            yield b"X" * 200

    # Enforce a tiny ceiling of 500 bytes
    with pytest.raises(ValueError) as exc:
        await write_stream_to_temp(oversized_stream(), max_bytes=500)

    assert "exceeds maximum ceiling of 500 bytes" in str(exc.value)


def test_safe_cleanup_file_idempotent():
    assert safe_cleanup_file(None) is False
    assert safe_cleanup_file(Path("non_existent_scratch_file.bin")) is False
