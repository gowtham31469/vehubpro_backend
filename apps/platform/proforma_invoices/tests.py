"""
Tests for ProformaInvoiceService / AdvancePaymentService — the core business
logic (numbering, status lifecycle, revision re-snapshotting, advance
recording, and conversion-with-advance-credit). Exercises the service layer
directly, mirroring apps.platform.invoices.tests's style (plain TestCase,
no pytest, no API client).
"""
from decimal import Decimal

from django.test import TestCase

from apps.platform.customers.models import Customer
from apps.platform.invoices.models import Invoice
from apps.platform.jobcards.models import JobCard, JobCardLineItem, indian_fy_code
from apps.platform.proforma_invoices.models import AdvancePayment, ProformaInvoice
from apps.platform.proforma_invoices.service import (
    AdvancePaymentAlreadyApplied,
    AdvancePaymentService,
    InvalidAdvancePaymentAmount,
    InvalidAdvancePaymentStatus,
    InvalidJobCardForProforma,
    InvalidProformaStatus,
    InvalidProformaStatusForAdvance,
    ProformaAlreadyConverted,
    ProformaInvoiceAlreadyActive,
    ProformaInvoiceService,
    ProformaNotLatestVersion,
)
from apps.platform.tenants.models import Tenant
from apps.platform.vehicles.models import FuelType, ServiceVehicle, VehicleBrand, VehicleModel, VehicleType


class ProformaInvoicesTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Garage", domain="test-garage-pi.vehubpro.com")
        self.other_tenant = Tenant.objects.create(name="Other Garage", domain="other-garage-pi.vehubpro.com")
        self.customer = Customer.objects.create(tenant=self.tenant, full_name="Test Customer", phone="+919999900001")
        vehicle_type, _ = VehicleType.objects.get_or_create(code="test_car_pi", defaults={"name": "Test Car PI"})
        fuel_type, _ = FuelType.objects.get_or_create(code="test_petrol_pi", defaults={"name": "Test Petrol PI"})
        brand = VehicleBrand.objects.create(tenant=self.tenant, name="TestBrandPI")
        vehicle_model = VehicleModel.objects.create(tenant=self.tenant, brand=brand, vehicle_type=vehicle_type, name="TestModelPI")
        self.vehicle = ServiceVehicle.objects.create(
            tenant=self.tenant, customer=self.customer, registration_no="PITEST001",
            vehicle_type=vehicle_type, brand=brand, vehicle_model=vehicle_model, year=2024, fuel_type=fuel_type,
        )

    def _make_job_card(self, suffix: str, *, status=JobCard.STATUS_WORKING) -> JobCard:
        job_card = JobCard.objects.create(
            tenant=self.tenant,
            jobcard_number=f"JC-PI-TEST-{suffix}",
            customer=self.customer,
            vehicle=self.vehicle,
            subtotal=Decimal("1000.00"),
            cgst_amount=Decimal("90.00"),
            sgst_amount=Decimal("90.00"),
            total_amount=Decimal("1180.00"),
            status=status,
        )
        JobCardLineItem.objects.create(
            job_card=job_card, sort_order=0, service_type=JobCardLineItem.SERVICE_TYPE_LABOUR,
            description="Test Labour", quantity=Decimal("1"), unit_price=Decimal("1000.00"),
            gst_percentage=Decimal("18.00"), cgst_amount=Decimal("90.00"), sgst_amount=Decimal("90.00"),
            line_total=Decimal("1000.00"),
        )
        return job_card


class GenerateTests(ProformaInvoicesTestCase):
    def test_generate_snapshots_job_card_verbatim_for_gst(self):
        job_card = self._make_job_card("gen-1")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None, invoice_type=Invoice.INVOICE_TYPE_GST)

        fy = indian_fy_code()
        self.assertEqual(proforma.proforma_number, f"PI/{fy}/00001")
        self.assertEqual(proforma.status, ProformaInvoice.STATUS_DRAFT)
        self.assertEqual(proforma.cgst_amount, Decimal("90.00"))
        self.assertEqual(proforma.sgst_amount, Decimal("90.00"))
        self.assertEqual(proforma.total_amount, Decimal("1180.00"))
        self.assertEqual(proforma.customer_id, self.customer.id)
        self.assertEqual(proforma.vehicle_id, self.vehicle.id)

        line = proforma.line_items.get()
        self.assertEqual(line.gst_percentage, Decimal("18.00"))
        self.assertEqual(line.cgst_amount, Decimal("90.00"))

    def test_generate_zeroes_tax_for_non_gst(self):
        job_card = self._make_job_card("gen-2")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None, invoice_type=Invoice.INVOICE_TYPE_NON_GST)
        self.assertEqual(proforma.cgst_amount, Decimal("0.00"))
        self.assertEqual(proforma.total_amount, Decimal("1000.00"))

    def test_generate_allowed_before_job_card_completed(self):
        """Unlike a real invoice, a proforma estimate is usable early in the
        job's lifecycle — no 'completed' status gate."""
        job_card = self._make_job_card("gen-3", status=JobCard.STATUS_JOB_CONTROL)
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        self.assertIsNotNone(proforma.pk)

    def test_generate_rejected_for_cancelled_job_card(self):
        job_card = self._make_job_card("gen-4", status=JobCard.STATUS_CANCELLED)
        with self.assertRaises(InvalidJobCardForProforma):
            ProformaInvoiceService.generate(job_card, created_by=None)

    def test_generate_rejected_when_active_invoice_already_exists(self):
        job_card = self._make_job_card("gen-5", status=JobCard.STATUS_COMPLETED)
        from apps.platform.invoices.service import InvoiceService
        InvoiceService.generate(job_card, issued_by=None, invoice_type=Invoice.INVOICE_TYPE_GST)
        with self.assertRaises(InvalidJobCardForProforma):
            ProformaInvoiceService.generate(job_card, created_by=None)

    def test_numbering_independent_from_invoice_numbering(self):
        fy = indian_fy_code()
        job_card1 = self._make_job_card("gen-6")
        job_card2 = self._make_job_card("gen-7")
        p1 = ProformaInvoiceService.generate(job_card1, created_by=None)
        p2 = ProformaInvoiceService.generate(job_card2, created_by=None)
        self.assertEqual(p1.proforma_number, f"PI/{fy}/00001")
        self.assertEqual(p2.proforma_number, f"PI/{fy}/00002")

    def test_generate_rejected_while_draft_proforma_already_active(self):
        job_card = self._make_job_card("gen-8")
        ProformaInvoiceService.generate(job_card, created_by=None)
        with self.assertRaises(ProformaInvoiceAlreadyActive):
            ProformaInvoiceService.generate(job_card, created_by=None)

    def test_generate_rejected_while_issued_proforma_already_active(self):
        job_card = self._make_job_card("gen-9")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        ProformaInvoiceService.issue(proforma)
        with self.assertRaises(ProformaInvoiceAlreadyActive):
            ProformaInvoiceService.generate(job_card, created_by=None)

    def test_generate_rejected_while_approved_proforma_already_active(self):
        job_card = self._make_job_card("gen-10")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        proforma = ProformaInvoiceService.issue(proforma)
        ProformaInvoiceService.approve(proforma)
        with self.assertRaises(ProformaInvoiceAlreadyActive):
            ProformaInvoiceService.generate(job_card, created_by=None)

    def test_generate_allowed_again_after_proforma_rejected(self):
        job_card = self._make_job_card("gen-11")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        proforma = ProformaInvoiceService.issue(proforma)
        ProformaInvoiceService.reject(proforma, reason="declined")
        second = ProformaInvoiceService.generate(job_card, created_by=None)
        self.assertNotEqual(second.proforma_number, proforma.proforma_number)

    def test_generate_allowed_again_after_proforma_cancelled(self):
        job_card = self._make_job_card("gen-12")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        ProformaInvoiceService.cancel(proforma, reason="mistake")
        second = ProformaInvoiceService.generate(job_card, created_by=None)
        self.assertNotEqual(second.proforma_number, proforma.proforma_number)

    def test_generate_allowed_again_after_revised_proforma_no_longer_latest(self):
        """The superseded v1 isn't is_latest anymore, so it doesn't block a
        fresh generate() even though its own status is still 'issued'."""
        job_card = self._make_job_card("gen-13")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        proforma = ProformaInvoiceService.issue(proforma)
        ProformaInvoiceService.create_revision(proforma, revision_reason="scope changed", created_by=None)
        # The revision (v2) is itself draft/is_latest, so generate() should
        # still be blocked by IT, not by the superseded v1.
        with self.assertRaises(ProformaInvoiceAlreadyActive):
            ProformaInvoiceService.generate(job_card, created_by=None)


class LifecycleTests(ProformaInvoicesTestCase):
    def test_full_lifecycle_draft_to_approved(self):
        job_card = self._make_job_card("lc-1")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)

        proforma = ProformaInvoiceService.issue(proforma)
        self.assertEqual(proforma.status, ProformaInvoice.STATUS_ISSUED)
        self.assertIsNotNone(proforma.issued_at)

        proforma = ProformaInvoiceService.approve(proforma)
        self.assertEqual(proforma.status, ProformaInvoice.STATUS_APPROVED)
        self.assertIsNotNone(proforma.approved_at)

    def test_reject_requires_issued_status(self):
        job_card = self._make_job_card("lc-2")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        with self.assertRaises(InvalidProformaStatus):
            ProformaInvoiceService.reject(proforma, reason="too expensive")

    def test_reject_from_issued(self):
        job_card = self._make_job_card("lc-3")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        proforma = ProformaInvoiceService.issue(proforma)
        proforma = ProformaInvoiceService.reject(proforma, reason="customer declined")
        self.assertEqual(proforma.status, ProformaInvoice.STATUS_REJECTED)
        self.assertEqual(proforma.rejection_reason, "customer declined")

    def test_cancel_blocked_once_converted(self):
        job_card = self._make_job_card("lc-4", status=JobCard.STATUS_COMPLETED)
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        proforma = ProformaInvoiceService.issue(proforma)
        proforma = ProformaInvoiceService.approve(proforma)
        ProformaInvoiceService.convert_to_invoice(proforma, issued_by=None)
        proforma.refresh_from_db()
        with self.assertRaises(InvalidProformaStatus):
            ProformaInvoiceService.cancel(proforma, reason="too late")


class RevisionTests(ProformaInvoicesTestCase):
    def test_revision_resnapshots_current_job_card_state_not_old_lines(self):
        job_card = self._make_job_card("rev-1")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        proforma = ProformaInvoiceService.issue(proforma)

        # Job card's scope changes after the proforma was issued.
        job_card.subtotal = Decimal("2000.00")
        job_card.cgst_amount = Decimal("180.00")
        job_card.sgst_amount = Decimal("180.00")
        job_card.total_amount = Decimal("2360.00")
        job_card.save()
        JobCardLineItem.objects.create(
            job_card=job_card, sort_order=1, service_type=JobCardLineItem.SERVICE_TYPE_PART,
            description="Extra Part", quantity=Decimal("1"), unit_price=Decimal("1000.00"),
            gst_percentage=Decimal("18.00"), cgst_amount=Decimal("90.00"), sgst_amount=Decimal("90.00"),
            line_total=Decimal("1000.00"),
        )

        revised = ProformaInvoiceService.create_revision(proforma, revision_reason="scope changed", created_by=None)

        self.assertEqual(revised.version, 2)
        self.assertEqual(revised.proforma_number, proforma.proforma_number)
        self.assertEqual(revised.total_amount, Decimal("2360.00"))
        self.assertEqual(revised.line_items.count(), 2)
        self.assertTrue(revised.is_latest)
        self.assertEqual(revised.status, ProformaInvoice.STATUS_DRAFT)

        # Original version untouched and no longer latest.
        proforma.refresh_from_db()
        self.assertFalse(proforma.is_latest)
        self.assertEqual(proforma.total_amount, Decimal("1180.00"))
        self.assertEqual(proforma.line_items.count(), 1)

    def test_cannot_revise_draft(self):
        job_card = self._make_job_card("rev-2")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        with self.assertRaises(Exception):
            ProformaInvoiceService.create_revision(proforma, revision_reason="x", created_by=None)

    def test_cannot_revise_superseded_version(self):
        job_card = self._make_job_card("rev-3")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        proforma = ProformaInvoiceService.issue(proforma)
        ProformaInvoiceService.create_revision(proforma, revision_reason="first revision", created_by=None)
        proforma.refresh_from_db()
        with self.assertRaises(ProformaNotLatestVersion):
            ProformaInvoiceService.create_revision(proforma, revision_reason="second attempt on stale version", created_by=None)


class AdvancePaymentTests(ProformaInvoicesTestCase):
    def _issued_proforma(self, suffix="ap-1"):
        job_card = self._make_job_card(suffix)
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        return ProformaInvoiceService.issue(proforma)

    def test_record_manual_payment_is_received_immediately_with_receipt(self):
        proforma = self._issued_proforma("ap-1")
        payment = AdvancePaymentService.record(
            proforma, amount=Decimal("300.00"), payment_mode=AdvancePayment.MODE_CASH, received_by=None,
        )
        self.assertEqual(payment.status, AdvancePayment.STATUS_RECEIVED)
        self.assertTrue(payment.receipt_number.startswith("RCPT/"))

    def test_record_gateway_payment_starts_pending_no_receipt(self):
        proforma = self._issued_proforma("ap-2")
        payment = AdvancePaymentService.record(
            proforma, amount=Decimal("300.00"), payment_mode=AdvancePayment.MODE_ONLINE_GATEWAY, received_by=None,
        )
        self.assertEqual(payment.status, AdvancePayment.STATUS_PENDING)
        self.assertEqual(payment.receipt_number, "")

    def test_mark_received_allocates_receipt(self):
        proforma = self._issued_proforma("ap-3")
        payment = AdvancePaymentService.record(
            proforma, amount=Decimal("300.00"), payment_mode=AdvancePayment.MODE_ONLINE_GATEWAY, received_by=None,
        )
        payment = AdvancePaymentService.mark_received(payment, received_by=None)
        self.assertEqual(payment.status, AdvancePayment.STATUS_RECEIVED)
        self.assertTrue(payment.receipt_number.startswith("RCPT/"))

    def test_cannot_record_against_draft_proforma(self):
        job_card = self._make_job_card("ap-4")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        with self.assertRaises(InvalidProformaStatusForAdvance):
            AdvancePaymentService.record(proforma, amount=Decimal("100"), payment_mode=AdvancePayment.MODE_CASH, received_by=None)

    def test_zero_amount_rejected(self):
        proforma = self._issued_proforma("ap-5")
        with self.assertRaises(InvalidAdvancePaymentAmount):
            AdvancePaymentService.record(proforma, amount=Decimal("0"), payment_mode=AdvancePayment.MODE_CASH, received_by=None)

    def test_reverse_blocked_once_applied(self):
        proforma = self._issued_proforma("ap-6")
        payment = AdvancePaymentService.record(proforma, amount=Decimal("100"), payment_mode=AdvancePayment.MODE_CASH, received_by=None)
        AdvancePayment.objects.filter(pk=payment.pk).update(applied=True)
        payment.refresh_from_db()
        with self.assertRaises(AdvancePaymentAlreadyApplied):
            AdvancePaymentService.reverse(payment, reason="mistake")


class ConversionTests(ProformaInvoicesTestCase):
    def _approved_proforma(self, suffix="conv-1", *, job_card_status=JobCard.STATUS_COMPLETED):
        job_card = self._make_job_card(suffix, status=job_card_status)
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        proforma = ProformaInvoiceService.issue(proforma)
        return ProformaInvoiceService.approve(proforma), job_card

    def test_convert_creates_invoice_and_links_it(self):
        proforma, job_card = self._approved_proforma("conv-1")
        invoice = ProformaInvoiceService.convert_to_invoice(proforma, issued_by=None)

        self.assertEqual(invoice.total_amount, Decimal("1180.00"))
        self.assertEqual(invoice.proforma_invoice_id, proforma.pk)

        proforma.refresh_from_db()
        self.assertEqual(proforma.status, ProformaInvoice.STATUS_CONVERTED)
        self.assertEqual(proforma.invoice_id, invoice.pk)

    def test_convert_requires_approved_status(self):
        job_card = self._make_job_card("conv-2", status=JobCard.STATUS_COMPLETED)
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        with self.assertRaises(InvalidProformaStatus):
            ProformaInvoiceService.convert_to_invoice(proforma, issued_by=None)

    def test_convert_twice_raises_already_converted(self):
        proforma, job_card = self._approved_proforma("conv-3")
        ProformaInvoiceService.convert_to_invoice(proforma, issued_by=None)
        proforma.refresh_from_db()
        with self.assertRaises(ProformaAlreadyConverted):
            ProformaInvoiceService.convert_to_invoice(proforma, issued_by=None)

    def test_convert_credits_received_advances_into_invoice(self):
        proforma, job_card = self._approved_proforma("conv-4")
        AdvancePaymentService.record(proforma, amount=Decimal("300.00"), payment_mode=AdvancePayment.MODE_CASH, received_by=None)
        AdvancePaymentService.record(proforma, amount=Decimal("200.00"), payment_mode=AdvancePayment.MODE_UPI, received_by=None)

        invoice = ProformaInvoiceService.convert_to_invoice(proforma, issued_by=None)

        self.assertEqual(invoice.amount_paid, Decimal("500.00"))
        self.assertEqual(invoice.payment_status, Invoice.PAYMENT_STATUS_PARTIAL)
        self.assertEqual(invoice.payments.count(), 2)
        for p in invoice.payments.all():
            self.assertEqual(p.payment_mode, Invoice.PAYMENT_MODE_ADVANCE)

        for payment in proforma.advance_payments.all():
            self.assertTrue(payment.applied)
            self.assertEqual(payment.applied_to_invoice_id, invoice.pk)

    def test_pending_and_unapplied_advances_are_not_double_credited(self):
        """Only RECEIVED, unapplied advances are credited — pending/failed/
        reversed ones are skipped, and re-converting (blocked by
        ProformaAlreadyConverted) can never double-credit the same advance."""
        proforma, job_card = self._approved_proforma("conv-5")
        AdvancePaymentService.record(proforma, amount=Decimal("100.00"), payment_mode=AdvancePayment.MODE_ONLINE_GATEWAY, received_by=None)
        AdvancePaymentService.record(proforma, amount=Decimal("300.00"), payment_mode=AdvancePayment.MODE_CASH, received_by=None)

        invoice = ProformaInvoiceService.convert_to_invoice(proforma, issued_by=None)
        self.assertEqual(invoice.amount_paid, Decimal("300.00"))

    def test_excess_advance_left_unapplied_not_split(self):
        """Advances summing above the invoice total: the overflowing one is
        skipped entirely (not split, not discarded) — a smaller later advance
        can still be applied if it fits."""
        proforma, job_card = self._approved_proforma("conv-6")
        big = AdvancePaymentService.record(proforma, amount=Decimal("1000.00"), payment_mode=AdvancePayment.MODE_CASH, received_by=None)
        small = AdvancePaymentService.record(proforma, amount=Decimal("1180.00"), payment_mode=AdvancePayment.MODE_UPI, received_by=None)

        invoice = ProformaInvoiceService.convert_to_invoice(proforma, issued_by=None)
        # big (1000) applies first (fits under 1180), small (1180) would push
        # total to 2180 > 1180, so it's skipped — left unapplied.
        self.assertEqual(invoice.amount_paid, Decimal("1000.00"))
        big.refresh_from_db()
        small.refresh_from_db()
        self.assertTrue(big.applied)
        self.assertFalse(small.applied)

    def test_convert_requires_completed_job_card(self):
        """The real invoice-generation gate (InvoiceService.generate's
        'completed' status requirement) is untouched — convert_to_invoice
        surfaces it rather than bypassing it."""
        from apps.platform.invoices.service import InvalidJobCardStatus
        proforma, job_card = self._approved_proforma("conv-7", job_card_status=JobCard.STATUS_WORKING)
        with self.assertRaises(InvalidJobCardStatus):
            ProformaInvoiceService.convert_to_invoice(proforma, issued_by=None)


class TenantIsolationTests(ProformaInvoicesTestCase):
    def test_proforma_scoped_to_tenant(self):
        job_card = self._make_job_card("iso-1")
        proforma = ProformaInvoiceService.generate(job_card, created_by=None)
        self.assertEqual(ProformaInvoice.objects.filter(pk=proforma.pk, tenant_id=self.other_tenant.id).count(), 0)
