"""
QuotationPdfService — generate a quotation PDF (via the shared Playwright
template) and persist it to storage. Mirrors JobCardPdfService/InvoicePdfService's
storage plumbing exactly; unlike those two, there is no legacy WeasyPrint
fallback template for quotations — Playwright is the only rendering path,
consistent with "don't introduce another PDF framework unnecessarily".
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
    """Raised when Playwright is not installed."""


def _build_pdf_key(tenant_id: str, quotation_id: str, quotation_number: str, version: int, content_hash: str) -> str:
    safe_num = quotation_number.replace("/", "-").replace(" ", "_")
    return f"quotation_pdfs/{tenant_id}/{quotation_id}/{safe_num}_v{version}_{content_hash}.pdf"


def _purge_pdf_folder(tenant_id: str, quotation_id: str) -> None:
    """Delete every file in this quotation's PDF folder before writing a new one."""
    folder = f"quotation_pdfs/{tenant_id}/{quotation_id}/"
    backend = getattr(settings, "STORAGE_TYPE", "LOCAL").strip().upper()

    if backend == "LOCAL":
        from pathlib import Path
        dest = Path(settings.MEDIA_ROOT) / folder
        if dest.is_dir():
            for f in dest.glob("*.pdf"):
                try:
                    f.unlink()
                except OSError:
                    logger.warning("Could not delete stale quotation PDF %s", f, exc_info=True)

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
            logger.warning("Could not purge S3 quotation PDF folder %s", folder, exc_info=True)


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


class QuotationPdfService:
    """Stateless PDF generation and storage service for Quotations."""

    @staticmethod
    def generate_and_store(quotation, *, force: bool = False) -> str:
        if quotation.pdf_key and not force:
            return quotation.pdf_key

        try:
            from apps.platform.quotations.pdf_generator import (
                render_quotation_preview_html,
                generate_quotation_pdf,
            )
            html_content = render_quotation_preview_html(quotation)
            logger.info("Generating PDF for quotation %s v%s", quotation.quotation_number, quotation.version)
            pdf_bytes = generate_quotation_pdf(html_content)
        except ImportError as ie:
            raise PdfNotAvailableError(f"playwright is not installed: {ie}")
        except Exception as exc:
            logger.exception("PDF generation failed for quotation %s", quotation.quotation_number)
            raise PdfGenerationError(f"PDF generation failed: {exc}") from exc

        content_hash = hashlib.sha256(pdf_bytes).hexdigest()[:8]
        relative_key = _build_pdf_key(
            str(quotation.tenant_id),
            str(quotation.id),
            quotation.quotation_number,
            quotation.version,
            content_hash,
        )

        _purge_pdf_folder(str(quotation.tenant_id), str(quotation.id))

        try:
            stored_key = _store_pdf_bytes(pdf_bytes, relative_key)
        except Exception as exc:
            logger.exception("PDF storage failed for quotation %s", quotation.quotation_number)
            raise PdfGenerationError(f"PDF storage failed: {exc}") from exc

        from apps.platform.quotations.models import Quotation as QuotationModel
        QuotationModel.objects.filter(pk=quotation.pk).update(
            pdf_key=stored_key,
            updated_at=timezone.now(),
        )
        quotation.pdf_key = stored_key
        return stored_key

    @staticmethod
    def resolve_url(pdf_key: str | None) -> str | None:
        if not pdf_key:
            return None
        from core.storage.resolve import resolve_media_url
        return resolve_media_url(pdf_key)
