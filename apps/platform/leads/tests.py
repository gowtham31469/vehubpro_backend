"""
Tests for the Leads service layer — creation, status transitions, and
conversion into customers.Customer (and that the resulting Customer actually
satisfies dealer_sales.VehicleSaleQuotation.customer's PROTECT FK, proving
the conversion boundary without leads importing any dealer_sales code).
Plain TestCase, no pytest — mirrors apps.platform.invoices.tests's style.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from apps.platform.customers.models import Customer
from apps.platform.dealer_sales.models import VehicleAcquisition, VehicleSaleQuotation
from apps.platform.leads.models import Lead, LeadStatusEvent
from apps.platform.leads.services import (
    LostReasonRequired,
    convert_lead_to_customer,
    convert_lead_to_inventory,
    create_lead,
    transition_lead_status,
)
from apps.platform.modules.models import (
    Module,
    Permission,
    Submodule,
    SubmodulePermission,
    UserSubmodulePermission,
)
from apps.platform.notifications.models import Notification
from apps.platform.portfolio.models import InventoryVehicle
from apps.platform.tenants.models import Tenant
from apps.platform.masters.models import Role
from apps.platform.users.models import User
from apps.platform.vehicles.models import BodyType, FuelType, VehicleBrand, VehicleModel, VehicleType


class LeadsTestBase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Garage", domain="test-leads.vehubpro.com")

        role, _ = Role.objects.get_or_create(code="ADMIN", defaults={"name": "Admin"})
        self.staff_user = User.objects.create(tenant=self.tenant, role=role, is_archived=False)

        vehicle_type, _ = VehicleType.objects.get_or_create(code="leads_test_car", defaults={"name": "Leads Test Car"})
        self.body_type, _ = BodyType.objects.get_or_create(code="leads_test_body", defaults={"name": "Leads Test Body"})
        self.fuel_type, _ = FuelType.objects.get_or_create(code="leads_test_petrol", defaults={"name": "Leads Test Petrol"})
        self.brand = VehicleBrand.objects.create(tenant=self.tenant, name="LeadsTestBrand")
        self.vehicle_model = VehicleModel.objects.create(
            tenant=self.tenant, brand=self.brand, vehicle_type=vehicle_type, name="LeadsTestModel"
        )
        self.vehicle = InventoryVehicle.objects.create(
            tenant=self.tenant, vehicle_type=self.body_type, brand=self.brand, vehicle_model=self.vehicle_model,
            year=2023, fuel_type=self.fuel_type, mileage_km=5000, listing_price=Decimal("600000.00"),
            registration_no="LEADSTST1", status=InventoryVehicle.STATUS_AVAILABLE,
        )

        # Module/Submodule fixture rows (modules.json/submodules.json) are
        # loaded via `loaddata` in dev/prod, never by `migrate` alone — a
        # fresh test DB has none, so the portfolio Module itself needs to
        # exist here too, not just the Submodule.
        portfolio_module, _ = Module.objects.get_or_create(
            id="d0000000-0000-0000-0000-000000000004",
            defaults={"key": "portfolio", "name": "Portfolio", "description": "Portfolio", "is_active": True},
        )
        leads_submodule, _ = Submodule.objects.get_or_create(
            module_id=portfolio_module.id,
            key="leads",
            defaults={"name": "Leads", "description": "Leads", "is_active": True, "display_order": 25},
        )
        view_permission, _ = Permission.objects.get_or_create(key="view", defaults={"name": "View"})
        submodule_permission, _ = SubmodulePermission.objects.get_or_create(
            submodule=leads_submodule, permission=view_permission
        )
        UserSubmodulePermission.objects.create(
            user=self.staff_user, submodule_permission=submodule_permission, tenant=self.tenant, is_active=True
        )


class LeadCreationTests(LeadsTestBase):
    def test_create_lead_snapshots_fields_and_writes_initial_event(self):
        lead = create_lead(
            tenant_id=self.tenant.id,
            created_by=self.staff_user,
            changed_by=self.staff_user,
            is_self_logged=True,
            source=Lead.SOURCE_WALK_IN,
            enquiry_type=Lead.ENQUIRY_SPECIFIC_VEHICLE,
            vehicle=self.vehicle,
            full_name="Jane Buyer",
            phone="+919876543210",
            email="jane@example.com",
        )

        self.assertEqual(lead.status, Lead.STATUS_NEW)
        self.assertEqual(lead.full_name, "Jane Buyer")
        self.assertTrue(lead.is_self_logged)

        events = list(lead.status_events.all())
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0].from_status)
        self.assertEqual(events[0].to_status, Lead.STATUS_NEW)

    def test_create_lead_notifies_only_users_with_view_permission(self):
        other_role, _ = Role.objects.get_or_create(code="STAFF_NO_ACCESS", defaults={"name": "No Access"})
        unrelated_user = User.objects.create(tenant=self.tenant, role=other_role, is_archived=False)

        lead = create_lead(
            tenant_id=self.tenant.id,
            source=Lead.SOURCE_PUBLIC_ENQUIRY,
            enquiry_type=Lead.ENQUIRY_GENERAL_SEARCH,
            full_name="Anon Buyer",
            phone="+919876500000",
        )

        notified_user_ids = set(
            Notification.objects.filter(tenant=self.tenant).values_list("user_id", flat=True)
        )
        self.assertIn(self.staff_user.id, notified_user_ids)
        self.assertNotIn(unrelated_user.id, notified_user_ids)
        self.assertEqual(lead.source, Lead.SOURCE_PUBLIC_ENQUIRY)


class LeadStatusTransitionTests(LeadsTestBase):
    def setUp(self):
        super().setUp()
        self.lead = create_lead(
            tenant_id=self.tenant.id,
            created_by=self.staff_user,
            changed_by=self.staff_user,
            is_self_logged=True,
            source=Lead.SOURCE_PHONE,
            enquiry_type=Lead.ENQUIRY_SPECIFIC_VEHICLE,
            vehicle=self.vehicle,
            full_name="Lead For Status Test",
            phone="+919876543211",
        )

    def test_transition_creates_one_event_and_updates_status(self):
        transition_lead_status(self.lead, Lead.STATUS_CONTACTED, note="Called", changed_by=self.staff_user)
        self.lead.refresh_from_db()

        self.assertEqual(self.lead.status, Lead.STATUS_CONTACTED)
        self.assertEqual(self.lead.status_events.count(), 2)
        latest = self.lead.status_events.order_by("-created_at").first()
        self.assertEqual(latest.from_status, Lead.STATUS_NEW)
        self.assertEqual(latest.to_status, Lead.STATUS_CONTACTED)
        self.assertEqual(latest.changed_by_id, self.staff_user.id)

    def test_lost_without_reason_raises(self):
        with self.assertRaises(LostReasonRequired):
            transition_lead_status(self.lead, Lead.STATUS_LOST, changed_by=self.staff_user)

    def test_lost_with_reason_succeeds_and_stores_it(self):
        transition_lead_status(
            self.lead, Lead.STATUS_LOST, changed_by=self.staff_user,
            lost_reason=Lead.LOST_REASON_PRICE, lost_notes="Too expensive for them",
        )
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, Lead.STATUS_LOST)
        self.assertEqual(self.lead.lost_reason, Lead.LOST_REASON_PRICE)


class LeadConversionTests(LeadsTestBase):
    def setUp(self):
        super().setUp()
        self.lead = create_lead(
            tenant_id=self.tenant.id,
            created_by=self.staff_user,
            changed_by=self.staff_user,
            is_self_logged=True,
            source=Lead.SOURCE_WALK_IN,
            enquiry_type=Lead.ENQUIRY_SPECIFIC_VEHICLE,
            vehicle=self.vehicle,
            full_name="Convertible Lead",
            phone="+919876543212",
            email="convertible@example.com",
        )

    def test_convert_creates_customer_from_snapshotted_contact_info(self):
        customer = convert_lead_to_customer(self.lead, created_by=self.staff_user)
        self.lead.refresh_from_db()

        self.assertEqual(customer.tenant_id, self.tenant.id)
        self.assertEqual(customer.full_name, "Convertible Lead")
        self.assertEqual(customer.phone, "+919876543212")
        self.assertEqual(self.lead.customer_id, customer.id)
        self.assertEqual(self.lead.status, Lead.STATUS_CONVERTED)

    def test_convert_links_existing_customer(self):
        existing = Customer.objects.create(tenant=self.tenant, full_name="Existing Customer", phone="+919000000000")
        customer = convert_lead_to_customer(self.lead, customer=existing, created_by=self.staff_user)

        self.assertEqual(customer.id, existing.id)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.customer_id, existing.id)

    def test_converted_customer_satisfies_dealer_sales_quotation_protect_fk(self):
        """The whole point of this module: proves the Customer this produces
        is good enough to start the (otherwise untouched) dealer_sales
        pipeline, without leads importing anything from dealer_sales."""
        customer = convert_lead_to_customer(self.lead, created_by=self.staff_user)

        quotation = VehicleSaleQuotation.objects.create(
            tenant=self.tenant,
            vehicle=self.vehicle,
            customer=customer,
            quotation_number="Q-TEST-0001",
            quoted_price=Decimal("580000.00"),
            created_by=self.staff_user,
        )
        self.assertEqual(quotation.customer_id, customer.id)


class LeadTradeInConversionTests(LeadsTestBase):
    def setUp(self):
        super().setUp()
        self.lead = create_lead(
            tenant_id=self.tenant.id,
            created_by=self.staff_user,
            changed_by=self.staff_user,
            is_self_logged=True,
            source=Lead.SOURCE_WALK_IN,
            enquiry_type=Lead.ENQUIRY_TRADE_IN,
            full_name="Trade-In Seller",
            phone="+919876543299",
            email="tradein@example.com",
            trade_in_brand="Honda",
            trade_in_model="City",
            trade_in_year=2019,
            trade_in_registration_no="KA01AB1234",
            trade_in_odometer_km=45000,
            trade_in_expected_price=Decimal("550000.00"),
        )

    def test_convert_creates_inventory_vehicle_and_acquisition(self):
        vehicle = convert_lead_to_inventory(
            self.lead,
            vehicle_type=self.body_type,
            brand=self.brand,
            vehicle_model=self.vehicle_model,
            fuel_type=self.fuel_type,
            year=2019,
            mileage_km=45000,
            registration_no="KA01AB1234",
            listing_price=Decimal("600000.00"),
            purchase_price=Decimal("520000.00"),
            created_by=self.staff_user,
        )

        self.assertEqual(vehicle.tenant_id, self.tenant.id)
        self.assertEqual(vehicle.inventory_type, InventoryVehicle.INVENTORY_TYPE_OWNED)
        self.assertEqual(vehicle.status, InventoryVehicle.STATUS_AVAILABLE)

        acquisition = VehicleAcquisition.objects.get(vehicle=vehicle)
        self.assertEqual(acquisition.acquisition_method, VehicleAcquisition.METHOD_TRADE_IN)
        self.assertEqual(acquisition.purchase_price, Decimal("520000.00"))
        self.assertEqual(acquisition.odometer_reading, 45000)
        self.assertIsNotNone(acquisition.seller_customer_id)

        self.lead.refresh_from_db()
        self.assertEqual(self.lead.converted_vehicle_id, vehicle.id)
        self.assertEqual(self.lead.status, Lead.STATUS_CONVERTED)
        # The trade-in seller needed a Customer record too — auto-created
        # since none was linked yet, same as convert_lead_to_customer does.
        self.assertIsNotNone(self.lead.customer_id)
        self.assertEqual(self.lead.customer_id, acquisition.seller_customer_id)

    def test_convert_reuses_already_linked_customer(self):
        existing = Customer.objects.create(tenant=self.tenant, full_name="Trade-In Seller", phone="+919876543299")
        convert_lead_to_customer(self.lead, customer=existing, created_by=self.staff_user)

        vehicle = convert_lead_to_inventory(
            self.lead,
            vehicle_type=self.body_type,
            brand=self.brand,
            vehicle_model=self.vehicle_model,
            fuel_type=self.fuel_type,
            year=2019,
            created_by=self.staff_user,
        )
        acquisition = VehicleAcquisition.objects.get(vehicle=vehicle)
        self.assertEqual(acquisition.seller_customer_id, existing.id)


class LeadDueFilterTests(LeadsTestBase):
    def test_due_today_and_overdue_are_distinguishable(self):
        today = date.today()
        overdue_lead = Lead.objects.create(
            tenant=self.tenant, full_name="Overdue", phone="+919000000001",
            source=Lead.SOURCE_WALK_IN, next_follow_up_at=today - timedelta(days=2),
        )
        today_lead = Lead.objects.create(
            tenant=self.tenant, full_name="Today", phone="+919000000002",
            source=Lead.SOURCE_WALK_IN, next_follow_up_at=today,
        )
        future_lead = Lead.objects.create(
            tenant=self.tenant, full_name="Future", phone="+919000000003",
            source=Lead.SOURCE_WALK_IN, next_follow_up_at=today + timedelta(days=2),
        )

        overdue_ids = set(Lead.objects.filter(tenant=self.tenant, next_follow_up_at__lt=today).values_list("id", flat=True))
        today_ids = set(Lead.objects.filter(tenant=self.tenant, next_follow_up_at=today).values_list("id", flat=True))

        self.assertEqual(overdue_ids, {overdue_lead.id})
        self.assertEqual(today_ids, {today_lead.id})
        self.assertNotIn(future_lead.id, overdue_ids | today_ids)
