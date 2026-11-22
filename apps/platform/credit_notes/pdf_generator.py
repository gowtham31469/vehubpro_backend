"""
Credit Note PDF generation using Playwright.

Renders the SAME shared "black-bar" template used for job cards/invoices/
quotations/proforma invoices (`jobcards/templates/jobcards/jobcard_preview.html`),
parameterized via doc_type_label/doc_number_label/notes_label — "CREDIT NOTE"
instead of "INVOICE", the credit note number instead of the invoice number,
and the credit reason in the notes slot. A new, additive `reference_display`
context key (the template already supports this kind of optional extra line —
see `valid_until_display`) carries "Against Invoice: INV/.../..." so the
credit note's own statutory link back to the original tax invoice is visible
on the document, without touching the shared template for every other doc
type that doesn't pass it.
"""
import asyncio
import logging

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

logger = logging.getLogger(__name__)


async def generate_credit_note_pdf_async(html_content: str) -> bytes:
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


def generate_credit_note_pdf(html_content: str) -> bytes:
    """Synchronous wrapper for async PDF generation."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(generate_credit_note_pdf_async(html_content))
    finally:
        loop.close()


def render_credit_note_preview_html(credit_note) -> str:
    """Render the credit note as standalone HTML (same shared template as invoices)."""
    from apps.platform.jobcards.pdf_service import _logo_data_url, _media_data_url

    invoice = credit_note.invoice
    tenant = invoice.tenant

    tenant_name = invoice.tenant_name_snapshot or (tenant.name if tenant else "AUTOCARE PRO")
    tenant_address = invoice.tenant_address_snapshot or ""
    tenant_gstin = invoice.tenant_gstin_snapshot or ""
    tenant_phone = ""
    tenant_alternate_phone = ""
    tenant_email = ""
    invoice_settings = None
    if tenant:
        try:
            pii = getattr(tenant, "pii", None)
            if pii:
                if not tenant_address:
                    tenant_address = pii.address or ""
                if not tenant_gstin and pii.gstin_encrypted:
                    tenant_gstin = pii.get_gstin() or ""
                if pii.phone_encrypted:
                    tenant_phone = pii.get_phone() or ""
                if pii.alternate_phone_encrypted:
                    tenant_alternate_phone = pii.get_alternate_phone() or ""
                if pii.email_encrypted:
                    tenant_email = pii.get_email() or ""
        except Exception:
            pass
        try:
            invoice_settings = tenant.invoice_settings
        except Exception:
            invoice_settings = None
    tenant_pan, tenant_state_code = derive_pan_and_state_code(tenant_gstin)
    tenant_state_name = state_name_from_code(tenant_state_code)

    if invoice.is_pii_erased:
        customer_name = "[ERASED]"
        customer_address = "[ERASED]"
        customer_phone = "[ERASED]"
    else:
        try:
            customer_name = invoice.get_customer_name() or "—"
        except Exception:
            customer_name = "—"
        try:
            customer_address = invoice.get_customer_address() or ""
        except Exception:
            customer_address = ""
        try:
            customer_phone = invoice.get_customer_phone() or ""
        except Exception:
            customer_phone = ""
    customer_gstin = invoice.customer_gstin or ""

    def _stored_cgst_sgst(line):
        return line.cgst_amount or 0, line.sgst_amount or 0

    lines_ctx = split_lines_into_sections(
        credit_note.line_items.order_by("sort_order", "created_at"),
        cgst_sgst_fn=_stored_cgst_sgst,
    )

    settings_ctx = build_invoice_settings_pdf_context(invoice_settings, _media_data_url)
    rounding_ctx = round_off_display_ctx(credit_note.total_amount, credit_note.round_off_amount)

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
        "logo_data_url": _logo_data_url(invoice.tenant_id),
        "doc_type_label": "CREDIT NOTE",
        "doc_number_label": "CREDIT NOTE NUMBER",
        "doc_number": credit_note.credit_note_number,
        "date_created": fmt_date(credit_note.created_at),
        "reference_display": (
            f"Against Invoice: {invoice.invoice_number} dated {fmt_date(invoice.created_at)}"
        ),
        "customer_name": customer_name,
        "customer_address": customer_address,
        "customer_gstin": customer_gstin,
        "customer_phone": customer_phone,
        "vehicle_reg": invoice.vehicle_registration_no_snapshot or "—",
        "vehicle_brand": invoice.vehicle_brand_snapshot,
        "vehicle_model_name": invoice.vehicle_model_snapshot,
        "vehicle_vin": invoice.vehicle_vin_snapshot,
        "vehicle_engine_no": invoice.vehicle_engine_no_snapshot,
        "vehicle_year": invoice.vehicle_year_snapshot,
        "vehicle_odo": f"{invoice.vehicle_odometer_snapshot:,} km" if invoice.vehicle_odometer_snapshot else "",
        **lines_ctx,
        "grand_total": fmt_money(credit_note.total_amount),
        "discount_amount_display": None,
        "shop_fees_display": None,
        **rounding_ctx,
        "total_in_words": amount_in_words(credit_note.total_amount),
        "show_gst": invoice.invoice_type == invoice.INVOICE_TYPE_GST,
        "notes_label": "Reason for Credit:-",
        "notes": credit_note.reason or "",
        "is_cancelled": credit_note.status == credit_note.STATUS_CANCELLED,
        "status_banner_label": "CANCELLED",
        "cancelled_at": fmt_date(credit_note.cancelled_at) if credit_note.cancelled_at else "",
        "cancellation_reason": credit_note.cancellation_reason or "",
        "terms_new_page": False,
        "bank_new_page": False,
        **settings_ctx,
    }

    return render_to_string("jobcards/jobcard_preview.html", context)
