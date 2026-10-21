"""
ProformaInvoicePdfService + AdvanceReceiptPdfService — generate PDFs and
persist them to storage. Mirrors apps.platform.invoices.pdf_service's
storage plumbing (purge-before-write, content-hashed filename, LOCAL/S3
branch) exactly, reusing the same generic Playwright wrapper
(apps.platform.invoices.pdf_generator.generate_invoice_pdf — it just takes
an HTML string, nothing invoice-specific) rather than duplicating it.
"""
from __future__ import annotations

import hashlib
import io
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class PdfGenerationError(Exception):
    """Raised when PDF generation fails."""


class PdfNotAvailableError(Exception):
    """Raised when Playwright is not installed."""


# ── Storage helpers (identical pattern to invoices/pdf_service.py) ─────────

def _purge_pdf_folder(folder: str) -> None:
    backend = getattr(settings, "STORAGE_TYPE", "LOCAL").strip().upper()

    if backend == "LOCAL":
        from pathlib import Path
        dest = Path(settings.MEDIA_ROOT) / folder
        if dest.is_dir():
            for f in dest.glob("*.pdf"):
                try:
                    f.unlink()
                except OSError:
                    logger.warning("Could not delete stale PDF %s", f, exc_info=True)
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
            logger.warning("Could not purge S3 PDF folder %s", folder, exc_info=True)


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
        buf = io.BytesIO(pdf_bytes)
        return upload_to_s3(buf, relative_key, "application/pdf")

    from core.storage.exceptions import StorageConfigError
    raise StorageConfigError(f"Unsupported STORAGE_TYPE: {backend}")


def _render(html_content: str, *, label_for_logs: str) -> bytes:
    try:
        from apps.platform.proforma_invoices.pdf_generator import generate_invoice_pdf
        return generate_invoice_pdf(html_content)
    except ImportError as ie:
        logger.error("Playwright not available (%s) for %s", str(ie), label_for_logs)
        raise PdfNotAvailableError("playwright is not installed. Run: pip install playwright && playwright install chromium") from ie
    except Exception as exc:
        logger.exception("PDF generation failed for %s", label_for_logs)
        raise PdfGenerationError(f"PDF generation failed: {exc}") from exc


class ProformaInvoicePdfService:
    """Stateless PDF generation and storage service for ProformaInvoice."""

    @staticmethod
    def generate_and_store(proforma, *, force: bool = False) -> str:
        if proforma.pdf_key and not force:
            return proforma.pdf_key

        from apps.platform.proforma_invoices.pdf_generator import render_proforma_invoice_preview_html
        html_content = render_proforma_invoice_preview_html(proforma)
        pdf_bytes = _render(html_content, label_for_logs=f"proforma {proforma.proforma_number}")

        content_hash = hashlib.sha256(pdf_bytes).hexdigest()[:8]
        safe_num = proforma.proforma_number.replace("/", "-").replace(" ", "_")
        folder = f"proforma_invoice_pdfs/{proforma.tenant_id}/{proforma.id}/"
        relative_key = f"{folder}{safe_num}_v{proforma.version}_{content_hash}.pdf"

        _purge_pdf_folder(folder)
        try:
            stored_key = _store_pdf_bytes(pdf_bytes, relative_key)
        except Exception as exc:
            logger.exception("PDF storage failed for proforma %s", proforma.proforma_number)
            raise PdfGenerationError(f"PDF storage failed: {exc}") from exc

        from apps.platform.proforma_invoices.models import ProformaInvoice
        ProformaInvoice.objects.filter(pk=proforma.pk).update(pdf_key=stored_key, updated_at=timezone.now())
        proforma.pdf_key = stored_key
        return stored_key

    @staticmethod
    def resolve_url(pdf_key: str | None) -> str | None:
        if not pdf_key:
            return None
        from core.storage.resolve import resolve_media_url
        return resolve_media_url(pdf_key)


class AdvanceReceiptPdfService:
    """Stateless PDF generation and storage service for an AdvancePayment's receipt."""

    @staticmethod
    def generate_and_store(payment, *, force: bool = False) -> str:
        if not payment.receipt_number:
            raise PdfGenerationError("Cannot generate a receipt PDF before a receipt number is allocated.")
        if payment.receipt_pdf_key and not force:
            return payment.receipt_pdf_key

        from apps.platform.proforma_invoices.pdf_generator import render_advance_receipt_html
        html_content = render_advance_receipt_html(payment)
        pdf_bytes = _render(html_content, label_for_logs=f"advance receipt {payment.receipt_number}")

        content_hash = hashlib.sha256(pdf_bytes).hexdigest()[:8]
        safe_num = payment.receipt_number.replace("/", "-").replace(" ", "_")
        folder = f"advance_receipts/{payment.tenant_id}/{payment.id}/"
        relative_key = f"{folder}{safe_num}_{content_hash}.pdf"

        _purge_pdf_folder(folder)
        try:
            stored_key = _store_pdf_bytes(pdf_bytes, relative_key)
        except Exception as exc:
            logger.exception("PDF storage failed for advance receipt %s", payment.receipt_number)
            raise PdfGenerationError(f"PDF storage failed: {exc}") from exc

        from apps.platform.proforma_invoices.models import AdvancePayment
        AdvancePayment.objects.filter(pk=payment.pk).update(receipt_pdf_key=stored_key, updated_at=timezone.now())
        payment.receipt_pdf_key = stored_key
        return stored_key

    @staticmethod
    def resolve_url(pdf_key: str | None) -> str | None:
        if not pdf_key:
            return None
        from core.storage.resolve import resolve_media_url
        return resolve_media_url(pdf_key)
