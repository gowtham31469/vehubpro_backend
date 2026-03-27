"""
Upload media files to configured backend (LOCAL or S3).

Generic entrypoint: :func:`upload_branding_asset` — tenant branding–oriented naming.
Lower-level helpers can be reused by passing the same relative key layout.
"""

from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from core.storage.exceptions import StorageConfigError
from core.storage.local_backend import save_upload_local
from core.storage.s3_backend import upload_to_s3
from core.storage.validation import validate_branding_upload

logger = logging.getLogger(__name__)


def build_tenant_branding_key(tenant_id: str, asset_kind: str, ext: str) -> str:
    """Relative path / S3 key: tenant_branding/<tenant_id>/<kind>/<uuid>.<ext>"""
    safe_kind = asset_kind.replace("\\", "").replace("/", "")
    if not safe_kind or ".." in asset_kind:
        raise StorageConfigError("Invalid asset kind for storage path.")
    tid = str(tenant_id).replace("/", "")
    return f"tenant_branding/{tid}/{safe_kind}/{uuid.uuid4()}{ext}"


def upload_branding_asset(
    uploaded_file: UploadedFile,
    *,
    tenant_id: str,
    asset_kind: str,
) -> str:
    """
    Validate and store a branding file. Returns value to persist (relative path or S3 key).

    ``asset_kind`` should be one of: logo, dark_logo, favicon.
    """
    ext = validate_branding_upload(uploaded_file)
    relative_key = build_tenant_branding_key(str(tenant_id), asset_kind, ext)
    backend = getattr(settings, "STORAGE_TYPE", "LOCAL").upper()

    if backend == "LOCAL":
        return save_upload_local(uploaded_file, relative_key)
    if backend == "S3":
        content_type = (uploaded_file.content_type or "").split(";")[0].strip() or None
        return upload_to_s3(uploaded_file, relative_key, content_type)

    logger.error("Unsupported STORAGE_TYPE: %s", backend)
    raise StorageConfigError(f"Unsupported STORAGE_TYPE: {backend}")


def upload_media_file(
    uploaded_file: UploadedFile,
    *,
    relative_key: str,
    content_type: str | None = None,
) -> str:
    """
    Persist a file at ``relative_key`` without branding-specific validation.

    Use for other modules after applying your own validation and key layout.
    """
    backend = getattr(settings, "STORAGE_TYPE", "LOCAL").upper()
    if backend == "LOCAL":
        return save_upload_local(uploaded_file, relative_key)
    if backend == "S3":
        ct = content_type
        if ct is None:
            ct = (uploaded_file.content_type or "").split(";")[0].strip() or None
        return upload_to_s3(uploaded_file, relative_key, ct)
    raise StorageConfigError(f"Unsupported STORAGE_TYPE: {backend}")
