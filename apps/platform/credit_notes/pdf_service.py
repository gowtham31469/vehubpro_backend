"""
CreditNotePdfService — generate a credit note PDF and persist it to storage.

Mirrors apps.platform.invoices.pdf_service's exact pipeline (Playwright
primary via credit_notes/pdf_generator.py, WeasyPrint has no fallback here
since the shared jobcard_preview.html template path has no WeasyPrint-era
twin — Playwright is the only renderer for this doc type), storage-key
convention, and whole-folder-purge-before-write behavior.
"""
from __future__ import annotations

import hashlib
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class PdfGenerationError(Exception):
    """Raised when PDF generation fails."""


class PdfNotAvailableError(Exception):
    """Raised when playwright is not installed."""


def _build_pdf_key(tenant_id: str, credit_note_id: str, credit_note_number: str, content_hash: str) -> str:
    safe_num = credit_note_number.replace("/", "-").replace(" ", "_")
    return f"credit_note_pdfs/{tenant_id}/{credit_note_id}/{safe_num}_{content_hash}.pdf"


def _purge_pdf_folder(tenant_id: str, credit_note_id: str) -> None:
    folder = f"credit_note_pdfs/{tenant_id}/{credit_note_id}/"
    backend = getattr(settings, "STORAGE_TYPE", "LOCAL").strip().upper()

    if backend == "LOCAL":
        from pathlib import Path
        dest = Path(settings.MEDIA_ROOT) / folder
        if dest.is_dir():
            for f in dest.glob("*.pdf"):
                try:
                    f.unlink()
                except OSError:
                    logger.warning("Could not delete stale credit note PDF %s", f, exc_info=True)

    elif backend == "S3":
        try:
            from core.storage.s3_backend import _client
            client = _client()
            bucket = settings.AWS_STORAGE_BUCKET_NAME
            resp = client.list_objects_v2(Bucket=bucket, Prefix=folder)
            keys = [obj["Key"] for obj in resp.get("Contents", [])]
            if keys:
                client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in keys]})
        except Exception:
            logger.warning("Could not purge S3 credit note PDF folder %s", folder, exc_info=True)


def _store_pdf_bytes(pdf_bytes: bytes, relative_key: str) -> str:
    backend = getattr(settings, "STORAGE_TYPE", "LOCAL").strip().upper()

    if backend == "LOCAL":
        from pathlib import Path
        from core.storage.exceptions import StorageUploadError
        dest = Path(settings.MEDIA_ROOT) / relative_key
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_bytes(pdf_bytes)
        except OSError as exc:
            logger.exception("Local PDF write failed: %s", relative_key)
            raise StorageUploadError("Could not save PDF to local storage.") from exc
        return relative_key.replace("\\", "/")

    if backend == "S3":
        from core.storage.s3_backend import upload_to_s3
        import io
        buf = io.BytesIO(pdf_bytes)
        return upload_to_s3(buf, relative_key, "application/pdf")

    from core.storage.exceptions import StorageConfigError
    raise StorageConfigError(f"Unsupported STORAGE_TYPE: {backend}")


class CreditNotePdfService:
    """Stateless PDF generation and storage service."""

    @staticmethod
    def generate_and_store(credit_note, *, force: bool = False) -> str:
        if credit_note.pdf_key and not force:
            return credit_note.pdf_key

        try:
            from apps.platform.credit_notes.pdf_generator import (
                render_credit_note_preview_html,
                generate_credit_note_pdf,
            )
            html_content = render_credit_note_preview_html(credit_note)
            pdf_bytes = generate_credit_note_pdf(html_content)
        except ImportError as ie:
            logger.warning("Playwright not available (%s) for credit note PDF generation", str(ie))
            raise PdfNotAvailableError(
                "playwright is not installed. Add it to requirements and restart."
            ) from ie
        except Exception as exc:
            logger.exception("PDF generation failed for credit note %s", credit_note.credit_note_number)
            raise PdfGenerationError(f"PDF generation failed: {exc}") from exc

        content_hash = hashlib.sha256(pdf_bytes).hexdigest()[:8]
        relative_key = _build_pdf_key(
            str(credit_note.tenant_id),
            str(credit_note.id),
            credit_note.credit_note_number,
            content_hash,
        )

        _purge_pdf_folder(str(credit_note.tenant_id), str(credit_note.id))

        try:
            stored_key = _store_pdf_bytes(pdf_bytes, relative_key)
        except Exception as exc:
            logger.exception("PDF storage failed for credit note %s", credit_note.credit_note_number)
            raise PdfGenerationError(f"PDF storage failed: {exc}") from exc

        from apps.platform.credit_notes.models import CreditNote as CreditNoteModel
        CreditNoteModel.objects.filter(pk=credit_note.pk).update(
            pdf_key=stored_key,
            updated_at=timezone.now(),
        )
        credit_note.pdf_key = stored_key
        return stored_key

    @staticmethod
    def resolve_url(pdf_key: str | None) -> str | None:
        if not pdf_key:
            return None
        from core.storage.resolve import resolve_media_url
        return resolve_media_url(pdf_key)
