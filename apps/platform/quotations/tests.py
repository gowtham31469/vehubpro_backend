"""
Tests for the Quotation module: creation validation, status transitions,
revisions, tenant isolation, job card conversion, and pricing snapshots.

Mirrors apps.platform.invoices.tests's style — exercises the service layer
directly (QuotationService), since the lifecycle/revision/conversion rules
live there.
"""
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.platform.customers.models import Customer
from apps.platform.jobcards.models import JobCard
from apps.platform.quotations.models import Quotation, QuotationLineItem
from apps.platform.quotations.serializers import QuotationSerializer
from apps.platform.quotations.service import (
    InvalidQuotationStatus,
    QuotationAlreadyConverted,
    QuotationNotLatestVersion,
    QuotationRevisionNotAllowed,
    QuotationService,
)
from apps.platform.services.models import ServiceCategory, ServiceItem
from apps.platform.tenants.models import Tenant
from apps.platform.vehicles.models import FuelType, ServiceVehicle, VehicleBrand, VehicleModel, VehicleType


class QuotationTestBase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Garage", domain="test-garage-quotations.vehubpro.com")
        self.other_tenant = Tenant.objects.create(name="Other Garage", domain="other-garage-quotations.vehubpro.com")

        self.customer = Customer.objects.create(
            tenant=self.tenant, full_name="Ravi Kumar", phone="+919999999999"
        )
        self.other_customer = Customer.objects.create(
            tenant=self.other_tenant, full_name="Other Customer", phone="+918888888888"
        )

        vehicle_type, _ = VehicleType.objects.get_or_create(code="test_car_qt", defaults={"name": "Test Car"})
        fuel_type, _ = FuelType.objects.get_or_create(code="test_petrol_qt", defaults={"name": "Test Petrol"})
        brand = VehicleBrand.objects.create(tenant=self.tenant, name="TestBrandQT")
        vehicle_model = VehicleModel.objects.create(
            tenant=self.tenant, brand=brand, vehicle_type=vehicle_type, name="TestModelQT"
        )
        self.vehicle = ServiceVehicle.objects.create(
            tenant=self.tenant,
            customer=self.customer,
            registration_no="QTTEST0001",
            vehicle_type=vehicle_type,
            brand=brand,
            vehicle_model=vehicle_model,
            year=2024,
            fuel_type=fuel_type,
        )
        other_brand = VehicleBrand.objects.create(tenant=self.other_tenant, name="OtherBrandQT")
        other_model = VehicleModel.objects.create(
            tenant=self.other_tenant, brand=other_brand, vehicle_type=vehicle_type, name="OtherModelQT"
        )
        self.other_vehicle = ServiceVehicle.objects.create(
            tenant=self.other_tenant,
            customer=self.other_customer,
            registration_no="QTTEST0002",
            vehicle_type=vehicle_type,
            brand=other_brand,
            vehicle_model=other_model,
            year=2024,
            fuel_type=fuel_type,
        )

        category = ServiceCategory.objects.create(tenant=self.tenant, name="Engine")
        self.oil_change = ServiceItem.objects.create(
            tenant=self.tenant,
            category=category,
            name="Oil Change",
            service_type="labour",
            base_price=Decimal("500.00"),
            gst_percentage=Decimal("18.00"),
        )

    def _make_draft_quotation(self, *, tenant=None, customer=None, vehicle=None, use_catalog_item=True) -> Quotation:
        tenant = tenant or self.tenant
        line_item = {
            "description": "Oil Change",
            "quantity": "1",
            "unit_price": "500.00",
        }
        if use_catalog_item:
            line_item["service_item"] = str(self.oil_change.id)
        serializer = QuotationSerializer(
            data={
                "customer": str((customer or self.customer).id),
                "vehicle": str((vehicle or self.vehicle).id),
                "quotation_date": str(timezone.now().date()),
                "line_items": [line_item],
            },
            context={"request": _FakeRequest(user=None), "tenant_id": tenant.id, "compact": False},
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()


class _FakeRequest:
    """Minimal stand-in for DRF's request — these tests exercise serializers/
    service methods directly, not the view layer, so `user=None` is fine
    (Quotation.created_by is nullable)."""

    def __init__(self, user=None):
        self.user = user


class QuotationCreationTests(QuotationTestBase):
    def test_valid_quotation_snapshots_price_and_computes_totals(self):
        quotation = self._make_draft_quotation()
        self.assertEqual(quotation.status, Quotation.STATUS_DRAFT)
        self.assertEqual(quotation.version, 1)
        self.assertTrue(quotation.is_latest)
        self.assertTrue(quotation.quotation_number.startswith("QT/"))

        line = quotation.line_items.get()
        self.assertEqual(line.unit_price, Decimal("500.00"))
        self.assertEqual(line.gst_percentage, Decimal("18.00"))
        # subtotal 500, GST 18% = 90 (45 CGST + 45 SGST), total = 590
        self.assertEqual(quotation.subtotal, Decimal("500.00"))
        self.assertEqual(quotation.total_amount, Decimal("590"))

    def test_customer_vehicle_mismatch_rejected(self):
        other_customer = Customer.objects.create(tenant=self.tenant, full_name="Someone Else", phone="+917777777777")
        serializer = QuotationSerializer(
            data={
                "customer": str(other_customer.id),
                "vehicle": str(self.vehicle.id),  # belongs to self.customer, not other_customer
                "quotation_date": str(timezone.now().date()),
                "line_items": [],
            },
            context={"request": _FakeRequest(), "tenant_id": self.tenant.id},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("vehicle", serializer.errors)

    def test_invalid_customer_wrong_tenant_rejected(self):
        serializer = QuotationSerializer(
            data={
                "customer": str(self.other_customer.id),
                "vehicle": str(self.vehicle.id),
                "quotation_date": str(timezone.now().date()),
                "line_items": [],
            },
            context={"request": _FakeRequest(), "tenant_id": self.tenant.id},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("customer", serializer.errors)

    def test_pricing_snapshot_survives_catalog_price_change(self):
        quotation = self._make_draft_quotation()
        line = quotation.line_items.get()
        self.assertEqual(line.unit_price, Decimal("500.00"))

        self.oil_change.base_price = Decimal("650.00")
        self.oil_change.save(update_fields=["base_price"])

        line.refresh_from_db()
        quotation.refresh_from_db()
        self.assertEqual(line.unit_price, Decimal("500.00"))
        self.assertEqual(quotation.subtotal, Decimal("500.00"))


class QuotationStatusTransitionTests(QuotationTestBase):
    def test_draft_to_sent_to_approved(self):
        quotation = self._make_draft_quotation()
        quotation = QuotationService.send(quotation)
        self.assertEqual(quotation.status, Quotation.STATUS_SENT)
        self.assertIsNotNone(quotation.sent_at)

        quotation = QuotationService.approve(quotation)
        self.assertEqual(quotation.status, Quotation.STATUS_APPROVED)
        self.assertIsNotNone(quotation.approved_at)

    def test_sent_to_rejected(self):
        quotation = self._make_draft_quotation()
        quotation = QuotationService.send(quotation)
        quotation = QuotationService.reject(quotation, reason="Customer declined")
        self.assertEqual(quotation.status, Quotation.STATUS_REJECTED)
        self.assertEqual(quotation.rejection_reason, "Customer declined")

    def test_sent_to_expired_lazily_via_apply_expiry(self):
        quotation = self._make_draft_quotation()
        quotation = QuotationService.send(quotation)
        # quotation_date must move back too, or valid_until < quotation_date
        # would violate the quotation_valid_until_after_date CHECK constraint.
        Quotation.objects.filter(pk=quotation.pk).update(
            quotation_date=timezone.now().date() - timezone.timedelta(days=5),
            valid_until=timezone.now().date() - timezone.timedelta(days=1),
        )
        quotation.refresh_from_db()
        quotation = QuotationService.apply_expiry_if_due(quotation)
        self.assertEqual(quotation.status, Quotation.STATUS_EXPIRED)

    def test_cannot_send_empty_quotation(self):
        serializer = QuotationSerializer(
            data={
                "customer": str(self.customer.id),
                "vehicle": str(self.vehicle.id),
                "quotation_date": str(timezone.now().date()),
                "line_items": [],
            },
            context={"request": _FakeRequest(), "tenant_id": self.tenant.id, "compact": False},
        )
        serializer.is_valid(raise_exception=True)
        quotation = serializer.save()
        with self.assertRaises(InvalidQuotationStatus):
            QuotationService.send(quotation)

    def test_cannot_approve_a_draft(self):
        quotation = self._make_draft_quotation()
        with self.assertRaises(InvalidQuotationStatus):
            QuotationService.approve(quotation)

    def test_cannot_reject_a_draft(self):
        quotation = self._make_draft_quotation()
        with self.assertRaises(InvalidQuotationStatus):
            QuotationService.reject(quotation)

    def test_cancel_from_draft(self):
        quotation = self._make_draft_quotation()
        quotation = QuotationService.cancel(quotation, reason="No longer needed")
        self.assertEqual(quotation.status, Quotation.STATUS_CANCELLED)

    def test_cannot_cancel_already_cancelled(self):
        quotation = self._make_draft_quotation()
        quotation = QuotationService.cancel(quotation)
        with self.assertRaises(InvalidQuotationStatus):
            QuotationService.cancel(quotation)


class QuotationRevisionTests(QuotationTestBase):
    def _approved_v1(self) -> Quotation:
        quotation = self._make_draft_quotation()
        quotation = QuotationService.send(quotation)
        quotation = QuotationService.approve(quotation)
        return quotation

    def test_revision_preserves_v1_and_copies_items(self):
        v1 = self._approved_v1()
        v1_total = v1.total_amount

        v2 = QuotationService.create_revision(v1, revision_reason="Clutch also needs replacement", created_by=None)

        v1.refresh_from_db()
        self.assertFalse(v1.is_latest)
        self.assertEqual(v1.status, Quotation.STATUS_APPROVED)
        self.assertEqual(v1.total_amount, v1_total)
        self.assertEqual(v1.line_items.count(), 1)

        self.assertTrue(v2.is_latest)
        self.assertEqual(v2.status, Quotation.STATUS_DRAFT)
        self.assertEqual(v2.version, 2)
        self.assertEqual(v2.quotation_number, v1.quotation_number)
        self.assertEqual(v2.parent_quotation_id, v1.id)
        self.assertEqual(v2.line_items.count(), 1)
        self.assertEqual(v2.total_amount, v1_total)

    def test_revision_of_expired_quotation_drops_stale_valid_until(self):
        """
        Regression test: reviving an EXPIRED quotation (whose valid_until is
        necessarily in the past) used to crash with an IntegrityError, because
        the new version is dated today while valid_until was copied verbatim
        from the parent — violating quotation_valid_until_after_date.
        """
        v1 = self._approved_v1()
        past = timezone.now().date() - timezone.timedelta(days=2)
        Quotation.objects.filter(pk=v1.pk).update(quotation_date=past, valid_until=past, status=Quotation.STATUS_EXPIRED)
        v1.refresh_from_db()

        v2 = QuotationService.create_revision(v1, revision_reason="Reviving an expired quote", created_by=None)

        self.assertEqual(v2.quotation_date, timezone.now().date())
        self.assertIsNone(v2.valid_until)

    def test_revision_can_add_items_and_be_approved(self):
        v1 = self._approved_v1()
        v2 = QuotationService.create_revision(v1, revision_reason="Additional work discovered", created_by=None)

        QuotationLineItem.objects.create(
            quotation=v2,
            sort_order=1,
            description="Clutch Replacement",
            quantity=Decimal("1"),
            unit_price=Decimal("5000.00"),
            line_total=Decimal("5000.00"),
        )
        from apps.platform.quotations.utils import refresh_quotation_totals
        refresh_quotation_totals(v2)
        v2.refresh_from_db()

        self.assertGreater(v2.total_amount, v1.total_amount)

        v2 = QuotationService.send(v2)
        v2 = QuotationService.approve(v2)
        self.assertEqual(v2.status, Quotation.STATUS_APPROVED)

    def test_cannot_revise_a_draft(self):
        quotation = self._make_draft_quotation()
        with self.assertRaises(QuotationRevisionNotAllowed):
            QuotationService.create_revision(quotation, revision_reason="x", created_by=None)

    def test_cannot_revise_a_non_latest_version(self):
        v1 = self._approved_v1()
        QuotationService.create_revision(v1, revision_reason="first revision", created_by=None)
        v1.refresh_from_db()
        with self.assertRaises(QuotationNotLatestVersion):
            QuotationService.create_revision(v1, revision_reason="second revision", created_by=None)


class QuotationTenantIsolationTests(QuotationTestBase):
    def test_tenant_a_cannot_access_tenant_b_quotation_via_serializer_validation(self):
        serializer = QuotationSerializer(
            data={
                "customer": str(self.other_customer.id),
                "vehicle": str(self.other_vehicle.id),
                "quotation_date": str(timezone.now().date()),
                "line_items": [],
            },
            context={"request": _FakeRequest(), "tenant_id": self.tenant.id},
        )
        self.assertFalse(serializer.is_valid())

    def test_quotation_number_sequences_are_tenant_scoped(self):
        q1 = self._make_draft_quotation(tenant=self.tenant)
        q2 = self._make_draft_quotation(
            tenant=self.other_tenant,
            customer=self.other_customer,
            vehicle=self.other_vehicle,
            use_catalog_item=False,
        )
        # Independent per-tenant FY sequences both start at 00001.
        self.assertTrue(q1.quotation_number.endswith("/00001"))
        self.assertTrue(q2.quotation_number.endswith("/00001"))
        self.assertNotEqual(q1.tenant_id, q2.tenant_id)


class QuotationJobCardConversionTests(QuotationTestBase):
    def _approved_quotation(self) -> Quotation:
        quotation = self._make_draft_quotation()
        quotation = QuotationService.send(quotation)
        return QuotationService.approve(quotation)

    def test_approved_quotation_converts_to_job_card(self):
        quotation = self._approved_quotation()
        job_card = QuotationService.convert_to_job_card(quotation)

        quotation.refresh_from_db()
        self.assertEqual(quotation.status, Quotation.STATUS_CONVERTED)
        self.assertIsNotNone(quotation.converted_at)

        self.assertEqual(job_card.customer_id, quotation.customer_id)
        self.assertEqual(job_card.vehicle_id, quotation.vehicle_id)
        self.assertEqual(job_card.quotation_id, quotation.id)
        self.assertEqual(job_card.line_items.count(), quotation.line_items.count())
        self.assertEqual(job_card.total_amount, quotation.total_amount)
        self.assertEqual(job_card.status, JobCard.STATUS_JOB_CONTROL)

    def test_draft_quotation_cannot_convert(self):
        quotation = self._make_draft_quotation()
        with self.assertRaises(InvalidQuotationStatus):
            QuotationService.convert_to_job_card(quotation)

    def test_rejected_quotation_cannot_convert(self):
        quotation = self._make_draft_quotation()
        quotation = QuotationService.send(quotation)
        quotation = QuotationService.reject(quotation)
        with self.assertRaises(InvalidQuotationStatus):
            QuotationService.convert_to_job_card(quotation)

    def test_cancelled_quotation_cannot_convert(self):
        quotation = self._make_draft_quotation()
        quotation = QuotationService.cancel(quotation)
        with self.assertRaises(InvalidQuotationStatus):
            QuotationService.convert_to_job_card(quotation)

    def test_expired_quotation_cannot_convert(self):
        quotation = self._make_draft_quotation()
        quotation = QuotationService.send(quotation)
        quotation = QuotationService.approve(quotation)
        Quotation.objects.filter(pk=quotation.pk).update(
            quotation_date=timezone.now().date() - timezone.timedelta(days=5),
            valid_until=timezone.now().date() - timezone.timedelta(days=1),
        )
        quotation.refresh_from_db()
        with self.assertRaises(InvalidQuotationStatus):
            QuotationService.convert_to_job_card(quotation)

    def test_already_converted_quotation_cannot_convert_again(self):
        quotation = self._approved_quotation()
        QuotationService.convert_to_job_card(quotation)
        quotation.refresh_from_db()
        with self.assertRaises(QuotationAlreadyConverted):
            QuotationService.convert_to_job_card(quotation)

    def test_only_latest_revision_can_convert(self):
        v1 = self._approved_quotation()
        v2 = QuotationService.create_revision(v1, revision_reason="more work", created_by=None)
        v2 = QuotationService.send(v2)
        v2 = QuotationService.approve(v2)
        v1.refresh_from_db()

        with self.assertRaises(QuotationNotLatestVersion):
            QuotationService.convert_to_job_card(v1)

        job_card = QuotationService.convert_to_job_card(v2)
        self.assertEqual(job_card.quotation_id, v2.id)
