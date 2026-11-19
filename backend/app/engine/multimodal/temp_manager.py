"""Secure temporary file lifecycle manager for multimodal uploads.

Guarantees:
- Uses /tmp/brandshield_uploads (with cross-platform fallback to system temp dir).
- Restricted filesystem permissions (mode 0700).
- Chunk-by-chunk stream ingestion with 10MB hard ceiling abort.
- Simultaneous SHA-256 cryptographic digest computation.
- Reliable cleanup via context managers, including on task cancellation and unhandled exceptions.
- Never retains raw binary uploads in database or persistent server disk.
"""

from contextlib import asynccontextmanager
import hashlib
import logging
import os
from pathlib import Path
import tempfile
from typing import AsyncGenerator, AsyncIterator, Optional, Tuple
import uuid

from app.core.config import settings

logger = logging.getLogger("brandshield.engine.multimodal.temp_manager")


def get_upload_temp_dir() -> Path:
    """Resolve and ensure the secure ephemeral upload scratch directory exists."""
    configured = Path(settings.UPLOAD_TMP_DIR)
    target_dir: Path

    # On POSIX systems where /tmp exists and is accessible
    if os.name != "nt":
        target_dir = configured
    else:
        # Cross-platform fallback on Windows
        target_dir = Path(tempfile.gettempdir()) / "brandshield_uploads"

    try:
        target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    except Exception as e:
        logger.warning("Could not set mode 0700 on %s: %s", target_dir, e)
        target_dir.mkdir(parents=True, exist_ok=True)

    return target_dir


def safe_cleanup_file(path: Optional[Path]) -> bool:
    """Safely unlink a temporary file, ignoring missing file errors."""
    if path is None:
        return False
    try:
        p = Path(path)
        if p.exists() and p.is_file():
            p.unlink()
            logger.debug("Successfully cleaned up temporary upload: %s", p.name)
            return True
    except Exception as e:
        logger.warning("Failed to clean up temporary file %s: %s", path, e)
    return False


@asynccontextmanager
async def managed_temp_file(suffix: str = "") -> AsyncGenerator[Path, None]:
    """Async context manager guaranteeing cleanup of temporary scratch file on exit.
    
    Guarantees:
    - Creates randomized unique file in the upload directory.
    - Guaranteed cleanup in finally: block even upon asyncio.CancelledError.
    """
    upload_dir = get_upload_temp_dir()
    file_id = f"bs_{uuid.uuid4().hex}{suffix}"
    temp_path = upload_dir / file_id

    # Touch file to claim inode
    temp_path.touch(mode=0o600, exist_ok=False)

    try:
        yield temp_path
    finally:
        safe_cleanup_file(temp_path)


async def write_stream_to_temp(
    stream: AsyncIterator[bytes],
    max_bytes: int = 10 * 1024 * 1024,
    suffix: str = "",
) -> Tuple[Path, str, int]:
    """Stream chunks to a secure temporary file while hashing and enforcing size ceiling.
    
    Returns:
        Tuple of (temp_file_path, sha256_hex_digest, total_bytes_written)
        
    Raises:
        ValueError if stream exceeds max_bytes.
    """
    upload_dir = get_upload_temp_dir()
    file_id = f"upload_{uuid.uuid4().hex}{suffix}"
    temp_path = upload_dir / file_id

    hasher = hashlib.sha256()
    total_written = 0

    try:
        with open(temp_path, "wb") as f:
            async for chunk in stream:
                if not chunk:
                    continue
                total_written += len(chunk)
                if total_written > max_bytes:
                    raise ValueError(
                        f"Uploaded file size ({total_written} bytes) exceeds maximum ceiling of {max_bytes} bytes (10MB)"
                    )
                hasher.update(chunk)
                f.write(chunk)

        sha256_digest = hasher.hexdigest()
        logger.info(
            "Safely ingested upload stream: %s (%d bytes, SHA-256: %s)",
            temp_path.name,
            total_written,
            sha256_digest[:12],
        )
        return temp_path, sha256_digest, total_written

    except Exception:
        # Guarantee cleanup on oversized abort or stream failure
        safe_cleanup_file(temp_path)
        raise
