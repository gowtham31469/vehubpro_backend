"""
JobCardPdfService — generate an operational PDF job card and persist it to storage.
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

def _build_pdf_key(tenant_id: str, jobcard_id: str, jobcard_number: str) -> str:
    safe_num = jobcard_number.replace("/", "-").replace(" ", "_")
    return f"jobcard_pdfs/{tenant_id}/{jobcard_id}/{safe_num}_{uuid.uuid4().hex[:8]}.pdf"


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
    return f"₹{Decimal(str(value or 0)):,.2f}"


def _fmt_date(dt) -> str:
    if not dt:
        return "—"
    try:
        return dt.strftime("%-d %b %Y")
    except ValueError:
        return dt.strftime("%d %b %Y").lstrip("0")


def _fmt_datetime(dt) -> str:
    if not dt:
        return "—"
    try:
        return dt.strftime("%-d %b %Y %I:%M %p")
    except ValueError:
        return dt.strftime("%d %b %Y %H:%M")


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
        elif raw[:4] == b"GIF8":
            mime = "image/gif"
        elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            mime = "image/webp"

        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"

    except Exception:
        logger.warning(
            "Could not build logo data URL for JobCard PDF (tenant_id=%s)", tenant_id, exc_info=True
        )
    return None


def _build_context(job_card) -> dict:
    """Build the template context dict from a JobCard instance."""
    
    # ── Tenant branding ───────────────────────────────────────────────────
    accent_color = "#1d4ed8"
    try:
        from apps.platform.tenants.models import TenantBranding
        branding = TenantBranding.objects.filter(tenant_id=job_card.tenant_id).first()
        if branding and branding.primary_color:
            accent_color = branding.primary_color
    except Exception:
        pass

    # ── Vehicle ───────────────────────────────────────────────────────────
    vehicle_label = f"{job_card.vehicle.brand.name} {job_card.vehicle.vehicle_model.name}" if job_card.vehicle and job_card.vehicle.brand and job_card.vehicle.vehicle_model else "—"
    vehicle_odo = f"{job_card.km_reading:,} km" if job_card.km_reading else "—"

    # ── Line items ────────────────────────────────────────────────────────
    line_items_ctx = []
    raw_lines = list(job_card.line_items.all().order_by("sort_order", "created_at"))
    for line in raw_lines:
        line_items_ctx.append({
            "description":        line.description,
            "detail_text":        line.detail_text or "",
            "qty_display":        str(Decimal(str(line.quantity)).normalize()),
            "unit_price_display": _fmt_money(line.unit_price),
            "line_total_display": _fmt_money(line.line_total),
        })

    # ── GST label ─────────────────────────────────────────────────────────
    cgst = Decimal(str(job_card.cgst_amount or 0))
    sgst = Decimal(str(job_card.sgst_amount or 0))
    igst = Decimal(str(job_card.igst_amount or 0))
    total_gst = cgst + sgst + igst

    gst_label = "GST"
    if cgst > 0 and sgst > 0:
        gst_label = "CGST + SGST"
    elif igst > 0:
        gst_label = "IGST"

    # ── Status Strip ────────────────────────────────────────────────────────
    STATUS_MAP = {
        "job_control":  ("#f1f5f9", "#475569", "STATUS: JOB CONTROL"),
        "working":      ("#fffbeb", "#d97706", "STATUS: WORKING"),
        "ready_for_fi": ("#fff7ed", "#c2410c", "STATUS: READY FOR FINAL INSPECTION"),
        "completed":    ("#ecfdf5", "#059669", "STATUS: COMPLETED"),
        "invoiced":     ("#eff6ff", "#2563eb", "STATUS: INVOICED"),
        "delivered":    ("#f0fdf4", "#16a34a", "STATUS: DELIVERED"),
        "cancelled":    ("#fef2f2", "#dc2626", "STATUS: CANCELLED"),
    }
    status_bg, status_fg, status_text = STATUS_MAP.get(
        job_card.status,
        ("#f1f5f9", "#475569", f"STATUS: {job_card.status.upper()}"),
    )

    # ── Totals ──────────────────────────────────────────────────────────────
    discount = Decimal(str(job_card.discount_amount or 0))
    shop_fees = Decimal(str(job_card.shop_fees or 0))

    return {
        # Branding
        "logo_data_url":    _logo_data_url(job_card.tenant_id),
        "tenant_name":      job_card.tenant.name if job_card.tenant else "AUTOCARE PRO",
        "accent_color":     accent_color,
        # JobCard meta
        "jobcard_number":   job_card.jobcard_number,
        "date_created":      _fmt_date(job_card.created_at),
        "estimated_delivery": _fmt_datetime(job_card.estimated_delivery),
        # Customer
        "customer_name":    job_card.customer.full_name if job_card.customer else "—",
        "customer_phone":   job_card.customer.phone if job_card.customer else "",
        "customer_email":   job_card.customer.email if job_card.customer else "",
        "customer_address": job_card.customer.address if job_card.customer else "",
        # Vehicle
        "vehicle_label":    vehicle_label,
        "vehicle_reg":      job_card.vehicle.registration_no if job_card.vehicle else "—",
        "vehicle_vin":      job_card.vehicle.vin_number if job_card.vehicle else "—",
        "vehicle_odo":      vehicle_odo,
        # Line items
        "line_items":       line_items_ctx,
        # Totals
        "subtotal":         _fmt_money(job_card.subtotal),
        "discount":         _fmt_money(discount) if discount > 0 else "",
        "gst_label":        gst_label,
        "gst_total":        _fmt_money(total_gst) if total_gst > 0 else "",
        "shop_fees_display":_fmt_money(shop_fees) if shop_fees > 0 else "",
        "total_est":        _fmt_money(job_card.total_amount),
        # Status
        "status_bg":        status_bg,
        "status_fg":        status_fg,
        "status_text":      status_text,
        # Notes
        "notes":            job_card.notes or "",
    }


# ── Core render function ──────────────────────────────────────────────────────

def _render_pdf(job_card) -> bytes:
    if not WEASYPRINT_AVAILABLE:
        raise PdfNotAvailableError("weasyprint is not installed.")

    context = _build_context(job_card)
    html_string = render_to_string("jobcards/jobcard_pdf.html", context)

    import weasyprint
    pdf_bytes = weasyprint.HTML(string=html_string).write_pdf()
    return pdf_bytes


# ── Public service class ──────────────────────────────────────────────────────

class JobCardPdfService:
    """Stateless PDF generation and storage service for Job Cards."""

    @staticmethod
    def generate_and_store(job_card, *, force: bool = False) -> str:
        if not WEASYPRINT_AVAILABLE:
            raise PdfNotAvailableError("weasyprint is not installed.")

        # We don't store the key in models for now, as Job Card is operational.
        # But for caching purposes, let's assume we might want to in future.
        # For now, we'll just generate it on the fly or use a temporary key.
        # Actually, let's follow the Invoice pattern and add pdf_key to JobCard model if needed.
        # But wait, I don't want to run migrations if I can avoid it.
        # I'll just return the pre-signed URL directly without storing.
        # No, wait. S3 requires a key.
        
        relative_key = _build_pdf_key(
            str(job_card.tenant_id),
            str(job_card.id),
            job_card.jobcard_number,
        )

        try:
            pdf_bytes = _render_pdf(job_card)
            stored_key = _store_pdf_bytes(pdf_bytes, relative_key)
            return stored_key
        except Exception as exc:
            logger.exception("PDF generation/storage failed for JobCard %s", job_card.jobcard_number)
            raise PdfGenerationError(f"PDF generation failed: {exc}") from exc

    @staticmethod
    def resolve_url(pdf_key: str | None) -> str | None:
        if not pdf_key:
            return None
        from core.storage.resolve import resolve_media_url
        return resolve_media_url(pdf_key)
