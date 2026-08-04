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


def allocate_cents_by_weight(weights: list[int], total_cents: int) -> list[int]:
    """
    Split integer cents across rows proportional to weights (same total as `total_cents`).
    Mirrors `allocateCentsByWeight` in the job card editor's live preview (frontend) exactly,
    so saved totals always match what the tenant saw before saving.
    """
    wsum = sum(weights)
    if wsum <= 0 or total_cents <= 0:
        return [0] * len(weights)
    raw = [(w / wsum) * total_cents for w in weights]
    base = [int(x) for x in raw]
    rem = total_cents - sum(base)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)
    for k in range(rem):
        base[order[k % len(order)]] += 1
    return base


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
    """
    Replace all lines on a job card from payload (normalized rows).

    Each line's catalog GST% is snapshotted at sync time (0 for custom lines with no
    catalog match), and its CGST/SGST contribution is computed and stored using the same
    per-line taxable-allocation algorithm as the job card editor's live preview: the header
    taxable amount (subtotal − discount) is split across lines by weight (each line's share
    of the subtotal), then each line's own GST% is applied to its allocated taxable share,
    rounded per line, then split half/half into CGST/SGST. This keeps the persisted totals
    consistent with what the tenant saw in the preview before saving.
    """
    JobCardLineItem.objects.filter(job_card=job_card).delete()

    rows = []
    for idx, raw in enumerate(items_data or []):
        if not isinstance(raw, dict):
            continue
        sort_order = int(raw.get("sort_order", idx))
        sid, si_obj = _resolve_line_service_item(raw.get("service_item"), tenant_id)
        service_type = raw.get("service_type")
        if service_type not in dict(JobCardLineItem.SERVICE_TYPE_CHOICES):
            service_type = si_obj.service_type if si_obj else JobCardLineItem.SERVICE_TYPE_LABOUR
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

    discount = Decimal(str(job_card.discount_amount or 0))
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
        objs.append(JobCardLineItem(
            job_card=job_card,
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
    JobCardLineItem.objects.bulk_create(objs)


def refresh_job_card_totals(job_card: JobCard) -> None:
    """
    Recompute header subtotal/tax/total from persisted line items, header discount, and shop
    fees. CGST/SGST are summed directly from each line's own stored amount (set by
    `sync_job_card_line_items`) rather than re-derived from a flat rate, so the header total
    reflects each line's actual catalog GST%.
    """
    job_card.refresh_from_db(fields=["discount_amount", "shop_fees"])
    items = list(job_card.line_items.all())

    subtotal = sum((li.line_total for li in items), Decimal("0"))
    discount = Decimal(str(job_card.discount_amount or 0))
    if discount < 0:
        discount = Decimal("0")
    taxable = subtotal - discount
    if taxable < 0:
        taxable = Decimal("0")

    cgst = sum((li.cgst_amount for li in items), Decimal("0"))
    sgst = sum((li.sgst_amount for li in items), Decimal("0"))
    igst = Decimal("0")

    shop = Decimal(str(job_card.shop_fees or 0))
    if shop < 0:
        shop = Decimal("0")
    total = (taxable + cgst + sgst + igst + shop).quantize(Decimal("0.01"))

    JobCard.objects.filter(pk=job_card.pk).update(
        subtotal=subtotal.quantize(Decimal("0.01")),
        discount_amount=discount.quantize(Decimal("0.01")),
        cgst_amount=cgst.quantize(Decimal("0.01")),
        sgst_amount=sgst.quantize(Decimal("0.01")),
        igst_amount=igst,
        total_amount=total,
    )
