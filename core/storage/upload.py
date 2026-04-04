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
from core.storage.validation import validate_branding_upload, validate_image_upload

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


def build_media_image_key(folder: str, record_id: str, ext: str) -> str:
    """
    Relative path / S3 key for a model image.

    Pattern: <folder>/<record_id>/<uuid><ext>
    e.g.  customers/abc-123/f47ac10b-58cc.jpg
          service_vehicles/xyz-456/3f2504e0-4f89.png
    """
    safe_folder = folder.replace("\\", "").replace("/", "").strip()
    if not safe_folder or ".." in safe_folder:
        raise StorageConfigError("Invalid folder name for image storage path.")
    rid = str(record_id).replace("/", "").replace("..", "")
    return f"{safe_folder}/{rid}/{uuid.uuid4()}{ext}"


def upload_image_file(
    uploaded_file: UploadedFile,
    *,
    folder: str,
    record_id: str,
    max_bytes: int | None = None,
) -> str:
    """
    Validate and store a general image (png, jpg, jpeg, webp).

    - ``folder``    : top-level storage folder, e.g. "customers" or "service_vehicles"
    - ``record_id`` : UUID of the owning record, used to namespace the file
    - ``max_bytes`` : override size limit (defaults to BRANDING_MAX_UPLOAD_BYTES)

    Returns the relative key / S3 key to persist in the database.
    """
    ext = validate_image_upload(uploaded_file, max_bytes=max_bytes)
    relative_key = build_media_image_key(folder, str(record_id), ext)
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
