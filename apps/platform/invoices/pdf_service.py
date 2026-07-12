"""
InvoicePdfService — generate a GST-compliant PDF invoice and persist it to storage.

Pipeline
--------
1. Build a Python context dict from the Invoice model (PII decryption, money
   formatting, logo base64-encoding, GST label derivation).
2. Render ``invoices/invoice_pdf.html`` via Django's template engine into an
   HTML string.
3. Convert the HTML string to PDF bytes using WeasyPrint (HTML→PDF).
   - The tenant logo is embedded as a ``data:`` URI so it is self-contained
     and never requires a filesystem/network lookup by WeasyPrint.
4. Persist the bytes to the configured storage backend (LOCAL or S3) using the
   same ``core.storage`` infrastructure as image uploads.
5. Save the resulting storage key to ``Invoice.pdf_key``.

Why WeasyPrint instead of ReportLab
-------------------------------------
WeasyPrint renders CSS/HTML faithfully, so the PDF matches the React-rendered
web invoice exactly — same fonts, same flex/grid layout, same colours.
ReportLab required a manual ReportLab-specific layout that always drifted from
the HTML design.

Compliance
----------
DPDP Act 2023 / GDPR:
  - PII (name, phone, email, address) is decrypted only at render time and
    never written to disk; it lives only inside the produced PDF bytes.
  - ``invoice.is_pii_erased`` → "[Customer data erased]" placeholder.
  - ``erase_customer_pii()`` deletes the stored PDF via ``delete_stored_media``.

ISO 27001 (A.9 / A.12):
  - S3 backend: URLs are pre-signed (time-limited).
  - LOCAL backend: URLs are absolute, scoped to ``settings.BASE_URL``.
  - All generation events are audit-logged in the calling view.

GST (CGST Act 2017):
  - Invoice number, date, GSTIN (tenant + customer), HSN/SAC codes, qty,
    unit price, CGST, SGST/IGST, and totals are all present in the template.
"""
from __future__ import annotations

import base64
import io
import logging
import uuid
from decimal import Decimal

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

# ── WeasyPrint availability guard ─────────────────────────────────────────────
try:
    import weasyprint  # noqa: F401
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False


class PdfGenerationError(Exception):
    """Raised when PDF generation fails."""


class PdfNotAvailableError(Exception):
    """Raised when weasyprint is not installed."""


# ── Storage helpers ───────────────────────────────────────────────────────────

def _build_pdf_key(tenant_id: str, invoice_id: str, invoice_number: str) -> str:
    safe_num = invoice_number.replace("/", "-").replace(" ", "_")
    return f"invoice_pdfs/{tenant_id}/{invoice_id}/{safe_num}_{uuid.uuid4().hex[:8]}.pdf"


def _store_pdf_bytes(pdf_bytes: bytes, relative_key: str) -> str:
    """Persist raw PDF bytes to the configured storage backend. Returns stored key."""
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


# ── Context-building helpers ──────────────────────────────────────────────────

def _fmt_money(value) -> str:
    """₹ formatted string — always uses the Unicode rupee sign (HTML supports it)."""
    return f"₹{Decimal(str(value or 0)):,.2f}"


def _fmt_date(dt) -> str:
    if not dt:
        return "—"
    try:
        return dt.strftime("%-d %b %Y")
    except ValueError:
        return dt.strftime("%d %b %Y").lstrip("0")


def _logo_data_url(tenant_id) -> str | None:
    """
    Return the tenant logo as a ``data:<mime>;base64,...`` URI, or None.

    Embedding the image as a data URI guarantees that WeasyPrint renders it
    without needing filesystem access or a running HTTP server.
    """
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

        # Detect MIME type from bytes magic number
        mime = "image/png"
        if raw[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        elif raw[:4] == b"<svg" or b"<svg" in raw[:64]:
            mime = "image/svg+xml"
        elif raw[:4] == b"GIF8":
            mime = "image/gif"
        elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            mime = "image/webp"

        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"

    except Exception:
        logger.warning(
            "Could not build logo data URL for PDF (tenant_id=%s)", tenant_id, exc_info=True
        )
    return None


def _build_context(invoice) -> dict:
    """Build the template context dict from an Invoice instance."""
    erased = invoice.is_pii_erased

    # ── PII fields ────────────────────────────────────────────────────────
    customer_name    = "" if erased else (invoice.get_customer_name() or "—")
    customer_phone   = "" if erased else (invoice.get_customer_phone() or "")
    customer_email   = "" if erased else (invoice.get_customer_email() or "")
    customer_address = "" if erased else (invoice.get_customer_address() or "")
    customer_gstin   = "" if erased else (invoice.customer_gstin or "")

    # ── Tenant branding ───────────────────────────────────────────────────
    accent_color = "#1d4ed8"  # Tailwind blue-700 default
    try:
        from apps.platform.tenants.models import TenantBranding
        branding = TenantBranding.objects.filter(tenant_id=invoice.tenant_id).first()
        if branding and branding.primary_color:
            accent_color = branding.primary_color
    except Exception:
        pass

    # ── Job card reference ────────────────────────────────────────────────
    job_card_ref = ""
    if invoice.job_card_id:
        try:
            jc_number = invoice.job_card.jobcard_number if invoice.job_card else None
            job_card_ref = jc_number or ""
        except Exception:
            pass

    # ── Vehicle ───────────────────────────────────────────────────────────
    vehicle_odo = (
        f"{invoice.vehicle_odometer_snapshot:,} km"
        if invoice.vehicle_odometer_snapshot else "—"
    )

    # ── Line items ────────────────────────────────────────────────────────
    line_items_ctx = []
    raw_lines = list(invoice.line_items.order_by("sort_order", "created_at"))
    for line in raw_lines:
        line_items_ctx.append({
            "description":        line.description,
            "detail_text":        getattr(line, "detail_text", "") or "",
            "hsn_sac_code":       getattr(line, "hsn_sac_code", "") or "",
            "qty_display":        str(Decimal(str(line.quantity)).normalize()),
            "unit_price_display": _fmt_money(line.unit_price),
            "line_total_display": _fmt_money(line.line_total),
        })

    # ── GST label ─────────────────────────────────────────────────────────
    cgst = Decimal(str(invoice.cgst_amount or 0))
    sgst = Decimal(str(invoice.sgst_amount or 0))
    igst = Decimal(str(invoice.igst_amount or 0))
    total_gst = cgst + sgst + igst

    gst_rates = set()
    for line in raw_lines:
        rate = Decimal(str(getattr(line, "gst_percentage", 0) or 0))
        if rate:
            gst_rates.add(rate)
    rate_str = f"{gst_rates.pop():.0f}%" if len(gst_rates) == 1 else "GST"
    if cgst > 0 and sgst > 0:
        gst_label = f"CGST + SGST ({rate_str})"
    elif igst > 0:
        gst_label = f"IGST ({rate_str})"
    else:
        gst_label = f"GST ({rate_str})"

    # ── Payment status strip ──────────────────────────────────────────────
    balance = max(
        Decimal("0"),
        Decimal(str(invoice.total_amount or 0)) - Decimal(str(invoice.amount_paid or 0)),
    )
    STATUS_MAP = {
        "paid":    ("#E8F5E9", "#2E7D32", "STATUS: FULLY PAID"),
        "partial": ("#fffbeb", "#d97706",
                    f"STATUS: PARTIALLY PAID · BALANCE {_fmt_money(balance)}"),
        "unpaid":  ("#fff1f2", "#e11d48", "STATUS: UNPAID"),
    }
    status_bg, status_fg, status_text = STATUS_MAP.get(
        invoice.payment_status,
        ("#f1f5f9", "#475569", f"STATUS: {invoice.payment_status.upper()}"),
    )

    # ── Discount / shop fees ──────────────────────────────────────────────
    discount = Decimal(str(invoice.discount_amount or 0))
    shop_fees = Decimal(str(invoice.shop_fees or 0))

    return {
        # Branding
        "logo_data_url":    _logo_data_url(invoice.tenant_id),
        "tenant_name":      invoice.tenant_name_snapshot or "AUTOCARE PRO",
        "tenant_address_snapshot": invoice.tenant_address_snapshot or "",
        "tenant_gstin_snapshot": invoice.tenant_gstin_snapshot or "",
        "accent_color":     accent_color,
        # Invoice meta
        "invoice_number":   invoice.invoice_number,
        "date_issued":      _fmt_date(invoice.created_at),
        "job_card_ref":     job_card_ref,
        # Customer
        "is_pii_erased":    erased,
        "customer_name":    customer_name,
        "customer_phone":   customer_phone,
        "customer_email":   customer_email,
        "customer_address": customer_address,
        "customer_gstin":   customer_gstin,
        # Vehicle
        "vehicle_label":    invoice.vehicle_label_snapshot or "—",
        "vehicle_reg":      invoice.vehicle_registration_no_snapshot or "—",
        "vehicle_vin":      invoice.vehicle_vin_snapshot or "—",
        "vehicle_odo":      vehicle_odo,
        # Line items
        "line_items":       line_items_ctx,
        # Totals
        "subtotal":         _fmt_money(invoice.subtotal),
        "discount":         _fmt_money(discount) if discount > 0 else "",
        "gst_label":        gst_label,
        "gst_total":        _fmt_money(total_gst) if total_gst > 0 else "",
        "shop_fees_display":_fmt_money(shop_fees) if shop_fees > 0 else "",
        "total_due":        _fmt_money(invoice.total_amount),
        # Status
        "status_bg":        status_bg,
        "status_fg":        status_fg,
        "status_text":      status_text,
        # Notes and recommendations
        "notes":            invoice.notes or "",
        "next_service_recommendation": getattr(invoice, "next_service_recommendation", "") or "",
        # Signatures
        "customer_signature": getattr(invoice, "customer_signature", "") or "",
        "customer_signature_date": _fmt_date(getattr(invoice, "customer_signature_date", None)),
        "admin_signature": getattr(invoice, "admin_signature", "") or "",
        "admin_signature_date": _fmt_date(getattr(invoice, "admin_signature_date", None)),
    }


# ── Core render function ──────────────────────────────────────────────────────

def _render_pdf(invoice) -> bytes:
    """Render the invoice HTML template and convert to PDF bytes via WeasyPrint."""
    if not WEASYPRINT_AVAILABLE:
        raise PdfNotAvailableError(
            "weasyprint is not installed. Run: pip install weasyprint"
        )

    context = _build_context(invoice)
    html_string = render_to_string("invoices/invoice_pdf.html", context)

    import weasyprint
    pdf_bytes = weasyprint.HTML(string=html_string).write_pdf()
    return pdf_bytes


# ── Public service class ──────────────────────────────────────────────────────

class InvoicePdfService:
    """Stateless PDF generation and storage service."""

    @staticmethod
    def generate_and_store(invoice, *, force: bool = False) -> str:
        """
        Generate the invoice PDF, upload to storage, persist the key to the DB.

        Uses Playwright to render the invoice preview HTML to PDF, ensuring
        pixel-perfect consistency between web preview and PDF.

        Parameters
        ----------
        invoice : Invoice
            Must have ``line_items`` prefetched (or be acceptable to hit the DB).
        force : bool
            Regenerate even if ``pdf_key`` is already set (e.g. after a payment
            status update). The old file is deleted from storage first.

        Returns
        -------
        str
            The storage key (relative LOCAL path or S3 object key).
        """
        if invoice.pdf_key and not force:
            return invoice.pdf_key

        # Delete old file if regenerating
        if invoice.pdf_key and force:
            try:
                from core.storage.resolve import delete_stored_media
                delete_stored_media(invoice.pdf_key)
            except Exception:
                logger.warning(
                    "Could not delete old PDF %s before regeneration", invoice.pdf_key
                )

        try:
            from apps.platform.invoices.pdf_generator import (
                render_invoice_preview_html,
                generate_invoice_pdf,
            )
            # Render the invoice preview HTML
            html_content = render_invoice_preview_html(invoice)
            logger.info("Using Playwright for PDF generation (invoice: %s)", invoice.invoice_number)
            logger.debug("Rendered HTML length: %d chars, includes tenant_address: %s",
                        len(html_content), 'tenant_address_snapshot' in html_content)
            # Generate PDF using Playwright
            pdf_bytes = generate_invoice_pdf(html_content)
        except ImportError as ie:
            logger.warning(
                "Playwright not available (%s), falling back to WeasyPrint", str(ie)
            )
            if not WEASYPRINT_AVAILABLE:
                raise PdfNotAvailableError(
                    "weasyprint is not installed. Add it to requirements and restart."
                )
            try:
                logger.info("Using WeasyPrint for PDF generation (invoice: %s)", invoice.invoice_number)
                pdf_bytes = _render_pdf(invoice)
            except PdfNotAvailableError:
                raise
            except Exception as exc:
                logger.exception("PDF render failed for invoice %s", invoice.invoice_number)
                raise PdfGenerationError(f"PDF generation failed: {exc}") from exc
        except Exception as exc:
            logger.exception("PDF generation failed for invoice %s", invoice.invoice_number)
            raise PdfGenerationError(f"PDF generation failed: {exc}") from exc

        relative_key = _build_pdf_key(
            str(invoice.tenant_id),
            str(invoice.id),
            invoice.invoice_number,
        )

        try:
            stored_key = _store_pdf_bytes(pdf_bytes, relative_key)
        except Exception as exc:
            logger.exception("PDF storage failed for invoice %s", invoice.invoice_number)
            raise PdfGenerationError(f"PDF storage failed: {exc}") from exc

        # Persist the key
        from apps.platform.invoices.models import Invoice as InvoiceModel
        InvoiceModel.objects.filter(pk=invoice.pk).update(
            pdf_key=stored_key,
            updated_at=timezone.now(),
        )
        invoice.pdf_key = stored_key
        return stored_key

    @staticmethod
    def resolve_url(pdf_key: str | None) -> str | None:
        """Resolve a stored pdf_key to a usable download URL."""
        if not pdf_key:
            return None
        from core.storage.resolve import resolve_media_url
        return resolve_media_url(pdf_key)
