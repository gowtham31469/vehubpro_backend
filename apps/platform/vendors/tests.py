"""
Tests for VendorBillService/VendorPaymentService — bill generation (intrastate
and interstate GST math, TDS), tied and on-account payment recording, the
over-payment guard, voiding, cancellation, and the outstanding-balance helper.
Plain TestCase, no pytest — mirrors apps.platform.credit_notes.tests's style.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.platform.tenants.models import Tenant
from apps.platform.vendors.models import Vendor, VendorBill, VendorPayment
from apps.platform.vendors.service import (
    InvalidVendorBillReference,
    OverPaymentError,
    VendorBillAlreadyCancelled,
    VendorBillHasPayments,
    VendorBillService,
    VendorPaymentAlreadyVoided,
    VendorPaymentService,
    vendor_outstanding_balance,
)


class VendorTestBase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Garage VEN", domain="test-garage-ven.vehubpro.com")
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, name="Acme Spares", category="Parts Supplier",
            payment_terms_days=30,
        )


class VendorMasterTests(VendorTestBase):
    def test_duplicate_name_rejected_case_insensitively(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vendor.objects.create(tenant=self.tenant, name="acme spares")

    def test_archived_vendor_name_can_be_reused(self):
        self.vendor.archive()
        Vendor.objects.create(tenant=self.tenant, name="Acme Spares")  # should not raise


class VendorBillGenerationTests(VendorTestBase):
    def test_intrastate_bill_splits_cgst_sgst_and_deducts_tds(self):
        bill = VendorBillService.generate(
            self.vendor, created_by=None, bill_date=date(2026, 1, 15),
            subtotal=Decimal("1000.00"), gst_percentage=Decimal("18.00"), is_interstate=False,
            tds_percentage=Decimal("10.00"),
        )
        self.assertEqual(bill.cgst_amount, Decimal("90.00"))
        self.assertEqual(bill.sgst_amount, Decimal("90.00"))
        self.assertEqual(bill.igst_amount, Decimal("0.00"))
        self.assertEqual(bill.total_amount, Decimal("1180.00"))
        self.assertEqual(bill.tds_amount, Decimal("100.00"))
        self.assertEqual(bill.net_payable_amount, Decimal("1080.00"))
        self.assertEqual(bill.bill_number.split("/")[0], "VB")
        # due_date defaults from vendor.payment_terms_days
        self.assertEqual(bill.due_date, date(2026, 2, 14))

    def test_interstate_bill_uses_igst_only(self):
        bill = VendorBillService.generate(
            self.vendor, created_by=None, bill_date=date(2026, 1, 15),
            subtotal=Decimal("1000.00"), gst_percentage=Decimal("18.00"), is_interstate=True,
        )
        self.assertEqual(bill.cgst_amount, Decimal("0.00"))
        self.assertEqual(bill.sgst_amount, Decimal("0.00"))
        self.assertEqual(bill.igst_amount, Decimal("180.00"))
        self.assertEqual(bill.total_amount, Decimal("1180.00"))

    def test_bill_numbering_is_sequential(self):
        numbers = [
            VendorBillService.generate(
                self.vendor, created_by=None, bill_date=date(2026, 1, 1), subtotal=Decimal("100.00"),
            ).bill_number
            for _ in range(3)
        ]
        sequences = [int(n.split("/")[-1]) for n in numbers]
        self.assertEqual(sequences, [1, 2, 3])


class VendorPaymentTests(VendorTestBase):
    def _bill(self, subtotal="1000.00", tds="0"):
        return VendorBillService.generate(
            self.vendor, created_by=None, bill_date=date(2026, 1, 15),
            subtotal=Decimal(subtotal), gst_percentage=Decimal("18.00"), is_interstate=False,
            tds_percentage=Decimal(tds),
        )

    def test_partial_then_full_payment_against_a_bill(self):
        bill = self._bill()  # net_payable = 1180.00
        VendorPaymentService.record(
            self.vendor, amount=Decimal("700.00"), payment_mode=VendorPayment.MODE_CASH,
            payment_date=date(2026, 1, 20), recorded_by=None, vendor_bill=bill,
        )
        bill.refresh_from_db()
        self.assertEqual(bill.payment_status, VendorBill.PAYMENT_STATUS_PARTIAL)
        self.assertEqual(bill.amount_paid, Decimal("700.00"))

        VendorPaymentService.record(
            self.vendor, amount=Decimal("480.00"), payment_mode=VendorPayment.MODE_BANK_TRANSFER,
            payment_date=date(2026, 1, 25), recorded_by=None, vendor_bill=bill,
        )
        bill.refresh_from_db()
        self.assertEqual(bill.payment_status, VendorBill.PAYMENT_STATUS_PAID)
        self.assertEqual(bill.amount_paid, Decimal("1180.00"))

    def test_overpayment_rejected_with_remaining_balance(self):
        bill = self._bill()
        with self.assertRaisesMessage(OverPaymentError, "1180.00"):
            VendorPaymentService.record(
                self.vendor, amount=Decimal("5000.00"), payment_mode=VendorPayment.MODE_CASH,
                payment_date=date(2026, 1, 20), recorded_by=None, vendor_bill=bill,
            )

    def test_payment_against_cancelled_bill_rejected(self):
        bill = self._bill()
        VendorBillService.cancel(bill, cancelled_by=None, reason="duplicate entry")
        with self.assertRaises(InvalidVendorBillReference):
            VendorPaymentService.record(
                self.vendor, amount=Decimal("100.00"), payment_mode=VendorPayment.MODE_CASH,
                payment_date=date(2026, 1, 20), recorded_by=None, vendor_bill=bill,
            )

    def test_on_account_payment_does_not_touch_any_bill(self):
        bill = self._bill()
        VendorPaymentService.record(
            self.vendor, amount=Decimal("300.00"), payment_mode=VendorPayment.MODE_UPI,
            payment_date=date(2026, 1, 20), recorded_by=None,
        )
        bill.refresh_from_db()
        self.assertEqual(bill.amount_paid, Decimal("0.00"))
        self.assertEqual(bill.payment_status, VendorBill.PAYMENT_STATUS_UNPAID)
        # outstanding balance: 1180 (bill) - 300 (on-account) = 880
        self.assertEqual(vendor_outstanding_balance(self.vendor), Decimal("880.00"))

    def test_voiding_a_payment_reverses_the_bills_aggregate(self):
        bill = self._bill()
        payment = VendorPaymentService.record(
            self.vendor, amount=Decimal("700.00"), payment_mode=VendorPayment.MODE_CASH,
            payment_date=date(2026, 1, 20), recorded_by=None, vendor_bill=bill,
        )
        bill.refresh_from_db()
        self.assertEqual(bill.payment_status, VendorBill.PAYMENT_STATUS_PARTIAL)

        VendorPaymentService.void(payment, voided_by=None, reason="entered against wrong bill")
        bill.refresh_from_db()
        self.assertEqual(bill.amount_paid, Decimal("0.00"))
        self.assertEqual(bill.payment_status, VendorBill.PAYMENT_STATUS_UNPAID)

        with self.assertRaises(VendorPaymentAlreadyVoided):
            VendorPaymentService.void(payment, voided_by=None)


class VendorBillCancellationTests(VendorTestBase):
    def test_cancel_unpaid_bill_succeeds(self):
        bill = VendorBillService.generate(
            self.vendor, created_by=None, bill_date=date(2026, 1, 1), subtotal=Decimal("100.00"),
        )
        VendorBillService.cancel(bill, cancelled_by=None, reason="wrong vendor")
        bill.refresh_from_db()
        self.assertEqual(bill.status, VendorBill.STATUS_CANCELLED)

        with self.assertRaises(VendorBillAlreadyCancelled):
            VendorBillService.cancel(bill, cancelled_by=None)

    def test_cancel_paid_bill_refused(self):
        bill = VendorBillService.generate(
            self.vendor, created_by=None, bill_date=date(2026, 1, 1), subtotal=Decimal("100.00"),
        )
        VendorPaymentService.record(
            self.vendor, amount=Decimal("100.00"), payment_mode=VendorPayment.MODE_CASH,
            payment_date=date(2026, 1, 2), recorded_by=None, vendor_bill=bill,
        )
        bill.refresh_from_db()
        with self.assertRaises(VendorBillHasPayments):
            VendorBillService.cancel(bill, cancelled_by=None)


class VendorOutstandingBalanceTests(VendorTestBase):
    def test_balance_across_multiple_bills_and_mixed_payments(self):
        bill1 = VendorBillService.generate(
            self.vendor, created_by=None, bill_date=date(2026, 1, 1), subtotal=Decimal("1000.00"),
        )  # net_payable 1000
        bill2 = VendorBillService.generate(
            self.vendor, created_by=None, bill_date=date(2026, 1, 1), subtotal=Decimal("500.00"),
        )  # net_payable 500

        VendorPaymentService.record(
            self.vendor, amount=Decimal("400.00"), payment_mode=VendorPayment.MODE_CASH,
            payment_date=date(2026, 1, 5), recorded_by=None, vendor_bill=bill1,
        )
        VendorPaymentService.record(
            self.vendor, amount=Decimal("200.00"), payment_mode=VendorPayment.MODE_CASH,
            payment_date=date(2026, 1, 6), recorded_by=None,
        )  # on-account

        # (1000-400) + (500-0) - 200 on-account = 900
        self.assertEqual(vendor_outstanding_balance(self.vendor), Decimal("900.00"))
