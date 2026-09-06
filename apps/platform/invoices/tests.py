"""
Tests for GST / Non-GST invoice generation and independent numbering sequences.

Covers InvoiceService.generate() directly (the core business logic), rather than
going through the API layer, since the numbering/tax-calculation rules live there.
"""
from decimal import Decimal

from django.test import TestCase

from apps.platform.customers.models import Customer
from apps.platform.invoices.models import Invoice
from apps.platform.invoices.service import InvalidJobCardStatus, InvoiceService
from apps.platform.jobcards.models import JobCard, JobCardLineItem, indian_fy_code
from apps.platform.tenants.models import Tenant
from apps.platform.vehicles.models import FuelType, ServiceVehicle, VehicleBrand, VehicleModel, VehicleType


class InvoiceGenerationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Garage", domain="test-garage.vehubpro.com")
        self.customer = Customer.objects.create(
            tenant=self.tenant, full_name="Test Customer", phone="+919999999999"
        )
        vehicle_type, _ = VehicleType.objects.get_or_create(code="test_car", defaults={"name": "Test Car"})
        fuel_type, _ = FuelType.objects.get_or_create(code="test_petrol", defaults={"name": "Test Petrol"})
        brand = VehicleBrand.objects.create(tenant=self.tenant, name="TestBrand")
        vehicle_model = VehicleModel.objects.create(
            tenant=self.tenant, brand=brand, vehicle_type=vehicle_type, name="TestModel"
        )
        self.vehicle = ServiceVehicle.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            registration_no="TEST0001",
            vehicle_type=vehicle_type,
            brand=brand,
            vehicle_model=vehicle_model,
            year=2024,
            fuel_type=fuel_type,
        )

    def _make_completed_job_card(self, suffix: str) -> JobCard:
        job_card = JobCard.objects.create(
            tenant=self.tenant,
            jobcard_number=f"JC-TEST-{suffix}",
            customer=self.customer,
            vehicle=self.vehicle,
            subtotal=Decimal("1000.00"),
            cgst_amount=Decimal("90.00"),
            sgst_amount=Decimal("90.00"),
            total_amount=Decimal("1180.00"),
            status=JobCard.STATUS_COMPLETED,
        )
        JobCardLineItem.objects.create(
            job_card=job_card,
            sort_order=0,
            service_type=JobCardLineItem.SERVICE_TYPE_LABOUR,
            description="Test Labour",
            quantity=Decimal("1"),
            unit_price=Decimal("1000.00"),
            gst_percentage=Decimal("18.00"),
            cgst_amount=Decimal("90.00"),
            sgst_amount=Decimal("90.00"),
            line_total=Decimal("1000.00"),
        )
        return job_card

    def test_gst_invoice_keeps_job_cards_tax_verbatim(self):
        job_card = self._make_completed_job_card("gst-1")
        invoice = InvoiceService.generate(job_card, issued_by=None, invoice_type=Invoice.INVOICE_TYPE_GST)

        fy = indian_fy_code()
        self.assertEqual(invoice.invoice_number, f"INV/{fy}/00001")
        self.assertEqual(invoice.invoice_type, Invoice.INVOICE_TYPE_GST)
        self.assertEqual(invoice.cgst_amount, Decimal("90.00"))
        self.assertEqual(invoice.sgst_amount, Decimal("90.00"))
        self.assertEqual(invoice.total_amount, Decimal("1180.00"))

        line = invoice.line_items.get()
        self.assertEqual(line.gst_percentage, Decimal("18.00"))
        self.assertEqual(line.cgst_amount, Decimal("90.00"))
        self.assertEqual(line.sgst_amount, Decimal("90.00"))

    def test_non_gst_invoice_zeroes_tax_and_recomputes_total(self):
        job_card = self._make_completed_job_card("nongst-1")
        invoice = InvoiceService.generate(job_card, issued_by=None, invoice_type=Invoice.INVOICE_TYPE_NON_GST)

        fy = indian_fy_code()
        self.assertEqual(invoice.invoice_number, f"INV-NGST/{fy}/00001")
        self.assertEqual(invoice.invoice_type, Invoice.INVOICE_TYPE_NON_GST)
        self.assertEqual(invoice.cgst_amount, Decimal("0.00"))
        self.assertEqual(invoice.sgst_amount, Decimal("0.00"))
        self.assertEqual(invoice.igst_amount, Decimal("0.00"))
        # Total drops the tax portion entirely: subtotal - discount + shop_fees.
        self.assertEqual(invoice.total_amount, Decimal("1000.00"))

        line = invoice.line_items.get()
        self.assertEqual(line.gst_percentage, Decimal("0.00"))
        self.assertEqual(line.cgst_amount, Decimal("0.00"))
        self.assertEqual(line.sgst_amount, Decimal("0.00"))
        # The pre-tax base figure is untouched.
        self.assertEqual(line.line_total, Decimal("1000.00"))

    def test_gst_and_non_gst_sequences_are_independent(self):
        """Mirrors the acceptance-criteria example table exactly."""
        fy = indian_fy_code()
        plan = [
            Invoice.INVOICE_TYPE_GST,
            Invoice.INVOICE_TYPE_GST,
            Invoice.INVOICE_TYPE_NON_GST,
            Invoice.INVOICE_TYPE_NON_GST,
            Invoice.INVOICE_TYPE_GST,
            Invoice.INVOICE_TYPE_NON_GST,
        ]
        numbers = []
        for i, invoice_type in enumerate(plan):
            job_card = self._make_completed_job_card(f"seq-{i}")
            invoice = InvoiceService.generate(job_card, issued_by=None, invoice_type=invoice_type)
            numbers.append(invoice.invoice_number)

        self.assertEqual(
            numbers,
            [
                f"INV/{fy}/00001",
                f"INV/{fy}/00002",
                f"INV-NGST/{fy}/00001",
                f"INV-NGST/{fy}/00002",
                f"INV/{fy}/00003",
                f"INV-NGST/{fy}/00003",
            ],
        )

    def test_gst_invoice_copies_job_cards_round_off(self):
        job_card = self._make_completed_job_card("gst-roundoff-1")
        job_card.round_off_amount = Decimal("-0.20")
        job_card.save(update_fields=["round_off_amount"])

        invoice = InvoiceService.generate(job_card, issued_by=None, invoice_type=Invoice.INVOICE_TYPE_GST)
        self.assertEqual(invoice.round_off_amount, Decimal("-0.20"))

    def test_non_gst_invoice_rounds_total_and_stores_round_off(self):
        job_card = JobCard.objects.create(
            tenant=self.tenant,
            jobcard_number="JC-TEST-roundoff-1",
            customer=self.customer,
            vehicle=self.vehicle,
            subtotal=Decimal("1000.00"),
            shop_fees=Decimal("111.65"),
            cgst_amount=Decimal("90.00"),
            sgst_amount=Decimal("90.00"),
            total_amount=Decimal("1291.65"),
            status=JobCard.STATUS_COMPLETED,
        )
        JobCardLineItem.objects.create(
            job_card=job_card,
            sort_order=0,
            service_type=JobCardLineItem.SERVICE_TYPE_LABOUR,
            description="Test Labour",
            quantity=Decimal("1"),
            unit_price=Decimal("1000.00"),
            gst_percentage=Decimal("18.00"),
            cgst_amount=Decimal("90.00"),
            sgst_amount=Decimal("90.00"),
            line_total=Decimal("1000.00"),
        )

        invoice = InvoiceService.generate(job_card, issued_by=None, invoice_type=Invoice.INVOICE_TYPE_NON_GST)
        # exact = subtotal - discount + shop_fees = 1000.00 + 111.65 = 1111.65 -> rounds to 1112.
        self.assertEqual(invoice.total_amount, Decimal("1112"))
        self.assertEqual(invoice.round_off_amount, Decimal("0.35"))

    def test_job_card_locks_after_invoicing_regardless_of_type(self):
        """A job card can only be invoiced once (as either type) — re-invoicing
        after the status has advanced to 'invoiced' is rejected by the existing
        status gate, unaffected by which invoice_type was chosen."""
        job_card = self._make_completed_job_card("lock-1")
        InvoiceService.generate(job_card, issued_by=None, invoice_type=Invoice.INVOICE_TYPE_GST)
        job_card.refresh_from_db()
        self.assertEqual(job_card.status, JobCard.STATUS_INVOICED)

        with self.assertRaises(InvalidJobCardStatus):
            InvoiceService.generate(job_card, issued_by=None, invoice_type=Invoice.INVOICE_TYPE_NON_GST)
