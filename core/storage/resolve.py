"""Build public or pre-signed URLs from stored references."""

from __future__ import annotations

import logging

from django.conf import settings

from core.storage.exceptions import StorageConfigError
from core.storage.local_backend import delete_local_if_exists
from core.storage.s3_backend import delete_s3_object_if_exists, presigned_get_url

logger = logging.getLogger(__name__)


def resolve_media_url(stored_reference: str | None) -> str | None:
    """
    Turn a DB-stored path (LOCAL) or object key (S3) into a usable URL.

    LOCAL: BASE_URL + MEDIA_URL + stored path.
    S3: time-limited pre-signed GET URL.
    """
    if not stored_reference:
        return None

    backend = getattr(settings, "STORAGE_TYPE", "LOCAL").upper()
    if backend == "LOCAL":
        base = getattr(settings, "BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        media_url = getattr(settings, "MEDIA_URL", "/media/")
        if not media_url.startswith("/"):
            media_url = "/" + media_url
        media_url = media_url.rstrip("/")
        ref = stored_reference.lstrip("/")
        return f"{base}{media_url}/{ref}"
    if backend == "S3":
        return presigned_get_url(stored_reference)

    logger.error("Unsupported STORAGE_TYPE for URL resolution: %s", backend)
    raise StorageConfigError(f"Unsupported STORAGE_TYPE: {backend}")


def delete_stored_media(stored_reference: str | None) -> None:
    """Remove a previously stored object when replacing or removing branding."""
    if not stored_reference:
        return
    backend = getattr(settings, "STORAGE_TYPE", "LOCAL").upper()
    if backend == "LOCAL":
        delete_local_if_exists(stored_reference)
    elif backend == "S3":
        delete_s3_object_if_exists(stored_reference)
