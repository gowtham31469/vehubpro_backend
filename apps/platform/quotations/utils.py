from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.common.utils.pdf_documents import compute_round_off
from apps.platform.jobcards.models import indian_fy_code
from apps.platform.jobcards.utils import allocate_cents_by_weight, extended_line_amount
from apps.platform.quotations.models import Quotation, QuotationFySequence, QuotationLineItem
from apps.platform.services.models import ServiceItem


def allocate_next_quotation_number(tenant_id) -> str:
    """
    Thread-safe next number: QT/{FY}/{5d}, mirroring allocate_next_jobcard_number.
    Only called once per quotation *family* (i.e. when creating version 1) — a
    revision reuses its parent's quotation_number instead of allocating a new one.
    """
    fy = indian_fy_code(timezone.now().date())
    with transaction.atomic():
        row, _ = QuotationFySequence.objects.select_for_update().get_or_create(
            tenant_id=tenant_id,
            fy_code=fy,
            defaults={"last_seq": 0},
        )
        row.last_seq += 1
        row.save(update_fields=["last_seq", "updated_at"])
        return f"QT/{fy}/{row.last_seq:05d}"


def _resolve_line_service_item(raw_si, tenant_id):
    """Mirrors apps.platform.jobcards.utils._resolve_line_service_item."""
    if raw_si in (None, ""):
        return None, None
    if isinstance(raw_si, ServiceItem):
        if str(raw_si.tenant_id) != str(tenant_id):
            return None, None
        return raw_si.pk, raw_si
    si_obj = ServiceItem.objects.filter(pk=raw_si, tenant_id=tenant_id).first()
    return (si_obj.pk if si_obj else None), si_obj


def sync_quotation_line_items(quotation: Quotation, items_data: list | None, tenant_id) -> None:
    """
    Replace all lines on a quotation from payload — identical algorithm to
    sync_job_card_line_items (per-line catalog GST% snapshot + cent-weighted
    taxable allocation), so a quotation converted to a job card produces the
    same totals it displayed. Only ever called while the quotation is DRAFT
    (enforced by QuotationSerializer/QuotationService) — once SENT, a line's
    unit_price/gst_percentage snapshot is frozen for good, satisfying the
    "never recompute from the current catalog price" requirement.
    """
    QuotationLineItem.objects.filter(quotation=quotation).delete()

    rows = []
    for idx, raw in enumerate(items_data or []):
        if not isinstance(raw, dict):
            continue
        sort_order = int(raw.get("sort_order", idx))
        sid, si_obj = _resolve_line_service_item(raw.get("service_item"), tenant_id)
        service_type = raw.get("service_type")
        if service_type not in dict(QuotationLineItem.SERVICE_TYPE_CHOICES):
            service_type = si_obj.service_type if si_obj else QuotationLineItem.SERVICE_TYPE_LABOUR
        desc = (raw.get("description") or "").strip()
        qty = Decimal(str(raw.get("quantity", 1)))
        up = Decimal(str(raw.get("unit_price", si_obj.base_price if si_obj else 0)))
        da = Decimal(str(raw.get("discount_amount", 0)))
        if da < 0:
            da = Decimal("0")
        if si_obj and not desc:
            desc = si_obj.name
        if not desc:
            desc = "—"
        lt = extended_line_amount({"quantity": qty, "unit_price": up, "discount_amount": da})
        detail = (raw.get("detail_text") or "").strip()[:500]
        if not detail and si_obj and si_obj.description:
            detail = str(si_obj.description).strip()[:500]
        gst_pct = (
            Decimal(str(si_obj.gst_percentage))
            if si_obj and si_obj.gst_percentage is not None
            else Decimal("0")
        )
        rows.append({
            "sort_order": sort_order,
            "service_item_id": sid,
            "service_type": service_type,
            "description": desc[:500],
            "detail_text": detail,
            "quantity": qty,
            "unit_price": up,
            "discount_amount": da,
            "line_total": lt,
            "gst_percentage": gst_pct,
        })

    if not rows:
        return

    discount = Decimal(str(quotation.discount_amount or 0))
    if discount < 0:
        discount = Decimal("0")
    subtotal = sum((r["line_total"] for r in rows), Decimal("0"))
    taxable = subtotal - discount
    if taxable < 0:
        taxable = Decimal("0")

    weight_cents = [int((r["line_total"] * 100).to_integral_value()) for r in rows]
    taxable_cents = int((taxable * 100).to_integral_value())
    line_taxable_cents = allocate_cents_by_weight(weight_cents, taxable_cents)

    objs = []
    for r, taxable_c in zip(rows, line_taxable_cents):
        base = Decimal(taxable_c) / Decimal("100")
        total_line_tax = (base * r["gst_percentage"] / Decimal("100")).quantize(Decimal("0.01"))
        half = (total_line_tax / 2).quantize(Decimal("0.01"))
        cgst = half
        sgst = (total_line_tax - half).quantize(Decimal("0.01"))
        objs.append(QuotationLineItem(
            quotation=quotation,
            sort_order=r["sort_order"],
            service_item_id=r["service_item_id"],
            service_type=r["service_type"],
            description=r["description"],
            detail_text=r["detail_text"],
            quantity=r["quantity"],
            unit_price=r["unit_price"],
            discount_amount=r["discount_amount"],
            line_total=r["line_total"],
            gst_percentage=r["gst_percentage"],
            cgst_amount=cgst,
            sgst_amount=sgst,
        ))
    QuotationLineItem.objects.bulk_create(objs)


def refresh_quotation_totals(quotation: Quotation) -> None:
    """
    Recompute header subtotal/taxable/tax/round_off/total from persisted line
    items + header discount_amount. Mirrors refresh_job_card_totals (no
    shop_fees concept on quotations — that's a job-card-specific post-tax fee).
    """
    quotation.refresh_from_db(fields=["discount_amount"])
    items = list(quotation.line_items.all())

    subtotal = sum((li.line_total for li in items), Decimal("0"))
    discount = Decimal(str(quotation.discount_amount or 0))
    if discount < 0:
        discount = Decimal("0")
    taxable = subtotal - discount
    if taxable < 0:
        taxable = Decimal("0")

    cgst = sum((li.cgst_amount for li in items), Decimal("0"))
    sgst = sum((li.sgst_amount for li in items), Decimal("0"))
    igst = Decimal("0")

    exact_total = (taxable + cgst + sgst + igst).quantize(Decimal("0.01"))
    rounded_total, round_off = compute_round_off(exact_total)

    Quotation.objects.filter(pk=quotation.pk).update(
        subtotal=subtotal.quantize(Decimal("0.01")),
        discount_amount=discount.quantize(Decimal("0.01")),
        taxable_amount=taxable.quantize(Decimal("0.01")),
        cgst_amount=cgst.quantize(Decimal("0.01")),
        sgst_amount=sgst.quantize(Decimal("0.01")),
        igst_amount=igst,
        round_off_amount=round_off,
        total_amount=rounded_total,
    )
