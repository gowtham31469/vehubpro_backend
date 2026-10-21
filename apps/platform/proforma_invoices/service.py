"""
ProformaInvoiceService + AdvancePaymentService — business logic for the
Proforma Invoice / Advance Payment workflow.

Design principles (mirrors apps.platform.quotations.service.QuotationService
and apps.platform.invoices.service.InvoiceService)
-------------------------------------------------------------------------
1. Atomicity: every state transition is @transaction.atomic. Conversion in
   particular wraps the real Invoice creation + advance-credit loop in one
   outer transaction — Django transactions nest via savepoints, so calling
   the already-@transaction.atomic InvoiceService.generate() from inside
   convert_to_invoice() participates correctly in the same all-or-nothing
   transaction.
2. Snapshot, never recompute: a ProformaInvoice's totals/line items are
   copied verbatim from the job card at generate()/create_revision() time,
   exactly like InvoiceService.generate() — this app has no GST-calculation
   engine of its own (that lives in apps.platform.jobcards.utils and is
   deliberately not duplicated here).
3. Revisions never mutate an issued proforma: create_revision() always
   inserts a new sibling row (version N+1), flips is_latest atomically, and
   leaves the previous version fully intact for audit — same mechanism as
   Quotation, except the new version RE-SNAPSHOTS from the job card's
   CURRENT state rather than copying the old version's own lines (see its
   docstring below for why).
4. Idempotent conversion: convert_to_invoice() locks the proforma row
   (select_for_update) and checks status/invoice_id before doing anything,
   so a double-click or a network-retry can never create two invoices from
   one proforma.
5. The existing InvoiceService/JobCard code is never modified by this
   service — conversion calls InvoiceService.generate() and
   InvoiceService.record_payment() completely unmodified, through their
   existing public API.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.common.utils.pdf_documents import compute_round_off
from apps.platform.invoices.models import Invoice
from apps.platform.invoices.service import InvoiceService
from apps.platform.jobcards.models import JobCard
from apps.platform.proforma_invoices.models import AdvancePayment, ProformaInvoice, ProformaInvoiceLineItem
from apps.platform.proforma_invoices.utils import allocate_next_advance_receipt_number, allocate_next_proforma_number


# ─────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────

class ProformaInvoiceError(Exception):
    """Base class for ProformaInvoiceService errors."""


class InvalidJobCardForProforma(ProformaInvoiceError):
    """Raised when a proforma can't be generated for this job card (cancelled, or already invoiced)."""


class InvalidProformaStatus(ProformaInvoiceError):
    """Raised when a status transition is attempted from an invalid current status."""


class ProformaNotLatestVersion(ProformaInvoiceError):
    """Raised when an action requiring the latest version is attempted on a superseded one."""


class ProformaRevisionNotAllowed(ProformaInvoiceError):
    """Raised when a revision is attempted from a status that doesn't support it."""


class ProformaAlreadyConverted(ProformaInvoiceError):
    """Raised when attempting to convert a proforma that has already been converted."""


class ProformaInvoiceAlreadyActive(ProformaInvoiceError):
    """Raised when generating a new proforma family for a job card that
    already has one in draft/issued/approved — the live, trackable state is
    "revise it" (ProformaInvoiceService.create_revision), not spin up an
    unrelated second proforma number. Only once the existing one reaches a
    terminal state (rejected/expired/cancelled/converted) is a fresh
    generate() meaningful again."""


class AdvancePaymentError(Exception):
    """Base class for AdvancePaymentService errors."""


class InvalidProformaStatusForAdvance(AdvancePaymentError):
    """Raised when recording an advance against a proforma that isn't issued/approved."""


class InvalidAdvancePaymentAmount(AdvancePaymentError):
    """Raised when the advance amount is not positive."""


class InvalidAdvancePaymentStatus(AdvancePaymentError):
    """Raised when a status transition is attempted from an invalid current status."""


class AdvancePaymentAlreadyApplied(AdvancePaymentError):
    """Raised when attempting to reverse/refund an advance already applied to an invoice."""


# ─────────────────────────────────────────────────────────────────────────
# Shared snapshot helper
# ─────────────────────────────────────────────────────────────────────────

def _snapshot_totals_from_job_card(job_card: JobCard, invoice_type: str) -> dict:
    """
    Same branch as InvoiceService.generate(): GST proformas carry the job
    card's tax amounts verbatim; Non-GST proformas zero CGST/SGST/IGST and
    recompute total_amount without tax. The job card itself is never
    modified either way.
    """
    is_gst = invoice_type == Invoice.INVOICE_TYPE_GST
    if is_gst:
        return {
            "cgst_amount": job_card.cgst_amount,
            "sgst_amount": job_card.sgst_amount,
            "igst_amount": job_card.igst_amount,
            "total_amount": job_card.total_amount,
            "round_off_amount": job_card.round_off_amount,
        }
    exact_total = job_card.subtotal - job_card.discount_amount + job_card.shop_fees
    total_amount, round_off_amount = compute_round_off(exact_total)
    return {
        "cgst_amount": Decimal("0.00"),
        "sgst_amount": Decimal("0.00"),
        "igst_amount": Decimal("0.00"),
        "total_amount": total_amount,
        "round_off_amount": round_off_amount,
    }


def _snapshot_line_items_from_job_card(proforma: ProformaInvoice, job_card: JobCard, invoice_type: str) -> None:
    """Bulk-creates ProformaInvoiceLineItem rows snapshotted from the job card's
    CURRENT line items — same HSN/SAC + tax-zeroing logic as InvoiceService.generate()."""
    is_gst = invoice_type == Invoice.INVOICE_TYPE_GST
    lines = list(job_card.line_items.select_related("service_item").order_by("sort_order", "created_at"))
    new_lines = []
    for line in lines:
        hsn_sac = ""
        if line.service_item_id and line.service_item:
            hsn_sac = line.service_item.hsn_code or ""
        new_lines.append(
            ProformaInvoiceLineItem(
                proforma_invoice=proforma,
                sort_order=line.sort_order,
                service_item_id=line.service_item_id,
                service_type=line.service_type,
                description=line.description,
                detail_text=line.detail_text or "",
                hsn_sac_code=hsn_sac,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_amount=line.discount_amount,
                gst_percentage=line.gst_percentage if is_gst else Decimal("0.00"),
                price_type=line.price_type,
                cgst_amount=line.cgst_amount if is_gst else Decimal("0.00"),
                sgst_amount=line.sgst_amount if is_gst else Decimal("0.00"),
                line_total=line.line_total,
            )
        )
    ProformaInvoiceLineItem.objects.bulk_create(new_lines)


class ProformaInvoiceService:
    """Stateless service class — all methods are static/class-level."""

    @staticmethod
    def apply_expiry_if_due(proforma: ProformaInvoice) -> ProformaInvoice:
        """Lazily flip ISSUED/APPROVED -> EXPIRED once valid_until has passed.
        No background scheduler exists anywhere in this codebase (see
        QuotationService.apply_expiry_if_due) — expiry is checked on read."""
        if (
            proforma.status in (ProformaInvoice.STATUS_ISSUED, ProformaInvoice.STATUS_APPROVED)
            and proforma.valid_until
            and proforma.valid_until < timezone.now().date()
        ):
            now = timezone.now()
            ProformaInvoice.objects.filter(pk=proforma.pk).update(status=ProformaInvoice.STATUS_EXPIRED, updated_at=now)
            proforma.status = ProformaInvoice.STATUS_EXPIRED
        return proforma

    @staticmethod
    @transaction.atomic
    def generate(job_card: JobCard, created_by, invoice_type: str = Invoice.INVOICE_TYPE_GST) -> ProformaInvoice:
        """
        Generate a draft ProformaInvoice snapshotting the job card's current
        line items/totals. Unlike InvoiceService.generate(), there is no
        'completed' status gate — a proforma is explicitly a *preliminary*
        estimate, useful from early in the job's lifecycle. The gates are:
        the job card isn't cancelled, it doesn't already have an active
        (non-cancelled) real Invoice, and it doesn't already have an active
        (draft/issued/approved) proforma — that case should go through
        create_revision() instead of spinning up an unrelated second
        proforma number (see ProformaInvoiceAlreadyActive).
        """
        if job_card.status == JobCard.STATUS_CANCELLED:
            raise InvalidJobCardForProforma(
                f"Job card '{job_card.jobcard_number}' is cancelled and cannot have a proforma invoice generated."
            )
        if Invoice.objects.filter(job_card=job_card, is_cancelled=False).exists():
            raise InvalidJobCardForProforma(
                f"Job card '{job_card.jobcard_number}' already has an active invoice — "
                "a proforma estimate is no longer applicable."
            )
        existing_active = ProformaInvoice.objects.filter(
            job_card=job_card, is_latest=True,
            status__in=[ProformaInvoice.STATUS_DRAFT, ProformaInvoice.STATUS_ISSUED, ProformaInvoice.STATUS_APPROVED],
        ).first()
        if existing_active:
            raise ProformaInvoiceAlreadyActive(
                f"Job card '{job_card.jobcard_number}' already has an active proforma invoice "
                f"'{existing_active.proforma_number}' ({existing_active.status}) — revise it instead of "
                "creating a new one."
            )

        proforma_number, fy_code, sequence_no = allocate_next_proforma_number(job_card.tenant_id)
        totals = _snapshot_totals_from_job_card(job_card, invoice_type)
        today = timezone.now().date()

        terms = ""
        try:
            terms = job_card.tenant.invoice_settings.terms_and_conditions or ""
        except Exception:
            pass

        proforma = ProformaInvoice.objects.create(
            tenant_id=job_card.tenant_id,
            job_card=job_card,
            customer_id=job_card.customer_id,
            vehicle_id=job_card.vehicle_id,
            proforma_number=proforma_number,
            fy_code=fy_code,
            sequence_no=sequence_no,
            invoice_type=invoice_type,
            status=ProformaInvoice.STATUS_DRAFT,
            issue_date=today,
            subtotal=job_card.subtotal,
            discount_amount=job_card.discount_amount,
            shop_fees=job_card.shop_fees,
            terms_and_conditions=terms,
            created_by=created_by,
            **totals,
        )
        _snapshot_line_items_from_job_card(proforma, job_card, invoice_type)
        proforma.refresh_from_db()
        return proforma

    @staticmethod
    @transaction.atomic
    def issue(proforma: ProformaInvoice) -> ProformaInvoice:
        if proforma.status != ProformaInvoice.STATUS_DRAFT:
            raise InvalidProformaStatus(
                f"Proforma '{proforma.proforma_number}' v{proforma.version} must be in "
                f"'draft' status to issue (current: '{proforma.status}')."
            )
        if not proforma.line_items.exists():
            raise InvalidProformaStatus("Cannot issue a proforma invoice with no line items.")
        now = timezone.now()
        ProformaInvoice.objects.filter(pk=proforma.pk).update(status=ProformaInvoice.STATUS_ISSUED, issued_at=now, updated_at=now)
        proforma.refresh_from_db()
        return proforma

    @staticmethod
    @transaction.atomic
    def approve(proforma: ProformaInvoice) -> ProformaInvoice:
        ProformaInvoiceService.apply_expiry_if_due(proforma)
        if proforma.status != ProformaInvoice.STATUS_ISSUED:
            raise InvalidProformaStatus(
                f"Proforma '{proforma.proforma_number}' v{proforma.version} must be in "
                f"'issued' status to approve (current: '{proforma.status}')."
            )
        now = timezone.now()
        ProformaInvoice.objects.filter(pk=proforma.pk).update(status=ProformaInvoice.STATUS_APPROVED, approved_at=now, updated_at=now)
        proforma.refresh_from_db()
        return proforma

    @staticmethod
    @transaction.atomic
    def reject(proforma: ProformaInvoice, *, reason: str = "") -> ProformaInvoice:
        ProformaInvoiceService.apply_expiry_if_due(proforma)
        if proforma.status != ProformaInvoice.STATUS_ISSUED:
            raise InvalidProformaStatus(
                f"Proforma '{proforma.proforma_number}' v{proforma.version} must be in "
                f"'issued' status to reject (current: '{proforma.status}')."
            )
        now = timezone.now()
        ProformaInvoice.objects.filter(pk=proforma.pk).update(
            status=ProformaInvoice.STATUS_REJECTED, rejected_at=now, rejection_reason=reason or "", updated_at=now
        )
        proforma.refresh_from_db()
        return proforma

    @staticmethod
    @transaction.atomic
    def cancel(proforma: ProformaInvoice, *, reason: str = "") -> ProformaInvoice:
        if proforma.status in (ProformaInvoice.STATUS_CANCELLED, ProformaInvoice.STATUS_CONVERTED):
            raise InvalidProformaStatus(
                f"Proforma '{proforma.proforma_number}' v{proforma.version} is already "
                f"'{proforma.status}' and cannot be cancelled."
            )
        now = timezone.now()
        ProformaInvoice.objects.filter(pk=proforma.pk).update(
            status=ProformaInvoice.STATUS_CANCELLED, cancelled_at=now, cancellation_reason=reason or "", updated_at=now
        )
        proforma.refresh_from_db()
        return proforma

    @staticmethod
    @transaction.atomic
    def create_revision(proforma: ProformaInvoice, *, revision_reason: str, created_by) -> ProformaInvoice:
        """
        Create version N+1 of `proforma`'s family. Unlike
        QuotationService.create_revision() (which copies the OLD version's
        own line items — Quotation is authored standalone, not derived from
        anything live), this RE-SNAPSHOTS from the job card's CURRENT line
        items/totals: a proforma revision exists specifically because the
        job card's scope/pricing changed, so the new version should reflect
        that, not a hand-copy of stale numbers. The old version remains
        untouched (is_latest=False) for audit.

        Only allowed from issued/approved/rejected/expired — draft is
        already directly editable by regenerating; cancelled/converted are
        dead ends.
        """
        ProformaInvoiceService.apply_expiry_if_due(proforma)

        if not proforma.is_latest:
            raise ProformaNotLatestVersion("Only the latest version of a proforma invoice can be revised.")
        if proforma.status not in (
            ProformaInvoice.STATUS_ISSUED,
            ProformaInvoice.STATUS_APPROVED,
            ProformaInvoice.STATUS_REJECTED,
            ProformaInvoice.STATUS_EXPIRED,
        ):
            raise ProformaRevisionNotAllowed(f"Cannot create a revision from a proforma in '{proforma.status}' status.")

        job_card = proforma.job_card
        if job_card.status == JobCard.STATUS_CANCELLED:
            raise InvalidJobCardForProforma(
                f"Job card '{job_card.jobcard_number}' is cancelled and cannot have a proforma revision generated."
            )

        parent = proforma
        # Flip the parent's is_latest OFF first — the partial unique constraint
        # on (tenant, proforma_number) WHERE is_latest allows at most one such
        # row at any instant within the transaction.
        ProformaInvoice.objects.filter(pk=parent.pk).update(is_latest=False, updated_at=timezone.now())

        today = timezone.now().date()
        new_valid_until = parent.valid_until if parent.valid_until and parent.valid_until >= today else None
        totals = _snapshot_totals_from_job_card(job_card, parent.invoice_type)

        new_version = ProformaInvoice.objects.create(
            tenant_id=parent.tenant_id,
            job_card=job_card,
            customer_id=job_card.customer_id,
            vehicle_id=job_card.vehicle_id,
            proforma_number=parent.proforma_number,
            fy_code=parent.fy_code,
            sequence_no=parent.sequence_no,
            invoice_type=parent.invoice_type,
            version=parent.version + 1,
            parent_proforma=parent,
            is_latest=True,
            revision_reason=revision_reason,
            status=ProformaInvoice.STATUS_DRAFT,
            issue_date=today,
            valid_until=new_valid_until,
            subtotal=job_card.subtotal,
            discount_amount=job_card.discount_amount,
            shop_fees=job_card.shop_fees,
            terms_and_conditions=parent.terms_and_conditions,
            customer_notes=parent.customer_notes,
            internal_notes=parent.internal_notes,
            created_by=created_by,
            **totals,
        )
        _snapshot_line_items_from_job_card(new_version, job_card, parent.invoice_type)

        new_version.refresh_from_db()
        return new_version

    @staticmethod
    @transaction.atomic
    def convert_to_invoice(proforma: ProformaInvoice, *, issued_by) -> Invoice:
        """
        Convert an approved, latest-version proforma into the real Invoice —
        via the existing, UNMODIFIED InvoiceService.generate() (same
        'completed' job-card-status gate as every other invoice generation),
        then credits any received-and-unapplied advance payments into it via
        the existing, UNMODIFIED InvoiceService.record_payment().

        Advances are applied oldest-first, in full, never split: the first
        advance that would push amount_paid past total_amount is skipped
        (left unapplied — a visible, tracked excess/credit balance on the
        proforma), and later, smaller advances are still tried in case they
        fit. No refund money-movement happens automatically — see
        AdvancePaymentService.refund() for the manual, tracked alternative.

        select_for_update() on the proforma row + the converted/invoice_id
        check below block a double-click or concurrent-retry from ever
        creating two invoices from the same proforma.
        """
        proforma = ProformaInvoice.objects.select_for_update().get(pk=proforma.pk)
        ProformaInvoiceService.apply_expiry_if_due(proforma)

        if proforma.status == ProformaInvoice.STATUS_CONVERTED or proforma.invoice_id:
            raise ProformaAlreadyConverted(
                f"Proforma '{proforma.proforma_number}' v{proforma.version} has already been converted."
            )
        if not proforma.is_latest:
            raise ProformaNotLatestVersion("Only the latest version of a proforma invoice can be converted.")
        if proforma.status != ProformaInvoice.STATUS_APPROVED:
            raise InvalidProformaStatus(
                f"Proforma must be 'approved' to convert to an invoice (current: '{proforma.status}')."
            )

        job_card = proforma.job_card
        invoice = InvoiceService.generate(job_card, issued_by=issued_by, invoice_type=proforma.invoice_type)

        pending_advances = proforma.advance_payments.filter(
            status=AdvancePayment.STATUS_RECEIVED, applied=False
        ).order_by("created_at")
        for payment in pending_advances:
            if invoice.amount_paid + payment.amount > invoice.total_amount:
                # Would overflow the invoice total — left entirely unapplied
                # (not split); try the next advance, a smaller one may still fit.
                continue
            invoice = InvoiceService.record_payment(
                invoice,
                payment_mode=Invoice.PAYMENT_MODE_ADVANCE,
                amount_paid=payment.amount,
                payment_reference=f"Advance receipt {payment.receipt_number}".strip(),
                recorded_by=issued_by,
            )
            AdvancePayment.objects.filter(pk=payment.pk).update(
                applied=True, applied_to_invoice=invoice, updated_at=timezone.now()
            )

        now = timezone.now()
        Invoice.objects.filter(pk=invoice.pk).update(proforma_invoice=proforma, updated_at=now)
        invoice.proforma_invoice = proforma
        ProformaInvoice.objects.filter(pk=proforma.pk).update(
            status=ProformaInvoice.STATUS_CONVERTED, converted_at=now, invoice=invoice, updated_at=now
        )

        return invoice


class AdvancePaymentService:
    """Stateless service class — all methods are static/class-level."""

    @staticmethod
    def _allocate_receipt(payment: AdvancePayment) -> AdvancePayment:
        """Eagerly allocates the receipt NUMBER (a statutory identifier that
        should exist the moment a payment is confirmed received) — the
        receipt PDF itself stays lazy (rendered on first preview/download),
        matching every other PDF in this codebase (pdf_key stays null until
        someone actually requests it)."""
        receipt_number = allocate_next_advance_receipt_number(payment.tenant_id)
        AdvancePayment.objects.filter(pk=payment.pk).update(receipt_number=receipt_number, updated_at=timezone.now())
        payment.receipt_number = receipt_number
        return payment

    @staticmethod
    @transaction.atomic
    def record(
        proforma_invoice: ProformaInvoice, *, amount, payment_mode: str,
        payment_reference: str = "", received_by, remarks: str = "",
    ) -> AdvancePayment:
        """
        Record an advance payment against an issued/approved proforma. Manual
        modes (cash/upi/card/bank_transfer/cheque/other) are recorded as
        already-received, same as every other payment in this codebase
        (InvoicePayment has no 'pending' concept either — it's always an
        after-the-fact ledger entry). Only 'online_gateway' starts 'pending'
        — there is no gateway webhook integration anywhere in this codebase,
        so staff confirm it manually later via mark_received().
        """
        amount = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
        if amount <= 0:
            raise InvalidAdvancePaymentAmount("Advance payment amount must be positive.")

        ProformaInvoiceService.apply_expiry_if_due(proforma_invoice)
        if proforma_invoice.status not in (ProformaInvoice.STATUS_ISSUED, ProformaInvoice.STATUS_APPROVED):
            raise InvalidProformaStatusForAdvance(
                f"Proforma '{proforma_invoice.proforma_number}' v{proforma_invoice.version} must be "
                f"'issued' or 'approved' to record an advance payment (current: '{proforma_invoice.status}')."
            )

        is_manual = payment_mode in AdvancePayment.MANUAL_MODES
        status = AdvancePayment.STATUS_RECEIVED if is_manual else AdvancePayment.STATUS_PENDING

        payment = AdvancePayment.objects.create(
            tenant_id=proforma_invoice.tenant_id,
            proforma_invoice=proforma_invoice,
            job_card_id=proforma_invoice.job_card_id,
            amount=amount,
            payment_mode=payment_mode,
            payment_reference=payment_reference,
            status=status,
            remarks=remarks,
            received_by=received_by,
        )

        if status == AdvancePayment.STATUS_RECEIVED:
            AdvancePaymentService._allocate_receipt(payment)

        return payment

    @staticmethod
    @transaction.atomic
    def mark_received(payment: AdvancePayment, *, received_by) -> AdvancePayment:
        """Gateway-mode transition pending -> received — a manual staff
        confirmation (after checking their own gateway dashboard), not a
        webhook callback, since no gateway integration exists in this app."""
        if payment.status != AdvancePayment.STATUS_PENDING:
            raise InvalidAdvancePaymentStatus(
                f"Advance payment is '{payment.status}', not 'pending' — cannot mark as received."
            )
        now = timezone.now()
        AdvancePayment.objects.filter(pk=payment.pk).update(
            status=AdvancePayment.STATUS_RECEIVED, received_by=received_by, updated_at=now
        )
        payment.status = AdvancePayment.STATUS_RECEIVED
        payment.received_by = received_by
        AdvancePaymentService._allocate_receipt(payment)
        return payment

    @staticmethod
    @transaction.atomic
    def mark_failed(payment: AdvancePayment) -> AdvancePayment:
        if payment.status != AdvancePayment.STATUS_PENDING:
            raise InvalidAdvancePaymentStatus(
                f"Advance payment is '{payment.status}', not 'pending' — cannot mark as failed."
            )
        AdvancePayment.objects.filter(pk=payment.pk).update(status=AdvancePayment.STATUS_FAILED, updated_at=timezone.now())
        payment.status = AdvancePayment.STATUS_FAILED
        return payment

    @staticmethod
    @transaction.atomic
    def reverse(payment: AdvancePayment, *, reason: str = "") -> AdvancePayment:
        if payment.status != AdvancePayment.STATUS_RECEIVED:
            raise InvalidAdvancePaymentStatus("Only a 'received' advance payment can be reversed.")
        if payment.applied:
            raise AdvancePaymentAlreadyApplied(
                "This advance has already been applied to an invoice — reverse/cancel the invoice "
                "payment instead of this advance record."
            )
        now = timezone.now()
        AdvancePayment.objects.filter(pk=payment.pk).update(
            status=AdvancePayment.STATUS_REVERSED, reversed_at=now, reversal_reason=reason or "", updated_at=now
        )
        payment.status = AdvancePayment.STATUS_REVERSED
        return payment

    @staticmethod
    @transaction.atomic
    def refund(payment: AdvancePayment, *, reason: str = "") -> AdvancePayment:
        """Tracked status flag only — no refund/payment-gateway API exists in
        this codebase to call, so no money actually moves here."""
        if payment.status != AdvancePayment.STATUS_RECEIVED:
            raise InvalidAdvancePaymentStatus("Only a 'received' advance payment can be refunded.")
        if payment.applied:
            raise AdvancePaymentAlreadyApplied(
                "This advance has already been applied to an invoice and cannot be refunded directly."
            )
        now = timezone.now()
        AdvancePayment.objects.filter(pk=payment.pk).update(
            status=AdvancePayment.STATUS_REFUNDED, refunded_at=now, refund_reason=reason or "", updated_at=now
        )
        payment.status = AdvancePayment.STATUS_REFUNDED
        return payment
