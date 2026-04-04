"""
Reusable media storage: LOCAL filesystem or S3, with URL resolution for APIs.

Tenant branding uses :func:`upload_branding_asset` and :func:`resolve_media_url`.
"""

from core.storage.exceptions import (
    StorageConfigError,
    StorageError,
    StorageUploadError,
    StorageValidationError,
)
from core.storage.resolve import delete_stored_media, resolve_media_url
from core.storage.upload import (
    build_media_image_key,
    build_tenant_branding_key,
    upload_branding_asset,
    upload_image_file,
    upload_media_file,
)

__all__ = [
    "StorageError",
    "StorageConfigError",
    "StorageValidationError",
    "StorageUploadError",
    "upload_branding_asset",
    "upload_image_file",
    "upload_media_file",
    "build_tenant_branding_key",
    "build_media_image_key",
    "resolve_media_url",
    "delete_stored_media",
]
