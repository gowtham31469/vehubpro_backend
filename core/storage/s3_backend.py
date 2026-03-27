"""S3 upload and pre-signed URL generation."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

from core.storage.exceptions import StorageConfigError, StorageUploadError

logger = logging.getLogger(__name__)


def _client():
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - dependency guard
        raise StorageConfigError("boto3 is required for S3 storage.") from exc

    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or ""
    if not bucket:
        raise StorageConfigError("AWS_STORAGE_BUCKET_NAME is not configured.")

    region = getattr(settings, "AWS_REGION", "us-east-1")
    kwargs: dict[str, Any] = {"region_name": region}
    key = getattr(settings, "AWS_ACCESS_KEY_ID", "") or ""
    secret = getattr(settings, "AWS_SECRET_ACCESS_KEY", "") or ""
    if key:
        kwargs["aws_access_key_id"] = key
    if secret:
        kwargs["aws_secret_access_key"] = secret

    return boto3.client("s3", **kwargs)


def upload_to_s3(uploaded_file, object_key: str, content_type: str | None) -> str:
    """Stream upload to S3. Returns object_key."""
    client = _client()
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    extra: dict[str, Any] = {}
    if content_type:
        extra["ContentType"] = content_type

    try:
        uploaded_file.seek(0)
        client.upload_fileobj(
            uploaded_file,
            bucket,
            object_key,
            ExtraArgs=extra if extra else None,
        )
    except Exception as exc:
        logger.exception("S3 upload failed for key %s", object_key)
        raise StorageUploadError("Could not upload file to S3.") from exc

    return object_key


def presigned_get_url(object_key: str, expires_in: int | None = None) -> str:
    client = _client()
    bucket = settings.AWS_STORAGE_BUCKET_NAME
    ttl = expires_in if expires_in is not None else int(
        getattr(settings, "AWS_S3_PRESIGN_EXPIRES_SECONDS", 3600)
    )
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=ttl,
        )
    except Exception as exc:
        logger.exception("S3 presign failed for key %s", object_key)
        raise StorageUploadError("Could not generate download URL for S3 object.") from exc


def delete_s3_object_if_exists(object_key: str | None) -> None:
    if not object_key:
        return
    try:
        client = _client()
        client.delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=object_key)
    except Exception:
        logger.warning("Could not delete S3 object %s", object_key, exc_info=True)
