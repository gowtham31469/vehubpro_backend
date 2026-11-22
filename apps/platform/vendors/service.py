"""VendorBillService / VendorPaymentService — accounts-payable business logic."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db import models, transaction
from django.utils import timezone

from apps.common.utils.pdf_documents import compute_round_off
from apps.platform.jobcards.models import indian_fy_code
from apps.platform.vendors.models import (
    VendorBill,
    VendorBillFySequence,
    VendorPayment,
    VendorPaymentFySequence,
)


class VendorError(Exception):
    """Base class for vendor-service errors."""


class VendorBillAlreadyCancelled(VendorError):
    pass


class VendorBillHasPayments(VendorError):
    pass


class InvalidVendorBillReference(VendorError):
    """Raised when a payment's vendor_bill doesn't belong to the given vendor, or is cancelled."""


class OverPaymentError(VendorError):
    """Raised when a payment would push a bill's amount_paid past its net_payable_amount."""


class VendorPaymentAlreadyVoided(VendorError):
    pass


def _quantize(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _allocate_vendor_bill_number(tenant_id) -> tuple[str, str, int]:
    fy = indian_fy_code(timezone.now().date())
    row, _ = VendorBillFySequence.objects.select_for_update().get_or_create(
        tenant_id=tenant_id, fy_code=fy, defaults={"last_seq": 0},
    )
    row.last_seq += 1
    row.save(update_fields=["last_seq", "updated_at"])
    return f"VB/{fy}/{row.last_seq:05d}", fy, row.last_seq


def _allocate_vendor_payment_number(tenant_id) -> tuple[str, str, int]:
    fy = indian_fy_code(timezone.now().date())
    row, _ = VendorPaymentFySequence.objects.select_for_update().get_or_create(
        tenant_id=tenant_id, fy_code=fy, defaults={"last_seq": 0},
    )
    row.last_seq += 1
    row.save(update_fields=["last_seq", "updated_at"])
    return f"VP/{fy}/{row.last_seq:05d}", fy, row.last_seq


def vendor_outstanding_balance(vendor) -> Decimal:
    """
    Sum(issued bills' net_payable_amount - amount_paid) minus the vendor's
    non-voided on-account (unallocated) payments. Computed on read, not stored.
    """
    bills_due = VendorBill.objects.filter(
        vendor=vendor, status=VendorBill.STATUS_ISSUED,
    ).aggregate(
        total=models.Sum(models.F("net_payable_amount") - models.F("amount_paid"))
    )["total"] or Decimal("0")

    on_account = VendorPayment.objects.filter(
        vendor=vendor, vendor_bill__isnull=True, is_voided=False,
    ).aggregate(total=models.Sum("amount"))["total"] or Decimal("0")

    return _quantize(bills_due - on_account)


class VendorBillService:
    """Stateless service class — all methods are static/class-level."""

    @staticmethod
    @transaction.atomic
    def generate(
        vendor,
        *,
        created_by,
        bill_date,
        subtotal,
        gst_percentage=Decimal("0"),
        is_interstate=False,
        tds_percentage=Decimal("0"),
        vendor_bill_reference="",
        description="",
        due_date=None,
        attachment_file=None,
    ) -> VendorBill:
        subtotal = _quantize(subtotal)
        gst_percentage = Decimal(str(gst_percentage or 0))
        tds_percentage = Decimal(str(tds_percentage or 0))

        gst_amount = _quantize(subtotal * gst_percentage / Decimal("100"))
        if is_interstate:
            cgst_amount = Decimal("0.00")
            sgst_amount = Decimal("0.00")
            igst_amount = gst_amount
        else:
            half = _quantize(gst_amount / Decimal("2"))
            cgst_amount = half
            sgst_amount = gst_amount - half
            igst_amount = Decimal("0.00")

        exact_total = subtotal + cgst_amount + sgst_amount + igst_amount
        total_amount, round_off_amount = compute_round_off(exact_total)

        tds_amount = _quantize(subtotal * tds_percentage / Decimal("100"))
        net_payable_amount = total_amount - tds_amount

        if due_date is None and vendor.payment_terms_days:
            from datetime import timedelta
            due_date = bill_date + timedelta(days=vendor.payment_terms_days)

        bill_number, fy_code, sequence_no = _allocate_vendor_bill_number(vendor.tenant_id)

        bill = VendorBill.objects.create(
            tenant_id=vendor.tenant_id,
            vendor=vendor,
            bill_number=bill_number,
            fy_code=fy_code,
            sequence_no=sequence_no,
            vendor_bill_reference=vendor_bill_reference,
            bill_date=bill_date,
            due_date=due_date,
            description=description,
            subtotal=subtotal,
            gst_percentage=gst_percentage,
            is_interstate=is_interstate,
            cgst_amount=cgst_amount,
            sgst_amount=sgst_amount,
            igst_amount=igst_amount,
            round_off_amount=round_off_amount,
            total_amount=total_amount,
            tds_percentage=tds_percentage,
            tds_amount=tds_amount,
            net_payable_amount=net_payable_amount,
            status=VendorBill.STATUS_ISSUED,
            created_by=created_by,
        )

        if attachment_file is not None:
            from core.storage import upload_document_file
            bill.attachment = upload_document_file(
                attachment_file, folder="vendor_bill_attachments", record_id=str(bill.id),
            )
            bill.save(update_fields=["attachment", "updated_at"])

        return bill

    @staticmethod
    @transaction.atomic
    def cancel(bill: VendorBill, *, cancelled_by, reason: str = "") -> VendorBill:
        if bill.status == VendorBill.STATUS_CANCELLED:
            raise VendorBillAlreadyCancelled(f"Bill '{bill.bill_number}' is already cancelled.")
        if Decimal(str(bill.amount_paid)) > 0:
            raise VendorBillHasPayments(
                f"Bill '{bill.bill_number}' has payments recorded against it and cannot be cancelled."
            )

        bill.status = VendorBill.STATUS_CANCELLED
        bill.cancelled_at = timezone.now()
        bill.cancelled_by = cancelled_by
        bill.cancellation_reason = reason
        bill.save(update_fields=["status", "cancelled_at", "cancelled_by", "cancellation_reason", "updated_at"])
        return bill


def _recompute_bill_payment_status(bill: VendorBill) -> None:
    sum_paid = VendorPayment.objects.filter(vendor_bill=bill, is_voided=False).aggregate(
        total=models.Sum("amount")
    )["total"] or Decimal("0")

    net_payable = Decimal(str(bill.net_payable_amount))
    if sum_paid <= 0:
        new_status = VendorBill.PAYMENT_STATUS_UNPAID
    elif sum_paid >= net_payable:
        new_status = VendorBill.PAYMENT_STATUS_PAID
    else:
        new_status = VendorBill.PAYMENT_STATUS_PARTIAL

    VendorBill.objects.filter(pk=bill.pk).update(
        amount_paid=sum_paid, payment_status=new_status, updated_at=timezone.now(),
    )


class VendorPaymentService:
    """Stateless service class — all methods are static/class-level."""

    @staticmethod
    @transaction.atomic
    def record(
        vendor,
        *,
        amount,
        payment_mode,
        payment_date,
        recorded_by,
        vendor_bill=None,
        payment_reference="",
        notes="",
    ) -> VendorPayment:
        amount = _quantize(amount)

        if vendor_bill is not None:
            if vendor_bill.vendor_id != vendor.id:
                raise InvalidVendorBillReference("The selected bill does not belong to this vendor.")
            if vendor_bill.status == VendorBill.STATUS_CANCELLED:
                raise InvalidVendorBillReference("Cannot record a payment against a cancelled bill.")

            already_paid = VendorPayment.objects.filter(vendor_bill=vendor_bill, is_voided=False).aggregate(
                total=models.Sum("amount")
            )["total"] or Decimal("0")
            remaining = Decimal(str(vendor_bill.net_payable_amount)) - already_paid
            if amount > remaining:
                raise OverPaymentError(
                    f"This payment exceeds what's left payable on bill '{vendor_bill.bill_number}' "
                    f"({remaining:.2f} remaining)."
                )

        payment_number, fy_code, sequence_no = _allocate_vendor_payment_number(vendor.tenant_id)

        payment = VendorPayment.objects.create(
            tenant_id=vendor.tenant_id,
            vendor=vendor,
            vendor_bill=vendor_bill,
            payment_number=payment_number,
            fy_code=fy_code,
            sequence_no=sequence_no,
            amount=amount,
            payment_date=payment_date,
            payment_mode=payment_mode,
            payment_reference=payment_reference,
            notes=notes,
            recorded_by=recorded_by,
        )

        if vendor_bill is not None:
            _recompute_bill_payment_status(vendor_bill)

        return payment

    @staticmethod
    @transaction.atomic
    def void(payment: VendorPayment, *, voided_by, reason: str = "") -> VendorPayment:
        if payment.is_voided:
            raise VendorPaymentAlreadyVoided(f"Payment '{payment.payment_number}' is already voided.")

        payment.is_voided = True
        payment.voided_at = timezone.now()
        payment.voided_by = voided_by
        payment.void_reason = reason
        payment.save(update_fields=["is_voided", "voided_at", "voided_by", "void_reason", "updated_at"])

        if payment.vendor_bill_id:
            _recompute_bill_payment_status(payment.vendor_bill)

        return payment
