"""
Job Card PDF generation using Playwright.

Renders the job card preview HTML directly to PDF using a headless browser.
This ensures the PDF matches the web preview pixel-perfectly, and lets the
template use real web fonts / icon fonts / Tailwind utility classes that a
CSS-only renderer (WeasyPrint) cannot execute.

The rendered template (`jobcards/jobcard_preview.html`) is shared with invoices
(see `apps.platform.invoices.pdf_generator`) — it's parameterized by
doc_type_label/doc_number_label/doc_number/notes_label so both document types
stay pixel-identical by construction rather than by copy-pasted markup.
"""
import asyncio
import logging
from decimal import Decimal

from django.template.loader import render_to_string

from apps.common.utils.pdf_documents import (
    build_invoice_settings_pdf_context,
    derive_pan_and_state_code,
    fmt_date,
    fmt_money,
    split_lines_into_sections,
)

logger = logging.getLogger(__name__)


async def generate_jobcard_pdf_async(html_content: str) -> bytes:
    """
    Generate PDF from HTML using Playwright headless browser.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed")
        raise ImportError("playwright is required for PDF generation")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_viewport_size({"width": 1024, "height": 1448})
            await page.set_content(html_content, wait_until="networkidle")
            pdf_bytes = await page.pdf(
                format="A4",
                margin={"top": "14mm", "right": "16mm", "bottom": "14mm", "left": "16mm"},
                print_background=True,
            )
            return pdf_bytes
        finally:
            await browser.close()


def generate_jobcard_pdf(html_content: str) -> bytes:
    """Synchronous wrapper for async PDF generation."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(generate_jobcard_pdf_async(html_content))
    finally:
        loop.close()


# Status -> (display label, Tailwind text-color utility class)
_STATUS_DISPLAY = {
    "job_control":  ("JOB CONTROL", "text-slate-600"),
    "working":      ("IN-PROGRESS", "text-amber-600"),
    "ready_for_fi": ("READY FOR FI", "text-orange-600"),
    "completed":    ("COMPLETED", "text-emerald-600"),
    "invoiced":     ("INVOICED", "text-blue-600"),
    "delivered":    ("DELIVERED", "text-green-600"),
    "cancelled":    ("CANCELLED", "text-rose-600"),
}


def _build_customer_address(customer) -> str:
    if not customer:
        return ""
    parts = []
    if customer.address:
        parts.append(customer.address.strip())
    city_name = getattr(customer.city, "name", None) if customer.city_id else None
    state_name = getattr(customer.state, "name", None) if customer.state_id else None
    tail = []
    if city_name:
        tail.append(city_name)
    if state_name:
        tail.append(state_name)
    label = "-".join(filter(None, [" ".join(tail).strip() or None, (customer.postal_code or "").strip() or None]))
    if label:
        parts.append(label)
    return ", ".join(filter(None, parts))


def render_jobcard_preview_html(job_card) -> str:
    """
    Render the job card as standalone HTML (matching the web preview exactly).

    Returns the complete HTML document that can be converted to PDF.
    """
    from apps.platform.jobcards.pdf_service import _logo_data_url, _media_data_url

    tenant = job_card.tenant

    # ── Tenant — statutory letterhead details (address, phone, email, GSTIN).
    #     PAN and state code aren't stored separately; they're substrings of
    #     the GSTIN itself, per GST's fixed GSTIN format. ────────────────────
    tenant_name = tenant.name if tenant else "AUTOCARE PRO"
    tenant_address = ""
    tenant_phone = ""
    tenant_email = ""
    tenant_gstin = ""
    invoice_settings = None
    if tenant:
        try:
            pii = getattr(tenant, "pii", None)
            if pii:
                tenant_address = pii.address or ""
                if pii.phone_encrypted:
                    tenant_phone = pii.get_phone() or ""
                if pii.email_encrypted:
                    tenant_email = pii.get_email() or ""
                if pii.gstin_encrypted:
                    tenant_gstin = pii.get_gstin() or ""
        except Exception:
            pass
        try:
            invoice_settings = tenant.invoice_settings
        except Exception:
            invoice_settings = None
    tenant_pan, tenant_state_code = derive_pan_and_state_code(tenant_gstin)

    # ── Customer ─────────────────────────────────────────────────────────────
    customer = job_card.customer
    customer_name = customer.full_name if customer else "—"
    customer_address = _build_customer_address(customer)
    customer_gstin = (getattr(customer, "gstin", "") or "").strip() if customer else ""

    # ── Vehicle ──────────────────────────────────────────────────────────────
    vehicle = job_card.vehicle
    vehicle_brand = getattr(vehicle.brand, "name", "") if vehicle and vehicle.brand_id else ""
    vehicle_model_name = getattr(vehicle.vehicle_model, "name", "") if vehicle and vehicle.vehicle_model_id else ""

    # ── Line items — split into Parts / Labour. Each line already carries its
    #     own stored gst_percentage/cgst_amount/sgst_amount (snapshotted by
    #     sync_job_card_line_items at save time), so section totals are exact
    #     sums — no re-derivation or apportionment needed. ───────────────────
    def _stored_cgst_sgst(line):
        return Decimal(str(line.cgst_amount or 0)), Decimal(str(line.sgst_amount or 0))

    lines_ctx = split_lines_into_sections(
        job_card.line_items.order_by("sort_order", "created_at"),
        cgst_sgst_fn=_stored_cgst_sgst,
    )

    # ── Terms & conditions / bank details / QR ────────────────────────────────
    settings_ctx = build_invoice_settings_pdf_context(invoice_settings, _media_data_url)

    status_label, status_color_class = _STATUS_DISPLAY.get(
        job_card.status, (job_card.status.upper(), "text-slate-600")
    )

    context = {
        "tenant_name": tenant_name,
        "tenant_address": tenant_address,
        "tenant_phone": tenant_phone,
        "tenant_email": tenant_email,
        "tenant_gstin": tenant_gstin,
        "tenant_pan": tenant_pan,
        "tenant_state_code": tenant_state_code,
        "logo_data_url": _logo_data_url(job_card.tenant_id),
        "doc_type_label": "JOB CARD",
        "doc_number_label": "JOB CARD NO",
        "doc_number": job_card.jobcard_number,
        "date_created": fmt_date(job_card.created_at),
        "status_label": status_label,
        "status_color_class": status_color_class,
        "customer_name": customer_name,
        "customer_address": customer_address,
        "customer_gstin": customer_gstin,
        "vehicle_reg": vehicle.registration_no if vehicle else "—",
        "vehicle_brand": vehicle_brand,
        "vehicle_model_name": vehicle_model_name,
        "vehicle_vin": vehicle.vin_number if vehicle else "",
        "vehicle_engine_no": vehicle.engine_number if vehicle else "",
        "vehicle_year": vehicle.year if vehicle else "",
        **lines_ctx,
        "grand_total": fmt_money(job_card.total_amount),
        "notes_label": "Notes:-",
        "notes": job_card.notes or "",
        **settings_ctx,
    }

    return render_to_string("jobcards/jobcard_preview.html", context)
