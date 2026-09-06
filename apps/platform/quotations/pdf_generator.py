"""
Quotation PDF generation using Playwright.

Renders the SAME shared "black-bar" template used for job cards and invoices
(`jobcards/templates/jobcards/jobcard_preview.html`) so all three document
types stay pixel-identical, parameterized by doc_type_label/doc_number_label/
valid_until_display/status_banner_label context keys — "QUOTATION" instead of
"JOB CARD"/"INVOICE", quotation number (with version) instead of job card/
invoice number, and the quotation's own lifecycle status instead of an
invoice cancellation.
"""
import asyncio
import logging
from decimal import Decimal

from django.template.loader import render_to_string

from apps.common.utils.pdf_documents import (
    amount_in_words,
    build_invoice_settings_pdf_context,
    derive_pan_and_state_code,
    fmt_date,
    fmt_money,
    round_off_display_ctx,
    split_lines_into_sections,
    state_name_from_code,
)
from apps.platform.quotations.models import Quotation

logger = logging.getLogger(__name__)

_STATUS_BANNER_LABELS = {
    Quotation.STATUS_REJECTED: "REJECTED",
    Quotation.STATUS_EXPIRED: "EXPIRED",
    Quotation.STATUS_CANCELLED: "CANCELLED",
}
_STATUS_BANNER_AT_FIELD = {
    Quotation.STATUS_REJECTED: "rejected_at",
    Quotation.STATUS_EXPIRED: None,
    Quotation.STATUS_CANCELLED: "cancelled_at",
}
_STATUS_BANNER_REASON_FIELD = {
    Quotation.STATUS_REJECTED: "rejection_reason",
    Quotation.STATUS_EXPIRED: None,
    Quotation.STATUS_CANCELLED: "cancellation_reason",
}


async def generate_quotation_pdf_async(html_content: str) -> bytes:
    """Generate PDF from HTML using Playwright headless browser."""
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
                margin={"top": "6mm", "right": "16mm", "bottom": "14mm", "left": "16mm"},
                print_background=True,
            )
            return pdf_bytes
        finally:
            await browser.close()


def generate_quotation_pdf(html_content: str) -> bytes:
    """Synchronous wrapper for async PDF generation."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(generate_quotation_pdf_async(html_content))
    finally:
        loop.close()


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


def render_quotation_preview_html(quotation: Quotation) -> str:
    """
    Render the quotation as standalone HTML (matching the job card/invoice
    preview design exactly).
    """
    from apps.platform.jobcards.pdf_service import _logo_data_url, _media_data_url

    tenant = quotation.tenant

    tenant_name = tenant.name if tenant else "AUTOCARE PRO"
    tenant_address = ""
    tenant_phone = ""
    tenant_alternate_phone = ""
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
                if pii.alternate_phone_encrypted:
                    tenant_alternate_phone = pii.get_alternate_phone() or ""
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
    tenant_state_name = state_name_from_code(tenant_state_code)

    customer = quotation.customer
    customer_name = customer.full_name if customer else "—"
    customer_address = _build_customer_address(customer)
    customer_gstin = (getattr(customer, "gstin", "") or "").strip() if customer else ""
    customer_phone = (getattr(customer, "phone", "") or "").strip() if customer else ""

    vehicle = quotation.vehicle
    vehicle_brand = getattr(vehicle.brand, "name", "") if vehicle and vehicle.brand_id else ""
    vehicle_model_name = getattr(vehicle.vehicle_model, "name", "") if vehicle and vehicle.vehicle_model_id else ""

    def _stored_cgst_sgst(line):
        return Decimal(str(line.cgst_amount or 0)), Decimal(str(line.sgst_amount or 0))

    lines_ctx = split_lines_into_sections(
        quotation.line_items.order_by("sort_order", "created_at"),
        cgst_sgst_fn=_stored_cgst_sgst,
    )

    settings_ctx = build_invoice_settings_pdf_context(invoice_settings, _media_data_url)
    # Terms shown on the quotation default to the tenant's standard terms unless
    # this quotation carries its own override.
    if quotation.terms_and_conditions:
        settings_ctx["terms_paragraphs"] = [
            p.strip() for p in quotation.terms_and_conditions.replace("\r\n", "\n").split("\n\n") if p.strip()
        ]

    rounding_ctx = round_off_display_ctx(quotation.total_amount, quotation.round_off_amount)

    status_banner_label = _STATUS_BANNER_LABELS.get(quotation.status)
    banner_at_field = _STATUS_BANNER_AT_FIELD.get(quotation.status)
    banner_reason_field = _STATUS_BANNER_REASON_FIELD.get(quotation.status)

    context = {
        "tenant_name": tenant_name,
        "tenant_address": tenant_address,
        "tenant_phone": tenant_phone,
        "tenant_alternate_phone": tenant_alternate_phone,
        "tenant_email": tenant_email,
        "tenant_gstin": tenant_gstin,
        "tenant_pan": tenant_pan,
        "tenant_state_code": tenant_state_code,
        "tenant_state_name": tenant_state_name,
        "logo_data_url": _logo_data_url(quotation.tenant_id),
        "doc_type_label": "QUOTATION",
        "doc_number_label": "QUOTATION NUMBER",
        "doc_number": f"{quotation.quotation_number} (v{quotation.version})",
        "date_created": fmt_date(quotation.quotation_date),
        "valid_until_display": fmt_date(quotation.valid_until) if quotation.valid_until else None,
        "customer_name": customer_name,
        "customer_address": customer_address,
        "customer_gstin": customer_gstin,
        "customer_phone": customer_phone,
        "vehicle_reg": vehicle.registration_no if vehicle else "—",
        "vehicle_brand": vehicle_brand,
        "vehicle_model_name": vehicle_model_name,
        "vehicle_vin": vehicle.vin_number if vehicle else "",
        "vehicle_engine_no": vehicle.engine_number if vehicle else "",
        "vehicle_year": vehicle.year if vehicle else "",
        "vehicle_odo": "",
        **lines_ctx,
        "grand_total": fmt_money(quotation.total_amount),
        "discount_amount_display": fmt_money(quotation.discount_amount) if quotation.discount_amount else None,
        "shop_fees_display": None,
        **rounding_ctx,
        "total_in_words": amount_in_words(quotation.total_amount),
        "show_gst": True,
        "notes_label": "Notes:-",
        "notes": quotation.notes or "",
        # Repurpose the shared "cancelled" banner block for any terminal, non-
        # convertible quotation status (rejected/expired/cancelled) — approved/
        # converted/sent/draft quotations show no banner.
        "is_cancelled": bool(status_banner_label),
        "status_banner_label": status_banner_label,
        "cancelled_at": fmt_date(getattr(quotation, banner_at_field)) if banner_at_field and getattr(quotation, banner_at_field) else "",
        "cancellation_reason": (getattr(quotation, banner_reason_field) or "") if banner_reason_field else "",
        **settings_ctx,
    }

    return render_to_string("jobcards/jobcard_preview.html", context)
