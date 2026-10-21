"""
Proforma invoice + advance receipt PDF rendering, via Playwright.

The proforma invoice renders the SAME shared "black-bar" template used for
job cards/invoices/quotations (`jobcards/templates/jobcards/jobcard_preview.html`),
parameterized by doc_type_label — so it stays pixel-identical to the other
three document types by construction, and the mandatory "not a tax invoice"
disclaimer is satisfied simply by what doc_type_label says (that label is
rendered as the template's bold top banner), with zero template changes.

The advance receipt is a genuinely different, much simpler document (no
multi-line GST table) and gets its own small template.
"""
from __future__ import annotations

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
from apps.platform.invoices.models import Invoice
from apps.platform.jobcards.pdf_service import _logo_data_url, _media_data_url

# Re-exported for pdf_service.py — the Playwright generation wrapper is
# fully generic (takes arbitrary html_content), so it's reused directly
# rather than duplicated.
from apps.platform.invoices.pdf_generator import generate_invoice_pdf  # noqa: F401


def _tenant_context(tenant) -> dict:
    tenant_name = tenant.name if tenant else "AUTOCARE PRO"
    tenant_address = ""
    tenant_gstin = ""
    tenant_phone = ""
    tenant_alternate_phone = ""
    tenant_email = ""
    invoice_settings = None
    if tenant:
        try:
            pii = getattr(tenant, "pii", None)
            if pii:
                tenant_address = pii.address or ""
                if pii.gstin_encrypted:
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
    return {
        "tenant_name": tenant_name,
        "tenant_address": tenant_address,
        "tenant_phone": tenant_phone,
        "tenant_alternate_phone": tenant_alternate_phone,
        "tenant_email": tenant_email,
        "tenant_gstin": tenant_gstin,
        "tenant_pan": tenant_pan,
        "tenant_state_code": tenant_state_code,
        "tenant_state_name": state_name_from_code(tenant_state_code),
        "invoice_settings": invoice_settings,
    }


def render_proforma_invoice_preview_html(proforma) -> str:
    """Render the proforma invoice as standalone HTML (same design as invoices/
    job cards/quotations). Returns the complete HTML document."""
    tenant = proforma.tenant
    tctx = _tenant_context(tenant)
    invoice_settings = tctx.pop("invoice_settings")

    customer = proforma.customer
    customer_name = customer.full_name if customer else "—"
    customer_address = getattr(customer, "address", "") or "" if customer else ""
    customer_phone = getattr(customer, "phone", "") or "" if customer else ""
    customer_gstin = getattr(customer, "gstin", "") or "" if customer else ""

    vehicle = proforma.vehicle
    vehicle_brand = getattr(getattr(vehicle, "brand", None), "name", "") if vehicle else ""
    vehicle_model_name = getattr(getattr(vehicle, "vehicle_model", None), "name", "") if vehicle else ""

    def _stored_cgst_sgst(line):
        return Decimal(str(line.cgst_amount or 0)), Decimal(str(line.sgst_amount or 0))

    lines_ctx = split_lines_into_sections(
        proforma.line_items.order_by("sort_order", "created_at"),
        cgst_sgst_fn=_stored_cgst_sgst,
    )

    settings_ctx = build_invoice_settings_pdf_context(invoice_settings, _media_data_url)
    rounding_ctx = round_off_display_ctx(proforma.total_amount, proforma.round_off_amount)

    context = {
        **tctx,
        "logo_data_url": _logo_data_url(proforma.tenant_id),
        "doc_type_label": "PROFORMA INVOICE — NOT A TAX INVOICE",
        "doc_number_label": "PROFORMA NUMBER",
        "doc_number": f"{proforma.proforma_number} (v{proforma.version})",
        "date_created": fmt_date(proforma.issue_date),
        "customer_name": customer_name,
        "customer_address": customer_address,
        "customer_gstin": customer_gstin,
        "customer_phone": customer_phone,
        "vehicle_reg": getattr(vehicle, "registration_no", "") or "—",
        "vehicle_brand": vehicle_brand,
        "vehicle_model_name": vehicle_model_name,
        "vehicle_vin": getattr(vehicle, "vin_number", "") or "",
        "vehicle_engine_no": getattr(vehicle, "engine_number", "") or "",
        "vehicle_year": getattr(vehicle, "year", None),
        "vehicle_odo": "",
        **lines_ctx,
        "grand_total": fmt_money(proforma.total_amount),
        "discount_amount_display": fmt_money(proforma.discount_amount) if proforma.discount_amount else None,
        "shop_fees_display": fmt_money(proforma.shop_fees) if proforma.shop_fees else None,
        **rounding_ctx,
        "total_in_words": amount_in_words(proforma.total_amount),
        "show_gst": proforma.invoice_type == Invoice.INVOICE_TYPE_GST,
        "notes_label": "Notes:-",
        "notes": proforma.customer_notes or "",
        "is_cancelled": proforma.status == proforma.STATUS_CANCELLED,
        "cancelled_at": fmt_date(proforma.cancelled_at) if proforma.cancelled_at else "",
        "cancellation_reason": proforma.cancellation_reason or "",
        "status_banner_label": "CANCELLED",
        "terms_new_page": False,
        "bank_new_page": False,
        **settings_ctx,
        # Terms & conditions on a proforma intentionally omit the tenant's
        # usual invoice T&C paragraph if it references statutory invoice
        # language — the proforma's own terms_and_conditions field (editable
        # per-document, defaulted from the tenant's template at generation
        # time) is shown instead via the notes/customer-facing text above;
        # the settings_ctx bank/QR block above is still shown since an
        # advance payment against this estimate would go to the same account.
    }
    return render_to_string("jobcards/jobcard_preview.html", context)


def render_advance_receipt_html(payment) -> str:
    """Render the advance payment receipt as standalone HTML — a plain
    amount-received record, deliberately with NO CGST/SGST/IGST breakdown
    (see apps.platform.proforma_invoices.service module docstring and the
    implementation plan's CA-review note: whether GST is due on an advance,
    and what statutory particulars a receipt voucher must carry, are open
    compliance questions this implementation does not resolve)."""
    proforma = payment.proforma_invoice
    tenant = proforma.tenant
    tctx = _tenant_context(tenant)
    tctx.pop("invoice_settings", None)

    customer = proforma.customer
    vehicle = proforma.vehicle

    received_by_name = ""
    if payment.received_by_id:
        try:
            received_by_name = payment.received_by.pii.get_full_name() or ""
        except Exception:
            received_by_name = ""

    context = {
        **tctx,
        "logo_data_url": _logo_data_url(proforma.tenant_id),
        "receipt_number": payment.receipt_number,
        "receipt_date": fmt_date(payment.created_at),
        "customer_name": customer.full_name if customer else "—",
        "customer_phone": getattr(customer, "phone", "") or "" if customer else "",
        "vehicle_label": f"{getattr(vehicle, 'brand', None) and vehicle.brand.name or ''} "
                          f"{getattr(vehicle, 'vehicle_model', None) and vehicle.vehicle_model.name or ''}".strip() or "—",
        "vehicle_reg": getattr(vehicle, "registration_no", "") or "—",
        "jobcard_number": proforma.job_card.jobcard_number,
        "proforma_number": f"{proforma.proforma_number} (v{proforma.version})",
        "amount_display": fmt_money(payment.amount),
        "amount_in_words": amount_in_words(payment.amount),
        "payment_mode_display": payment.get_payment_mode_display(),
        "payment_reference": payment.payment_reference or "—",
        "received_by_name": received_by_name or "—",
        "remarks": payment.remarks or "",
    }
    return render_to_string("proforma_invoices/advance_receipt.html", context)
