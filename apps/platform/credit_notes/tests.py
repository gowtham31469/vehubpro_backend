"""
Tests for CreditNoteService — generation (full/partial), the over-credit and
line-level double-credit guards, the amount_paid/payment_status interaction
(and that the InvoicePayment ledger is never touched), refund tracking, and
cancellation. Plain TestCase, no pytest — mirrors apps.platform.invoices.tests's
style (service-layer calls, not API client).
"""
from decimal import Decimal

from django.test import TestCase

from apps.platform.credit_notes.models import CreditNote
from apps.platform.credit_notes.service import (
    CreditNoteAlreadyCancelled,
    CreditNoteAlreadyRefunded,
    CreditNoteService,
    InvalidCreditNoteRefundState,
    InvalidLineItemReference,
    InvoiceIsCancelled,
    NoCreditTargetSpecified,
    OverCreditError,
)
from apps.platform.customers.models import Customer
from apps.platform.invoices.models import Invoice
from apps.platform.invoices.service import InvoiceService
from apps.platform.jobcards.models import JobCard, JobCardLineItem
from apps.platform.tenants.models import Tenant
from apps.platform.vehicles.models import FuelType, ServiceVehicle, VehicleBrand, VehicleModel, VehicleType


class CreditNoteTestBase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Garage CN", domain="test-garage-cn.vehubpro.com")
        self.customer = Customer.objects.create(
            tenant=self.tenant, full_name="Test Customer CN", phone="+919888888888"
        )
        vehicle_type, _ = VehicleType.objects.get_or_create(code="cn_test_car", defaults={"name": "CN Test Car"})
        fuel_type, _ = FuelType.objects.get_or_create(code="cn_test_petrol", defaults={"name": "CN Test Petrol"})
        brand = VehicleBrand.objects.create(tenant=self.tenant, name="CNTestBrand")
        vehicle_model = VehicleModel.objects.create(
            tenant=self.tenant, brand=brand, vehicle_type=vehicle_type, name="CNTestModel"
        )
        self.vehicle = ServiceVehicle.objects.create(
            tenant=self.tenant, customer=self.customer, registration_no="CNTST0001",
            vehicle_type=vehicle_type, brand=brand, vehicle_model=vehicle_model,
            year=2024, fuel_type=fuel_type,
        )

    def _make_invoice(self, suffix: str) -> Invoice:
        """Completed job card with two 18%-GST lines (labour 1000, part 500) → invoiced."""
        job_card = JobCard.objects.create(
            tenant=self.tenant, jobcard_number=f"JC-CN-{suffix}", customer=self.customer, vehicle=self.vehicle,
            subtotal=Decimal("1500.00"), cgst_amount=Decimal("135.00"), sgst_amount=Decimal("135.00"),
            total_amount=Decimal("1770.00"), status=JobCard.STATUS_COMPLETED,
        )
        JobCardLineItem.objects.create(
            job_card=job_card, sort_order=0, service_type=JobCardLineItem.SERVICE_TYPE_LABOUR,
            description="Labour A", quantity=Decimal("1"), unit_price=Decimal("1000.00"),
            gst_percentage=Decimal("18.00"), cgst_amount=Decimal("90.00"), sgst_amount=Decimal("90.00"),
            line_total=Decimal("1000.00"),
        )
        JobCardLineItem.objects.create(
            job_card=job_card, sort_order=1, service_type=JobCardLineItem.SERVICE_TYPE_PART,
            description="Part B", quantity=Decimal("1"), unit_price=Decimal("500.00"),
            gst_percentage=Decimal("18.00"), cgst_amount=Decimal("45.00"), sgst_amount=Decimal("45.00"),
            line_total=Decimal("500.00"),
        )
        return InvoiceService.generate(job_card, issued_by=None)


class CreditNoteGenerationTests(CreditNoteTestBase):
    def test_full_invoice_credit_note(self):
        invoice = self._make_invoice("full")
        credit_note = CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("1500.00"), custom_gst_percentage=Decimal("18.00"),
            reason="Job cancelled after invoicing",
        )
        self.assertEqual(credit_note.status, CreditNote.STATUS_ISSUED)
        self.assertEqual(credit_note.total_amount, Decimal("1770.00"))
        self.assertEqual(credit_note.credit_note_number.split("/")[0], "CN")

    def test_partial_line_item_credit_note_scales_tax_proportionally(self):
        invoice = self._make_invoice("partial")
        labour_line = invoice.line_items.get(description="Labour A")
        credit_note = CreditNoteService.generate(
            invoice, created_by=None,
            line_item_credits=[{"invoice_line_item_id": labour_line.id, "amount": Decimal("500.00")}],
            reason="Half the labour was redone for free",
        )
        line = credit_note.line_items.get()
        self.assertEqual(line.line_total, Decimal("500.00"))
        # Half of the line's own stored cgst/sgst (90/90), not a fresh recompute.
        self.assertEqual(line.cgst_amount, Decimal("45.00"))
        self.assertEqual(line.sgst_amount, Decimal("45.00"))
        self.assertEqual(credit_note.total_amount, Decimal("590.00"))

    def test_custom_amount_defaults_to_zero_gst(self):
        invoice = self._make_invoice("customgst")
        credit_note = CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("100.00"), reason="Goodwill",
        )
        self.assertEqual(credit_note.cgst_amount, Decimal("0.00"))
        self.assertEqual(credit_note.total_amount, Decimal("100.00"))

    def test_no_credit_target_raises(self):
        invoice = self._make_invoice("notarget")
        with self.assertRaises(NoCreditTargetSpecified):
            CreditNoteService.generate(invoice, created_by=None, reason="nothing to credit")

    def test_invalid_line_item_reference_raises(self):
        invoice_a = self._make_invoice("a")
        invoice_b = self._make_invoice("b")
        other_line = invoice_b.line_items.first()
        with self.assertRaises(InvalidLineItemReference):
            CreditNoteService.generate(
                invoice_a, created_by=None,
                line_item_credits=[{"invoice_line_item_id": other_line.id, "amount": Decimal("10.00")}],
                reason="wrong invoice's line",
            )

    def test_cancelled_invoice_cannot_be_credited(self):
        invoice = self._make_invoice("cancelled")
        Invoice.objects.filter(pk=invoice.pk).update(is_cancelled=True)
        invoice.refresh_from_db()
        with self.assertRaises(InvoiceIsCancelled):
            CreditNoteService.generate(invoice, created_by=None, custom_amount=Decimal("10.00"), reason="x")

    def test_over_credit_rejected(self):
        invoice = self._make_invoice("overcredit")
        CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("1700.00"), reason="first big credit",
        )
        with self.assertRaises(OverCreditError):
            CreditNoteService.generate(
                invoice, created_by=None, custom_amount=Decimal("100.00"), reason="pushes it over",
            )
        self.assertEqual(CreditNote.objects.filter(invoice=invoice).count(), 1)

    def test_line_level_double_credit_rejected_even_if_header_remaining_allows_it(self):
        invoice = self._make_invoice("doublecredit")
        labour_line = invoice.line_items.get(description="Labour A")
        CreditNoteService.generate(
            invoice, created_by=None,
            line_item_credits=[{"invoice_line_item_id": labour_line.id, "amount": Decimal("1000.00")}],
            reason="full labour line credited",
        )
        # Header-level remaining is still 1770 - 1180 = 590 (plenty), but this
        # specific line has nothing left — must still be rejected.
        with self.assertRaises(OverCreditError):
            CreditNoteService.generate(
                invoice, created_by=None,
                line_item_credits=[{"invoice_line_item_id": labour_line.id, "amount": Decimal("1.00")}],
                reason="double-dip the same line",
            )


class CreditNoteInvoiceReconciliationTests(CreditNoteTestBase):
    def test_amount_paid_untouched_and_payment_status_recomputed_when_already_paid(self):
        invoice = self._make_invoice("paidrecon")
        invoice = InvoiceService.record_payment(
            invoice, payment_mode=Invoice.PAYMENT_MODE_CASH, amount_paid=Decimal("1770.00"), recorded_by=None,
        )
        self.assertEqual(invoice.payment_status, Invoice.PAYMENT_STATUS_PAID)

        credit_note = CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("200.00"), reason="Discount after full payment",
        )
        invoice.refresh_from_db()

        # Ledger invariant: amount_paid must never change because of a credit note.
        self.assertEqual(invoice.amount_paid, Decimal("1770.00"))
        # Effective total is now 1570 — amount_paid (1770) still covers it, so still "paid",
        # and the excess becomes a tracked refund.
        self.assertEqual(invoice.payment_status, Invoice.PAYMENT_STATUS_PAID)
        self.assertTrue(credit_note.is_refund_applicable)
        self.assertEqual(credit_note.refund_amount, Decimal("200.00"))
        self.assertEqual(credit_note.refund_status, CreditNote.REFUND_STATUS_PENDING)

    def test_no_refund_applicable_when_invoice_unpaid(self):
        invoice = self._make_invoice("unpaidrecon")
        credit_note = CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("200.00"), reason="Discount, never paid",
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal("0.00"))
        self.assertEqual(invoice.payment_status, Invoice.PAYMENT_STATUS_UNPAID)
        self.assertFalse(credit_note.is_refund_applicable)
        self.assertEqual(credit_note.refund_status, CreditNote.REFUND_STATUS_NOT_APPLICABLE)

    def test_partial_payment_recomputes_to_paid_once_credited_enough(self):
        invoice = self._make_invoice("partialpay")
        invoice = InvoiceService.record_payment(
            invoice, payment_mode=Invoice.PAYMENT_MODE_CASH, amount_paid=Decimal("1000.00"), recorded_by=None,
        )
        self.assertEqual(invoice.payment_status, Invoice.PAYMENT_STATUS_PARTIAL)

        CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("770.00"), reason="Reduce remaining balance to match paid",
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal("1000.00"))
        self.assertEqual(invoice.payment_status, Invoice.PAYMENT_STATUS_PAID)


class CreditNoteRefundAndCancelTests(CreditNoteTestBase):
    def test_mark_refunded_transition_and_guards(self):
        invoice = self._make_invoice("refundtrans")
        InvoiceService.record_payment(
            invoice, payment_mode=Invoice.PAYMENT_MODE_CASH, amount_paid=Decimal("1770.00"), recorded_by=None,
        )
        credit_note = CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("200.00"), reason="Overpaid, need refund",
        )
        self.assertTrue(credit_note.is_refund_applicable)

        credit_note = CreditNoteService.mark_refunded(credit_note, reason="Cash handed back")
        self.assertEqual(credit_note.refund_status, CreditNote.REFUND_STATUS_REFUNDED)
        self.assertIsNotNone(credit_note.refunded_at)

        with self.assertRaises(InvalidCreditNoteRefundState):
            CreditNoteService.mark_refunded(credit_note, reason="again")

    def test_mark_refunded_on_non_applicable_raises(self):
        invoice = self._make_invoice("refundnotapplicable")
        credit_note = CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("100.00"), reason="No payment yet",
        )
        with self.assertRaises(InvalidCreditNoteRefundState):
            CreditNoteService.mark_refunded(credit_note)

    def test_cancellation_reverses_credit_and_recomputes_invoice(self):
        invoice = self._make_invoice("cancelreverse")
        credit_note = CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("1770.00"), reason="Full credit issued in error",
        )
        invoice.refresh_from_db()

        credit_note = CreditNoteService.cancel(credit_note, cancelled_by=None, reason="Issued in error")
        self.assertEqual(credit_note.status, CreditNote.STATUS_CANCELLED)

        # The cancelled note's amount must drop out of the "already credited"
        # pool — a fresh credit note for the same amount must now succeed.
        second = CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("1770.00"), reason="Reissued correctly",
        )
        self.assertEqual(second.total_amount, Decimal("1770.00"))

    def test_cannot_cancel_already_cancelled(self):
        invoice = self._make_invoice("doublecancel")
        credit_note = CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("100.00"), reason="x",
        )
        CreditNoteService.cancel(credit_note, cancelled_by=None, reason="first cancel")
        with self.assertRaises(CreditNoteAlreadyCancelled):
            CreditNoteService.cancel(credit_note, cancelled_by=None, reason="second cancel")

    def test_cannot_cancel_already_refunded(self):
        invoice = self._make_invoice("cancelrefunded")
        InvoiceService.record_payment(
            invoice, payment_mode=Invoice.PAYMENT_MODE_CASH, amount_paid=Decimal("1770.00"), recorded_by=None,
        )
        credit_note = CreditNoteService.generate(
            invoice, created_by=None, custom_amount=Decimal("200.00"), reason="x",
        )
        CreditNoteService.mark_refunded(credit_note)
        with self.assertRaises(CreditNoteAlreadyRefunded):
            CreditNoteService.cancel(credit_note, cancelled_by=None, reason="too late")


class CreditNoteNumberingTests(CreditNoteTestBase):
    def test_sequence_numbers_increase_without_gaps(self):
        invoice = self._make_invoice("numbering")
        numbers = []
        for i in range(3):
            credit_note = CreditNoteService.generate(
                invoice, created_by=None, custom_amount=Decimal("1.00"), reason=f"small credit {i}",
            )
            numbers.append(credit_note.sequence_no)
        self.assertEqual(numbers, [1, 2, 3])
        first = CreditNote.objects.get(sequence_no=1, invoice=invoice)
        self.assertTrue(first.credit_note_number.startswith("CN/"))
