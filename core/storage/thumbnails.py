"""Generate small preview images for listing grids, alongside full-size originals."""

from __future__ import annotations

import logging
from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile

logger = logging.getLogger(__name__)

THUMBNAIL_MAX_DIMENSION = 480
THUMBNAIL_JPEG_QUALITY = 72


def generate_thumbnail(uploaded_file: UploadedFile) -> ContentFile | None:
    """
    Downscale an uploaded image to a small JPEG for use in listing grids —
    the original is left untouched for the detail page's full-size gallery.

    Returns None if Pillow can't read the file, so callers can fall back to
    the original rather than failing the whole upload over a non-essential
    thumbnail.
    """
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow is not installed — skipping thumbnail generation.")
        return None

    try:
        uploaded_file.seek(0)
        image = Image.open(uploaded_file)
        image.load()
    except Exception:
        logger.warning("Could not read image for thumbnail generation", exc_info=True)
        return None
    finally:
        # The caller still needs to upload the original after this — leave
        # the stream exactly as it found it.
        uploaded_file.seek(0)

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    image.thumbnail((THUMBNAIL_MAX_DIMENSION, THUMBNAIL_MAX_DIMENSION))

    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=THUMBNAIL_JPEG_QUALITY, optimize=True)
    return ContentFile(buffer.getvalue())
