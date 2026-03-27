"""Persist uploads to local MEDIA_ROOT."""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

from core.storage.exceptions import StorageUploadError

logger = logging.getLogger(__name__)


def save_upload_local(uploaded_file: UploadedFile, relative_key: str) -> str:
    """
    Write file under MEDIA_ROOT / relative_key.

    `relative_key` must be a safe relative path (no leading slash, no '..').

    Returns the same relative_key stored in the database.
    """
    if ".." in relative_key or relative_key.startswith(("/", "\\")):
        raise StorageUploadError("Invalid relative storage path.")

    dest = Path(settings.MEDIA_ROOT) / relative_key
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        with dest.open("wb+") as out:
            for chunk in uploaded_file.chunks():
                out.write(chunk)
    except OSError as exc:
        logger.exception("Local branding upload failed: %s", relative_key)
        raise StorageUploadError("Could not save file to local storage.") from exc

    return relative_key.replace("\\", "/")


def delete_local_if_exists(relative_key: str | None) -> None:
    if not relative_key:
        return
    path = Path(settings.MEDIA_ROOT) / relative_key
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        logger.warning("Could not delete local file %s", path, exc_info=True)
