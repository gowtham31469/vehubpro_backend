"""
SaleInvoicePdfService — generate a PDF for a VehicleSaleInvoice and persist it
to storage, so a dealer has something to actually hand/email to the buyer.

Deliberately a separate, simpler service from apps.platform.invoices.pdf_service
— VehicleSaleInvoice has no GST/line-items/HSN fields (a used-car resale
document, not a GST tax invoice), so the template and context here are much
smaller. Mirrors the same storage pattern (WeasyPrint HTML->PDF, content-hashed
filename, LOCAL/S3 backend split, purge-then-store) for consistency.
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
from decimal import Decimal

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

try:
    import weasyprint  # noqa: F401
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


class PdfGenerationError(Exception):
    """Raised when PDF generation fails."""


class PdfNotAvailableError(Exception):
    """Raised when weasyprint is not installed."""


def _fmt_money(value) -> str:
    return f"₹{Decimal(str(value or 0)):,.2f}"


def _fmt_date(dt) -> str:
    if not dt:
        return "—"
    try:
        return dt.strftime("%-d %b %Y")
    except ValueError:
        return dt.strftime("%d %b %Y").lstrip("0")


def _logo_data_url(tenant_id) -> str | None:
    try:
        from apps.platform.tenants.models import TenantBranding
        branding = TenantBranding.objects.filter(tenant_id=tenant_id).first()
        if not branding or not branding.logo:
            return None

        raw: bytes | None = None
        backend = getattr(settings, "STORAGE_TYPE", "LOCAL").strip().upper()

        if backend == "LOCAL":
            from pathlib import Path
            path = Path(settings.MEDIA_ROOT) / branding.logo
            if path.is_file():
                raw = path.read_bytes()
        elif backend == "S3":
            import boto3
            client = boto3.client(
                "s3",
                region_name=getattr(settings, "AWS_REGION", "us-east-1"),
                aws_access_key_id=getattr(settings, "AWS_ACCESS_KEY_ID", "") or None,
                aws_secret_access_key=getattr(settings, "AWS_SECRET_ACCESS_KEY", "") or None,
            )
            buf = io.BytesIO()
            client.download_fileobj(settings.AWS_STORAGE_BUCKET_NAME, branding.logo, buf)
            buf.seek(0)
            raw = buf.read()

        if not raw:
            return None

        mime = "image/png"
        if raw[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        elif raw[:4] == b"<svg" or b"<svg" in raw[:64]:
            mime = "image/svg+xml"

        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        logger.warning("Could not build logo data URL for sale invoice PDF (tenant_id=%s)", tenant_id, exc_info=True)
    return None


def _build_context(invoice) -> dict:
    accent_color = "#1d4ed8"
    try:
        from apps.platform.tenants.models import TenantBranding
        branding = TenantBranding.objects.filter(tenant_id=invoice.tenant_id).first()
        if branding and branding.primary_color:
            accent_color = branding.primary_color
    except Exception:
        pass

    tenant_name = "VeHubPro Dealer"
    try:
        from apps.platform.tenants.models import Tenant
        tenant = Tenant.objects.filter(id=invoice.tenant_id).first()
        if tenant and tenant.name:
            tenant_name = tenant.name
    except Exception:
        pass

    amount_paid = Decimal(str(invoice.amount_paid or 0))
    sale_amount = Decimal(str(invoice.sale_amount or 0))
    balance_due = max(Decimal("0"), sale_amount - amount_paid)

    STATUS_MAP = {
        "paid": ("#E8F5E9", "#2E7D32", "FULLY PAID"),
        "partial": ("#fffbeb", "#d97706", f"PARTIALLY PAID — BALANCE {_fmt_money(balance_due)}"),
        "unpaid": ("#fff1f2", "#e11d48", "UNPAID"),
    }
    status_bg, status_fg, status_text = STATUS_MAP.get(
        invoice.payment_status, ("#f1f5f9", "#475569", invoice.payment_status.upper())
    )

    return {
        "logo_data_url": _logo_data_url(invoice.tenant_id),
        "tenant_name": tenant_name,
        "accent_color": accent_color,
        "invoice_number": invoice.invoice_number,
        "date_issued": _fmt_date(invoice.issued_at),
        "buyer_name": invoice.buyer_name_snapshot or "—",
        "buyer_phone": invoice.buyer_phone_snapshot or "",
        "buyer_email": invoice.buyer_email_snapshot or "",
        "vehicle_label": invoice.vehicle_label_snapshot or "—",
        "vehicle_reg": invoice.vehicle_registration_no_snapshot or "—",
        "sale_amount": _fmt_money(invoice.sale_amount),
        "amount_paid": _fmt_money(invoice.amount_paid),
        "balance_due": _fmt_money(balance_due),
        "status_bg": status_bg,
        "status_fg": status_fg,
        "status_text": status_text,
        "notes": invoice.notes or "",
    }


def render_preview_html(invoice) -> str:
    """Render the same template/context used for the PDF, as plain HTML — for
    an in-app iframe preview that's guaranteed pixel-identical to the download."""
    return render_to_string("dealer_sales/sale_invoice_pdf.html", _build_context(invoice))


def _render_pdf(invoice) -> bytes:
    if not WEASYPRINT_AVAILABLE:
        raise PdfNotAvailableError("weasyprint is not installed. Run: pip install weasyprint")

    html_string = render_preview_html(invoice)

    import weasyprint
    return weasyprint.HTML(string=html_string).write_pdf()


def _build_pdf_key(tenant_id: str, invoice_id: str, invoice_number: str, content_hash: str) -> str:
    safe_num = invoice_number.replace("/", "-").replace(" ", "_")
    return f"dealer_sale_invoice_pdfs/{tenant_id}/{invoice_id}/{safe_num}_{content_hash}.pdf"


def _purge_pdf_folder(tenant_id: str, invoice_id: str) -> None:
    folder = f"dealer_sale_invoice_pdfs/{tenant_id}/{invoice_id}/"
    backend = getattr(settings, "STORAGE_TYPE", "LOCAL").strip().upper()

    if backend == "LOCAL":
        from pathlib import Path
        dest = Path(settings.MEDIA_ROOT) / folder
        if dest.is_dir():
            for f in dest.glob("*.pdf"):
                try:
                    f.unlink()
                except OSError:
                    logger.warning("Could not delete stale sale invoice PDF %s", f, exc_info=True)
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
            logger.warning("Could not purge S3 sale invoice PDF folder %s", folder, exc_info=True)


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
            logger.exception("Local sale invoice PDF write failed: %s", relative_key)
            raise StorageUploadError("Could not save PDF to local storage.") from exc
        return relative_key.replace("\\", "/")

    if backend == "S3":
        from core.storage.s3_backend import upload_to_s3
        buf = io.BytesIO(pdf_bytes)
        return upload_to_s3(buf, relative_key, "application/pdf")

    from core.storage.exceptions import StorageConfigError
    raise StorageConfigError(f"Unsupported STORAGE_TYPE: {backend}")


class SaleInvoicePdfService:
    """Stateless PDF generation and storage service for VehicleSaleInvoice."""

    @staticmethod
    def generate_and_store(invoice, *, force: bool = False) -> str:
        if invoice.pdf_key and not force:
            return invoice.pdf_key

        try:
            pdf_bytes = _render_pdf(invoice)
        except PdfNotAvailableError:
            raise
        except Exception as exc:
            logger.exception("Sale invoice PDF render failed for %s", invoice.invoice_number)
            raise PdfGenerationError(f"PDF generation failed: {exc}") from exc

        content_hash = hashlib.sha256(pdf_bytes).hexdigest()[:8]
        relative_key = _build_pdf_key(str(invoice.tenant_id), str(invoice.id), invoice.invoice_number, content_hash)

        _purge_pdf_folder(str(invoice.tenant_id), str(invoice.id))

        try:
            stored_key = _store_pdf_bytes(pdf_bytes, relative_key)
        except Exception as exc:
            logger.exception("Sale invoice PDF storage failed for %s", invoice.invoice_number)
            raise PdfGenerationError(f"PDF storage failed: {exc}") from exc

        from apps.platform.dealer_sales.models import VehicleSaleInvoice
        VehicleSaleInvoice.objects.filter(pk=invoice.pk).update(pdf_key=stored_key, updated_at=timezone.now())
        invoice.pdf_key = stored_key
        return stored_key

    @staticmethod
    def resolve_url(pdf_key: str | None) -> str | None:
        if not pdf_key:
            return None
        from core.storage import resolve_media_url
        return resolve_media_url(pdf_key)
