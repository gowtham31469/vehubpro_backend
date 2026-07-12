from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.platform.jobcards.models import JobCard, JobCardFySequence, JobCardLineItem, indian_fy_code
from apps.platform.services.models import ServiceItem


def allocate_next_jobcard_number(tenant_id) -> str:
    """Thread-safe next number: JC-{FY}-{5d} per PRD."""
    fy = indian_fy_code(timezone.now().date())
    with transaction.atomic():
        row, _ = JobCardFySequence.objects.select_for_update().get_or_create(
            tenant_id=tenant_id,
            fy_code=fy,
            defaults={"last_seq": 0},
        )
        row.last_seq += 1
        row.save(update_fields=["last_seq", "updated_at"])
        return f"JC/{fy}/{row.last_seq:05d}"


def extended_line_amount(line) -> Decimal:
    """Pre-tax extended amount for one line (dict with PRD/JSON keys or ORM row with line_total)."""
    if line is None:
        return Decimal("0")
    if hasattr(line, "line_total"):
        return Decimal(str(line.line_total)).quantize(Decimal("0.01"))
    if not isinstance(line, dict):
        return Decimal("0")
    if line.get("line_total") is not None:
        return Decimal(str(line["line_total"])).quantize(Decimal("0.01"))
    qty = Decimal(str(line.get("quantity", line.get("qty", 1))))
    price = Decimal(str(line.get("unit_price", line.get("base_price", 0))))
    disc = Decimal(str(line.get("discount_amount", line.get("line_discount", 0))))
    if disc < 0:
        disc = Decimal("0")
    net = (qty * price) - disc
    if net < 0:
        net = Decimal("0")
    return net.quantize(Decimal("0.01"))


def compute_line_amounts(services_items: list | None, discount_amount) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    """Subtotal from line extended amounts, 9+9 CGST/SGST on (subtotal - header discount)."""
    subtotal = Decimal("0")
    for line in services_items or []:
        if line is None:
            continue
        subtotal += extended_line_amount(line)

    discount = Decimal(str(discount_amount or 0))
    if discount < 0:
        discount = Decimal("0")
    taxable = subtotal - discount
    if taxable < 0:
        taxable = Decimal("0")

    cgst = (taxable * Decimal("0.09")).quantize(Decimal("0.01"))
    sgst = (taxable * Decimal("0.09")).quantize(Decimal("0.01"))
    igst = Decimal("0")
    total = (taxable + cgst + sgst + igst).quantize(Decimal("0.01"))
    return subtotal.quantize(Decimal("0.01")), discount, cgst, sgst, igst, total


def _resolve_line_service_item(raw_si, tenant_id):
    """
    `items_data` may come from DRF validated_data where `service_item` is a ServiceItem
    instance. Never pass a model into filter(pk=...) on a UUID PK or into service_item_id=.
    """
    if raw_si in (None, ""):
        return None, None
    if isinstance(raw_si, ServiceItem):
        if str(raw_si.tenant_id) != str(tenant_id):
            return None, None
        return raw_si.pk, raw_si
    si_obj = ServiceItem.objects.filter(pk=raw_si, tenant_id=tenant_id).first()
    return (si_obj.pk if si_obj else None), si_obj


def sync_job_card_line_items(job_card: JobCard, items_data: list | None, tenant_id) -> None:
    """Replace all lines on a job card from payload (normalized rows)."""
    JobCardLineItem.objects.filter(job_card=job_card).delete()
    for idx, raw in enumerate(items_data or []):
        if not isinstance(raw, dict):
            continue
        sort_order = int(raw.get("sort_order", idx))
        sid, si_obj = _resolve_line_service_item(raw.get("service_item"), tenant_id)
        desc = (raw.get("description") or "").strip()
        qty = Decimal(str(raw.get("quantity", 1)))
        up = Decimal(str(raw.get("unit_price", 0)))
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
        JobCardLineItem.objects.create(
            job_card=job_card,
            sort_order=sort_order,
            service_item_id=sid,
            description=desc[:500],
            detail_text=detail,
            quantity=qty,
            unit_price=up,
            discount_amount=da,
            line_total=lt,
        )


def refresh_job_card_totals(job_card: JobCard) -> None:
    """Recompute header subtotal/tax/total from persisted line items, header discount, and shop fees."""
    job_card.refresh_from_db(fields=["discount_amount", "shop_fees"])
    items = list(job_card.line_items.all().order_by("sort_order", "id"))
    lines = [{"line_total": li.line_total} for li in items]
    sub, disc, cgst, sgst, igst, base_total = compute_line_amounts(lines, job_card.discount_amount)
    shop = Decimal(str(job_card.shop_fees or 0))
    if shop < 0:
        shop = Decimal("0")
    total = (base_total + shop).quantize(Decimal("0.01"))
    JobCard.objects.filter(pk=job_card.pk).update(
        subtotal=sub,
        discount_amount=disc,
        cgst_amount=cgst,
        sgst_amount=sgst,
        igst_amount=igst,
        total_amount=total,
    )
