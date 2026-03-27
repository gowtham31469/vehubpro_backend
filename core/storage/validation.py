"""Validate uploaded files (type, size)."""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from core.storage.exceptions import StorageValidationError

logger = logging.getLogger(__name__)

# Extension -> acceptable Content-Type prefixes or exact matches
ALLOWED_BRANDING_EXTENSIONS: dict[str, tuple[str, ...]] = {
    ".png": ("image/png",),
    ".jpg": ("image/jpeg",),
    ".jpeg": ("image/jpeg",),
    ".ico": ("image/x-icon", "image/vnd.microsoft.icon", "image/ico"),
}


def normalize_extension(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def validate_branding_upload(
    uploaded_file: UploadedFile,
    *,
    max_bytes: int | None = None,
) -> str:
    """
    Ensure branding asset is allowed type and within size limit.

    Returns normalized extension including dot (e.g. ".png").
    """
    limit = max_bytes if max_bytes is not None else int(getattr(settings, "BRANDING_MAX_UPLOAD_BYTES", 2 * 1024 * 1024))
    if uploaded_file.size > limit:
        raise StorageValidationError(
            f"File too large. Maximum size is {limit // (1024 * 1024)} MB."
        )

    ext = normalize_extension(uploaded_file.name)
    if ext not in ALLOWED_BRANDING_EXTENSIONS:
        raise StorageValidationError(
            "Unsupported file type. Allowed: png, jpg, jpeg, ico."
        )

    content_type = (uploaded_file.content_type or "").lower().split(";")[0].strip()
    allowed_types = ALLOWED_BRANDING_EXTENSIONS[ext]
    if content_type and content_type not in allowed_types:
        if content_type in ("application/octet-stream",):
            pass
        else:
            logger.warning(
                "Upload content_type mismatch for %s: got %s expected one of %s",
                uploaded_file.name,
                content_type,
                allowed_types,
            )
            raise StorageValidationError(
                "File content type does not match extension for allowed branding types."
            )

    return ext
