"""Number allocation for proforma invoices and advance receipts.

Same idiom as apps.platform.invoices.service._allocate_invoice_number and
apps.platform.jobcards.utils.allocate_next_jobcard_number: a per-tenant,
per-financial-year counter row, locked with select_for_update() inside the
caller's transaction.atomic() — no gaps, no collisions under concurrent
issuance, no unique-constraint-and-retry needed.
"""
from __future__ import annotations

from django.utils import timezone

from apps.platform.jobcards.models import indian_fy_code
from apps.platform.proforma_invoices.models import AdvanceReceiptFySequence, ProformaInvoiceFySequence

PROFORMA_NUMBER_PREFIX = "PI"
ADVANCE_RECEIPT_NUMBER_PREFIX = "RCPT"


def allocate_next_proforma_number(tenant_id) -> tuple[str, str, int]:
    """Must be called within an active transaction.atomic() context.
    Returns (proforma_number, fy_code, sequence_no)."""
    fy = indian_fy_code(timezone.now().date())
    row, _ = ProformaInvoiceFySequence.objects.select_for_update().get_or_create(
        tenant_id=tenant_id, fy_code=fy, defaults={"last_seq": 0},
    )
    row.last_seq += 1
    row.save(update_fields=["last_seq", "updated_at"])
    proforma_number = f"{PROFORMA_NUMBER_PREFIX}/{fy}/{row.last_seq:05d}"
    return proforma_number, fy, row.last_seq


def allocate_next_advance_receipt_number(tenant_id) -> str:
    """Must be called within an active transaction.atomic() context."""
    fy = indian_fy_code(timezone.now().date())
    row, _ = AdvanceReceiptFySequence.objects.select_for_update().get_or_create(
        tenant_id=tenant_id, fy_code=fy, defaults={"last_seq": 0},
    )
    row.last_seq += 1
    row.save(update_fields=["last_seq", "updated_at"])
    return f"{ADVANCE_RECEIPT_NUMBER_PREFIX}/{fy}/{row.last_seq:05d}"
