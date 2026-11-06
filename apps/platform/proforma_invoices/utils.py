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
from apps.platform.proforma_invoices.models import AdvancePayment, AdvanceReceiptFySequence, ProformaInvoiceFySequence

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


def family_advance_payments_queryset(proforma):
    """
    All AdvancePayment rows across every version of this proforma's family
    (same tenant + proforma_number) — not just the one version instance
    passed in.

    create_revision() starts a NEW ProformaInvoice row for v2, v3, etc., each
    with its own id; AdvancePayment.proforma_invoice points at whichever
    specific version was active when the money was recorded. Without this,
    an advance collected against v1 silently "disappears" once a revision
    exists — invisible on v2's page, AND never credited at conversion time
    (ProformaInvoiceService.convert_to_invoice only ever runs on the latest
    version) — even though it's the same real money against the same
    underlying estimate. Querying by proforma_number instead of the single
    row's id keeps it visible and creditable regardless of which version is
    currently "latest".
    """
    return AdvancePayment.objects.filter(
        proforma_invoice__tenant_id=proforma.tenant_id,
        proforma_invoice__proforma_number=proforma.proforma_number,
    )


def job_card_advance_payments_queryset(job_card):
    """
    Every AdvancePayment tied to this job card, across every proforma family
    that was ever generated from it — AdvancePayment.job_card is a
    denormalized copy of proforma_invoice.job_card_id kept exactly for this
    kind of query. Used when generating an invoice directly from the job
    card (bypassing any specific proforma's "Convert to Invoice"), so money
    already collected still gets credited regardless of which proforma
    family or version it was recorded against.
    """
    return AdvancePayment.objects.filter(job_card_id=job_card.pk)
