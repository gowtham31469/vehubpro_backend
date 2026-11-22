"""
CreditNoteService — core business logic for issuing a Credit Note against an
Invoice (full or partial), and the refund/cancellation lifecycle around it.

Design principles
-----------------
1. Never touches InvoicePayment / Invoice.amount_paid — that ledger must stay
   permanently equal to Sum(InvoicePayment.amount) for
   InvoiceService.record_payment()'s own invariant. A credit note instead
   reduces an "effective total" (invoice.total_amount minus all issued
   credit notes' total_amount) and re-derives Invoice.payment_status against
   that, exactly mirroring record_payment()'s own three-way comparison.
2. Tax on credited lines is always a proportional scale-down of what was
   actually charged on the original InvoiceLineItem — never a fresh flat-rate
   recomputation, so the credit note's tax breakdown can never drift from
   what was really billed.
3. Atomicity: number allocation + CreditNote row + line items + invoice
   payment_status recompute all happen inside one transaction.
4. Refunds are a tracked status flag only (mirrors
   proforma_invoices.AdvancePaymentService.refund()) — no payment-gateway API
   exists anywhere in this codebase, so no money actually moves here.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from apps.common.utils.pdf_documents import compute_round_off
from apps.platform.credit_notes.models import CreditNote, CreditNoteFySequence, CreditNoteLineItem
from apps.platform.invoices.models import Invoice, InvoiceLineItem
from apps.platform.jobcards.models import indian_fy_code


class CreditNoteError(Exception):
    """Base class for CreditNoteService errors."""


class InvoiceIsCancelled(CreditNoteError):
    """Raised when attempting to credit a cancelled invoice."""


class NoCreditTargetSpecified(CreditNoteError):
    """Raised when neither line_item_credits nor custom_amount is supplied."""


class InvalidLineItemReference(CreditNoteError):
    """Raised when a referenced InvoiceLineItem doesn't belong to this invoice."""


class OverCreditError(CreditNoteError):
    """Raised when the requested credit would exceed what's left creditable."""


class CreditNoteAlreadyCancelled(CreditNoteError):
    """Raised when attempting to cancel an already-cancelled credit note."""


class CreditNoteAlreadyRefunded(CreditNoteError):
    """Raised when attempting to cancel a credit note already marked refunded."""


class InvalidCreditNoteRefundState(CreditNoteError):
    """Raised when mark_refunded() is called on a note with no pending refund."""


def _allocate_credit_note_number(tenant_id) -> tuple[str, str, int]:
    """
    Thread-safe credit note number allocation inside an atomic block.
    Returns (credit_note_number, fy_code, sequence_no).
    Must be called within an active transaction.atomic() context.
    """
    fy = indian_fy_code(timezone.now().date())
    row, _ = CreditNoteFySequence.objects.select_for_update().get_or_create(
        tenant_id=tenant_id,
        fy_code=fy,
        defaults={"last_seq": 0},
    )
    row.last_seq += 1
    row.save(update_fields=["last_seq", "updated_at"])
    credit_note_number = f"CN/{fy}/{row.last_seq:05d}"
    return credit_note_number, fy, row.last_seq


def _effective_total(invoice: Invoice) -> Decimal:
    """invoice.total_amount minus every ISSUED credit note's total_amount."""
    credited = CreditNote.objects.filter(
        invoice=invoice, status=CreditNote.STATUS_ISSUED
    ).aggregate(s=models.Sum("total_amount"))["s"] or Decimal("0")
    return Decimal(str(invoice.total_amount)) - Decimal(str(credited))


def _recompute_invoice_payment_status(invoice: Invoice) -> None:
    """
    Re-derive Invoice.payment_status against the effective total (total_amount
    minus issued credit notes), WITHOUT ever touching amount_paid — that field
    must stay exactly Sum(InvoicePayment.amount) forever, independent of
    credit notes, for record_payment()'s own ledger invariant to keep working.
    """
    amount_paid = Decimal(str(invoice.amount_paid or 0))
    effective_total = _effective_total(invoice)

    if amount_paid <= 0:
        new_status = Invoice.PAYMENT_STATUS_UNPAID
    elif amount_paid >= effective_total:
        new_status = Invoice.PAYMENT_STATUS_PAID
    else:
        new_status = Invoice.PAYMENT_STATUS_PARTIAL

    Invoice.objects.filter(pk=invoice.pk).update(payment_status=new_status, updated_at=timezone.now())
    invoice.payment_status = new_status


class CreditNoteService:
    """Stateless service class — all methods are static/class-level."""

    @staticmethod
    @transaction.atomic
    def generate(
        invoice: Invoice,
        *,
        created_by,
        line_item_credits: list[dict] | None = None,
        custom_amount: Decimal | None = None,
        custom_gst_percentage: Decimal | None = None,
        reason: str,
        reason_category: str = "",
    ) -> CreditNote:
        """
        Issue a credit note against `invoice`.

        line_item_credits: optional list of {"invoice_line_item_id": ..., "amount": Decimal}
            — "amount" is the taxable (pre-tax) amount of that line being
            credited; must not exceed what's left creditable on that specific
            line (line_total minus amounts already credited against it by
            other issued credit notes). CGST/SGST are scaled down from the
            line's own stored tax amounts by the same fraction.
        custom_amount: optional flat, non-line-tied taxable credit amount.
            GST-free (0%) unless custom_gst_percentage is explicitly supplied.
        At least one of line_item_credits / custom_amount is required.
        """
        if invoice.is_cancelled:
            raise InvoiceIsCancelled(
                f"Invoice '{invoice.invoice_number}' is cancelled and has no outstanding balance to credit."
            )

        line_item_credits = line_item_credits or []
        if not line_item_credits and not custom_amount:
            raise NoCreditTargetSpecified("Specify at least one line item credit or a custom amount.")

        # ── Per-line "already credited" lookup — prevents double-crediting
        #     the same line across two separate partial credit notes, even
        #     when the header-level remaining would still allow it. ─────────
        already_credited_by_line = dict(
            CreditNoteLineItem.objects.filter(
                credit_note__invoice=invoice,
                credit_note__status=CreditNote.STATUS_ISSUED,
                invoice_line_item__isnull=False,
            )
            .values("invoice_line_item_id")
            .annotate(total=models.Sum("line_total"))
            .values_list("invoice_line_item_id", "total")
        )

        line_items_ctx = []
        subtotal = Decimal("0")
        cgst_total = Decimal("0")
        sgst_total = Decimal("0")

        for credit in line_item_credits:
            line = InvoiceLineItem.objects.filter(
                pk=credit["invoice_line_item_id"], invoice=invoice
            ).first()
            if line is None:
                raise InvalidLineItemReference(
                    f"Line item '{credit['invoice_line_item_id']}' does not belong to this invoice."
                )
            already = Decimal(str(already_credited_by_line.get(line.id, 0)))
            remaining_on_line = Decimal(str(line.line_total)) - already
            credit_amount = Decimal(str(credit["amount"])).quantize(Decimal("0.01"))
            if credit_amount <= 0:
                continue
            if credit_amount > remaining_on_line:
                raise OverCreditError(
                    f"Cannot credit {credit_amount} against line '{line.description}' — "
                    f"only {remaining_on_line} is left creditable on that line."
                )

            fraction = (credit_amount / Decimal(str(line.line_total))) if line.line_total else Decimal("0")
            line_cgst = (Decimal(str(line.cgst_amount)) * fraction).quantize(Decimal("0.01"))
            line_sgst = (Decimal(str(line.sgst_amount)) * fraction).quantize(Decimal("0.01"))

            subtotal += credit_amount
            cgst_total += line_cgst
            sgst_total += line_sgst

            line_items_ctx.append({
                "invoice_line_item": line,
                "service_type": line.service_type,
                "description": line.description,
                "detail_text": line.detail_text,
                "hsn_sac_code": line.hsn_sac_code,
                "labour_category_name": line.labour_category_name,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "gst_percentage": line.gst_percentage,
                "price_type": line.price_type,
                "cgst_amount": line_cgst,
                "sgst_amount": line_sgst,
                "line_total": credit_amount,
            })

        if custom_amount:
            custom_amount = Decimal(str(custom_amount)).quantize(Decimal("0.01"))
            custom_gst_percentage = Decimal(str(custom_gst_percentage or 0))
            custom_cgst = Decimal("0")
            custom_sgst = Decimal("0")
            if custom_gst_percentage:
                half = (custom_amount * custom_gst_percentage / Decimal("100") / Decimal("2")).quantize(Decimal("0.01"))
                custom_cgst = half
                custom_sgst = half
            subtotal += custom_amount
            cgst_total += custom_cgst
            sgst_total += custom_sgst
            line_items_ctx.append({
                "invoice_line_item": None,
                "service_type": InvoiceLineItem.SERVICE_TYPE_LABOUR,
                "description": "Custom credit",
                "detail_text": "",
                "hsn_sac_code": "",
                "labour_category_name": "",
                "quantity": Decimal("1"),
                "unit_price": custom_amount,
                "gst_percentage": custom_gst_percentage,
                "price_type": InvoiceLineItem.PRICE_TYPE_EXCLUSIVE,
                "cgst_amount": custom_cgst,
                "sgst_amount": custom_sgst,
                "line_total": custom_amount,
            })

        if not line_items_ctx:
            raise NoCreditTargetSpecified("No creditable amount was supplied.")

        exact_total = subtotal + cgst_total + sgst_total
        total_amount, round_off_amount = compute_round_off(exact_total)

        # ── Header guard: never let the cumulative credited amount exceed
        #     the invoice's own total — checked both pre- and post-round. ────
        total_already_credited = CreditNote.objects.filter(
            invoice=invoice, status=CreditNote.STATUS_ISSUED
        ).aggregate(s=models.Sum("total_amount"))["s"] or Decimal("0")
        creditable_remaining = Decimal(str(invoice.total_amount)) - Decimal(str(total_already_credited))
        if exact_total > creditable_remaining or total_amount > creditable_remaining:
            raise OverCreditError(
                f"This credit would exceed the invoice's remaining creditable amount "
                f"({creditable_remaining})."
            )

        credit_note_number, fy_code, sequence_no = _allocate_credit_note_number(invoice.tenant_id)

        credit_note = CreditNote.objects.create(
            tenant=invoice.tenant,
            invoice=invoice,
            credit_note_number=credit_note_number,
            fy_code=fy_code,
            sequence_no=sequence_no,
            status=CreditNote.STATUS_ISSUED,
            reason=reason,
            reason_category=reason_category,
            subtotal=subtotal,
            discount_amount=Decimal("0"),
            cgst_amount=cgst_total,
            sgst_amount=sgst_total,
            igst_amount=Decimal("0"),
            round_off_amount=round_off_amount,
            total_amount=total_amount,
            issued_by=created_by,
        )

        CreditNoteLineItem.objects.bulk_create([
            CreditNoteLineItem(
                credit_note=credit_note,
                sort_order=idx,
                **{k: v for k, v in ctx.items()},
            )
            for idx, ctx in enumerate(line_items_ctx)
        ])

        # ── Refund tracking: if the customer had already paid more than what
        #     will remain owed after this credit, track that excess — never
        #     touch Invoice.amount_paid itself. ──────────────────────────────
        amount_paid = Decimal(str(invoice.amount_paid or 0))
        new_effective_total = _effective_total(invoice)  # re-reads with this note now counted
        excess = amount_paid - new_effective_total
        if excess > 0:
            CreditNote.objects.filter(pk=credit_note.pk).update(
                is_refund_applicable=True,
                refund_status=CreditNote.REFUND_STATUS_PENDING,
                refund_amount=excess,
            )
            credit_note.is_refund_applicable = True
            credit_note.refund_status = CreditNote.REFUND_STATUS_PENDING
            credit_note.refund_amount = excess

        _recompute_invoice_payment_status(invoice)

        return credit_note

    @staticmethod
    @transaction.atomic
    def mark_refunded(credit_note: CreditNote, *, reason: str = "") -> CreditNote:
        """Tracked status flag only — no refund/payment-gateway API exists in
        this codebase to call, so no money actually moves here."""
        if not credit_note.is_refund_applicable:
            raise InvalidCreditNoteRefundState("This credit note has no refundable amount.")
        if credit_note.refund_status != CreditNote.REFUND_STATUS_PENDING:
            raise InvalidCreditNoteRefundState("Only a pending refund can be marked as refunded.")

        now = timezone.now()
        CreditNote.objects.filter(pk=credit_note.pk).update(
            refund_status=CreditNote.REFUND_STATUS_REFUNDED,
            refunded_at=now,
            refund_reason=reason or "",
            updated_at=now,
        )
        credit_note.refund_status = CreditNote.REFUND_STATUS_REFUNDED
        credit_note.refunded_at = now
        credit_note.refund_reason = reason or ""
        return credit_note

    @staticmethod
    @transaction.atomic
    def cancel(credit_note: CreditNote, *, cancelled_by, reason: str = "") -> CreditNote:
        """
        Void a credit note without deleting it — its amount drops out of the
        invoice's "already credited" pool, restoring that headroom, and the
        invoice's payment_status is recomputed accordingly.
        """
        if credit_note.status == CreditNote.STATUS_CANCELLED:
            raise CreditNoteAlreadyCancelled(f"Credit note '{credit_note.credit_note_number}' is already cancelled.")
        if credit_note.refund_status == CreditNote.REFUND_STATUS_REFUNDED:
            raise CreditNoteAlreadyRefunded(
                f"Credit note '{credit_note.credit_note_number}' has already been marked refunded "
                "and cannot be cancelled — resolve the refund manually first."
            )

        now = timezone.now()
        old_pdf_key = credit_note.pdf_key
        CreditNote.objects.filter(pk=credit_note.pk).update(
            status=CreditNote.STATUS_CANCELLED,
            cancelled_at=now,
            cancelled_by=cancelled_by,
            cancellation_reason=reason or "",
            pdf_key=None,
            updated_at=now,
        )
        credit_note.status = CreditNote.STATUS_CANCELLED
        credit_note.cancelled_at = now
        credit_note.cancelled_by = cancelled_by
        credit_note.cancellation_reason = reason or ""
        credit_note.pdf_key = None

        if old_pdf_key:
            try:
                from core.storage.resolve import delete_stored_media
                delete_stored_media(old_pdf_key)
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    "Could not delete stale PDF %s while cancelling credit note %s",
                    old_pdf_key, credit_note.pk,
                )

        invoice = credit_note.invoice
        _recompute_invoice_payment_status(invoice)

        return credit_note
