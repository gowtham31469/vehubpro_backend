"""
Tests for the dealer vehicle-inventory workflow (Phase 1): acquisition,
ownership history, vehicle work/expenses, pricing history, timeline, and
profitability. Exercises the service layer and models directly, mirroring
apps.platform.invoices.tests's style.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.platform.customers.models import Customer
from apps.platform.dealer_sales.models import (
    VehicleAcquisition,
    VehicleBooking,
    VehicleOwnershipRecord,
    VehiclePriceHistory,
    VehicleReservation,
    VehicleSale,
    VehicleSaleInvoice,
    VehicleSaleQuotation,
    VehicleTimelineEvent,
    VehicleWorkExpense,
)
from apps.platform.dealer_sales.services import (
    DealerSalesError,
    accept_quotation,
    add_negotiation_round,
    cancel_booking,
    cancel_quotation,
    cancel_sale,
    compute_commission,
    compute_profitability,
    confirm_sale,
    create_booking,
    create_delivery,
    create_quotation,
    create_reservation,
    create_settlement,
    generate_sale_invoice,
    get_total_work_expenses,
    mark_settlement_paid,
    record_price_change,
    record_sale_invoice_payment,
    record_vehicle_timeline_event,
    reject_quotation,
    send_quotation,
)
from apps.platform.portfolio.models import InventoryVehicle
from apps.platform.tenants.models import Tenant
from apps.platform.vehicles.models import BodyType, FuelType, VehicleBrand, VehicleModel


class DealerSalesTestCase(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Test Dealer", domain="test-dealer.vehubpro.com")
        self.other_tenant = Tenant.objects.create(name="Other Dealer", domain="other-dealer.vehubpro.com")

        body_type, _ = BodyType.objects.get_or_create(code="test_suv", defaults={"name": "Test SUV"})
        fuel_type, _ = FuelType.objects.get_or_create(code="test_diesel", defaults={"name": "Test Diesel"})
        brand = VehicleBrand.objects.create(tenant=self.tenant, name="TestToyota")
        vehicle_model = VehicleModel.objects.create(tenant=self.tenant, brand=brand, name="TestInnova")

        self.owned_vehicle = InventoryVehicle.objects.create(
            tenant=self.tenant,
            vehicle_type=body_type,
            brand=brand,
            vehicle_model=vehicle_model,
            year=2022,
            fuel_type=fuel_type,
            transmission=InventoryVehicle.TRANSMISSION_MANUAL,
            color="white",
            mileage_km=40000,
            listing_price=Decimal("580000.00"),
            inventory_type=InventoryVehicle.INVENTORY_TYPE_OWNED,
        )

        self.consignment_vehicle = InventoryVehicle.objects.create(
            tenant=self.tenant,
            vehicle_type=body_type,
            brand=brand,
            vehicle_model=vehicle_model,
            year=2021,
            fuel_type=fuel_type,
            transmission=InventoryVehicle.TRANSMISSION_AUTOMATIC,
            color="black",
            mileage_km=25000,
            listing_price=Decimal("550000.00"),
            inventory_type=InventoryVehicle.INVENTORY_TYPE_CUSTOMER_CONSIGNMENT,
        )


class VehicleWorkExpenseTests(DealerSalesTestCase):
    """Covers the mandatory requirement: work/expense tracking has no Garage dependency."""

    def test_create_multiple_work_expenses(self):
        VehicleWorkExpense.objects.create(
            tenant=self.tenant, vehicle=self.owned_vehicle, category="brake",
            amount=Decimal("8500.00"), expense_date=date(2026, 1, 3), provider_name="ABC Auto Works",
            provider_type="external_garage",
        )
        VehicleWorkExpense.objects.create(
            tenant=self.tenant, vehicle=self.owned_vehicle, category="painting",
            amount=Decimal("25000.00"), expense_date=date(2026, 1, 4), provider_name="Kumar Paint Works",
            provider_type="paint_shop",
        )
        self.assertEqual(VehicleWorkExpense.objects.filter(vehicle=self.owned_vehicle).count(), 2)

    def test_work_expense_has_no_garage_fk(self):
        """Structural proof: the model has no field referencing services/jobcards."""
        field_names = {f.name for f in VehicleWorkExpense._meta.get_fields()}
        self.assertNotIn("job_card", field_names)
        self.assertNotIn("service_item", field_names)
        self.assertNotIn("technician", field_names)

    def test_decimal_precision_preserved(self):
        expense = VehicleWorkExpense.objects.create(
            tenant=self.tenant, vehicle=self.owned_vehicle, category="tyre",
            amount=Decimal("32000.00"), expense_date=date(2026, 1, 5),
        )
        expense.refresh_from_db()
        self.assertEqual(expense.amount, Decimal("32000.00"))
        self.assertIsInstance(expense.amount, Decimal)

    def test_archive_instead_of_delete(self):
        expense = VehicleWorkExpense.objects.create(
            tenant=self.tenant, vehicle=self.owned_vehicle, category="other",
            amount=Decimal("1000.00"), expense_date=date(2026, 1, 1),
        )
        expense.archive()
        self.assertTrue(VehicleWorkExpense.objects.filter(pk=expense.pk).exists())
        self.assertTrue(VehicleWorkExpense.objects.get(pk=expense.pk).is_archived)

    def test_cancelled_expenses_excluded_from_total(self):
        VehicleWorkExpense.objects.create(
            tenant=self.tenant, vehicle=self.owned_vehicle, category="other",
            amount=Decimal("5000.00"), expense_date=date(2026, 1, 1), status="completed",
        )
        VehicleWorkExpense.objects.create(
            tenant=self.tenant, vehicle=self.owned_vehicle, category="other",
            amount=Decimal("9999.00"), expense_date=date(2026, 1, 1), status="cancelled",
        )
        self.assertEqual(get_total_work_expenses(self.owned_vehicle), Decimal("5000.00"))


class AcquisitionTests(DealerSalesTestCase):
    def test_owned_acquisition(self):
        acquisition = VehicleAcquisition.objects.create(
            tenant=self.tenant, vehicle=self.owned_vehicle, acquisition_date=date(2025, 12, 1),
            purchase_price=Decimal("450000.00"), acquisition_method="direct_purchase",
        )
        self.assertEqual(self.owned_vehicle.acquisition, acquisition)

    def test_consignment_acquisition(self):
        from apps.platform.customers.models import Customer

        owner = Customer.objects.create(tenant=self.tenant, full_name="Owner Customer", phone="+919000000001")
        acquisition = VehicleAcquisition.objects.create(
            tenant=self.tenant, vehicle=self.consignment_vehicle, acquisition_date=date(2025, 12, 1),
            owner_customer=owner, owner_expected_price=Decimal("500000.00"),
            commission_type="percentage", commission_value=Decimal("5.00"),
        )
        self.assertEqual(acquisition.owner_customer, owner)


class OwnershipHistoryTests(DealerSalesTestCase):
    def test_ownership_chain(self):
        VehicleOwnershipRecord.objects.create(
            tenant=self.tenant, vehicle=self.owned_vehicle, owner_type="previous_owner",
            owner_name="Previous Owner per RC", start_date=date(2020, 1, 1), end_date=date(2025, 12, 1),
        )
        VehicleOwnershipRecord.objects.create(
            tenant=self.tenant, vehicle=self.owned_vehicle, owner_type="dealer",
            start_date=date(2025, 12, 1),
        )
        self.assertEqual(self.owned_vehicle.ownership_history.count(), 2)


class PriceHistoryAndTimelineTests(DealerSalesTestCase):
    def test_record_price_change_creates_history_and_timeline(self):
        record_price_change(
            vehicle=self.owned_vehicle, price_type="listing_price",
            old_value=Decimal("580000.00"), new_value=Decimal("590000.00"),
        )
        self.assertEqual(VehiclePriceHistory.objects.filter(vehicle=self.owned_vehicle).count(), 1)
        history = VehiclePriceHistory.objects.get(vehicle=self.owned_vehicle)
        self.assertEqual(history.old_value, Decimal("580000.00"))
        self.assertEqual(history.new_value, Decimal("590000.00"))

        self.assertEqual(
            VehicleTimelineEvent.objects.filter(vehicle=self.owned_vehicle, category="pricing").count(), 1
        )

    def test_timeline_chronological_order(self):
        record_vehicle_timeline_event(vehicle=self.owned_vehicle, category="acquisition", title="First")
        record_vehicle_timeline_event(vehicle=self.owned_vehicle, category="work_expense", title="Second")
        events = list(self.owned_vehicle.timeline_events.all())
        self.assertEqual([e.title for e in events], ["First", "Second"])


class ProfitabilityTests(DealerSalesTestCase):
    def test_owned_profitability_matches_spec_example(self):
        """Toyota Innova example from the spec: purchase 4,50,000 + brake 8,500
        + painting 25,000 + tyres 32,000 + service 6,500 + transport 2,500
        = 5,24,500 landed cost."""
        VehicleAcquisition.objects.create(
            tenant=self.tenant, vehicle=self.owned_vehicle, acquisition_date=date(2025, 12, 1),
            purchase_price=Decimal("450000.00"),
        )
        for category, amount in [
            ("brake", "8500.00"), ("painting", "25000.00"), ("tyre", "32000.00"),
            ("general_service", "6500.00"), ("transport", "2500.00"),
        ]:
            VehicleWorkExpense.objects.create(
                tenant=self.tenant, vehicle=self.owned_vehicle, category=category,
                amount=Decimal(amount), expense_date=date(2026, 1, 1),
            )

        self.owned_vehicle.listing_price = Decimal("580000.00")
        self.owned_vehicle.save(update_fields=["listing_price"])

        result = compute_profitability(self.owned_vehicle)
        self.assertEqual(result["total_landed_cost"], Decimal("524500.00"))
        self.assertEqual(result["estimated_profit_at_listing"], Decimal("55500.00"))

    def test_consignment_profitability(self):
        from apps.platform.customers.models import Customer

        owner = Customer.objects.create(tenant=self.tenant, full_name="Consignor", phone="+919000000002")
        VehicleAcquisition.objects.create(
            tenant=self.tenant, vehicle=self.consignment_vehicle, acquisition_date=date(2025, 12, 1),
            owner_customer=owner, owner_expected_price=Decimal("500000.00"),
            commission_type="percentage", commission_value=Decimal("5.00"),
        )
        result = compute_profitability(self.consignment_vehicle)
        self.assertEqual(result["owner_expected_price"], Decimal("500000.00"))
        self.assertEqual(result["inventory_type"], InventoryVehicle.INVENTORY_TYPE_CUSTOMER_CONSIGNMENT)


class TenantIsolationTests(DealerSalesTestCase):
    def test_work_expense_queryset_respects_tenant(self):
        VehicleWorkExpense.objects.create(
            tenant=self.tenant, vehicle=self.owned_vehicle, category="other",
            amount=Decimal("1000.00"), expense_date=date(2026, 1, 1),
        )
        other_tenant_expenses = VehicleWorkExpense.objects.filter(tenant=self.other_tenant)
        self.assertEqual(other_tenant_expenses.count(), 0)

    def test_vehicle_from_other_tenant_not_resolvable(self):
        # Mirrors the _resolve_vehicle() check used in views.py.
        resolved = InventoryVehicle.objects.filter(
            id=self.owned_vehicle.id, tenant_id=self.other_tenant.id, is_archived=False
        ).first()
        self.assertIsNone(resolved)


# ─────────────────────────────────────────────────────────────────────────
# Phase 2 — Quotation → Negotiation → Reservation → Booking → Sale →
# Delivery → Settlement
# ─────────────────────────────────────────────────────────────────────────


class DealerSalesPhase2TestCase(DealerSalesTestCase):
    def setUp(self):
        super().setUp()
        self.buyer = Customer.objects.create(tenant=self.tenant, full_name="Buyer Customer", phone="+919000000010")


class QuotationNumberingTests(DealerSalesPhase2TestCase):
    def test_sequential_numbering_format_and_tenant_scope(self):
        q1 = create_quotation(vehicle=self.owned_vehicle, customer=self.buyer, quoted_price=Decimal("580000.00"))
        q2 = create_quotation(vehicle=self.owned_vehicle, customer=self.buyer, quoted_price=Decimal("575000.00"))
        self.assertTrue(q1.quotation_number.startswith("DQ/"))
        seq1 = int(q1.quotation_number.split("/")[-1])
        seq2 = int(q2.quotation_number.split("/")[-1])
        self.assertEqual(seq2, seq1 + 1)

        other_buyer = Customer.objects.create(tenant=self.other_tenant, full_name="Other Buyer", phone="+919000000099")
        other_vehicle = InventoryVehicle.objects.create(
            tenant=self.other_tenant, vehicle_type=self.owned_vehicle.vehicle_type,
            brand=self.owned_vehicle.brand, vehicle_model=self.owned_vehicle.vehicle_model,
            year=2020, fuel_type=self.owned_vehicle.fuel_type, listing_price=Decimal("400000.00"),
        )
        q3 = create_quotation(vehicle=other_vehicle, customer=other_buyer, quoted_price=Decimal("400000.00"))
        # Independent tenant sequence — restarts, doesn't continue q1/q2's counter.
        self.assertEqual(int(q3.quotation_number.split("/")[-1]), 1)


class NegotiationTests(DealerSalesPhase2TestCase):
    def test_negotiation_rounds_increment_and_appear_on_timeline(self):
        quotation = create_quotation(vehicle=self.owned_vehicle, customer=self.buyer, quoted_price=Decimal("580000.00"))
        send_quotation(quotation)
        r1 = add_negotiation_round(quotation, offered_by="customer", amount=Decimal("550000.00"))
        r2 = add_negotiation_round(quotation, offered_by="dealer", amount=Decimal("565000.00"))
        self.assertEqual(r1.round_number, 1)
        self.assertEqual(r2.round_number, 2)
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, VehicleSaleQuotation.STATUS_NEGOTIATING)
        self.assertTrue(
            VehicleTimelineEvent.objects.filter(vehicle=self.owned_vehicle, category="negotiation").count() >= 2
        )

    def test_negotiation_rejected_on_draft_quotation(self):
        quotation = create_quotation(vehicle=self.owned_vehicle, customer=self.buyer, quoted_price=Decimal("580000.00"))
        with self.assertRaises(DealerSalesError):
            add_negotiation_round(quotation, offered_by="customer", amount=Decimal("550000.00"))


class HappyPathStatusTransitionTests(DealerSalesPhase2TestCase):
    def test_available_to_booked_to_sold_to_delivered(self):
        vehicle = self.owned_vehicle
        self.assertEqual(vehicle.status, InventoryVehicle.STATUS_AVAILABLE)

        quotation = create_quotation(vehicle=vehicle, customer=self.buyer, quoted_price=Decimal("580000.00"))
        send_quotation(quotation)
        accept_quotation(quotation)

        reservation = create_reservation(
            vehicle=vehicle, customer=self.buyer, reservation_date=date(2026, 1, 1), quotation=quotation,
        )
        booking = create_booking(
            vehicle=vehicle, customer=self.buyer, booking_date=date(2026, 1, 2),
            reservation=reservation, quotation=quotation,
        )
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, InventoryVehicle.STATUS_BOOKED)
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, VehicleReservation.STATUS_CONVERTED_TO_BOOKING)

        sale = confirm_sale(
            vehicle=vehicle, buyer=self.buyer, sale_date=date(2026, 1, 5),
            final_sale_price=Decimal("575000.00"), quotation=quotation, booking=booking,
        )
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, InventoryVehicle.STATUS_SOLD)
        booking.refresh_from_db()
        self.assertEqual(booking.status, VehicleBooking.STATUS_CONVERTED_TO_SALE)
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, VehicleSaleQuotation.STATUS_CONVERTED)

        create_delivery(sale=sale, delivery_date=date(2026, 1, 10))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, InventoryVehicle.STATUS_DELIVERED)

        timeline_categories = list(
            vehicle.timeline_events.order_by("created_at").values_list("category", flat=True)
        )
        for expected in ["quotation", "reservation", "booking", "sale"]:
            self.assertIn(expected, timeline_categories)


class OneActiveSalePerVehicleTests(DealerSalesPhase2TestCase):
    def test_second_confirmed_sale_rejected(self):
        vehicle = self.owned_vehicle
        confirm_sale(vehicle=vehicle, buyer=self.buyer, sale_date=date(2026, 1, 1), final_sale_price=Decimal("500000.00"))
        with self.assertRaises(DealerSalesError):
            confirm_sale(vehicle=vehicle, buyer=self.buyer, sale_date=date(2026, 1, 2), final_sale_price=Decimal("510000.00"))

    def test_cancelled_sale_does_not_block_new_sale(self):
        vehicle = self.owned_vehicle
        sale = confirm_sale(vehicle=vehicle, buyer=self.buyer, sale_date=date(2026, 1, 1), final_sale_price=Decimal("500000.00"))
        cancel_sale(sale, reason="Buyer backed out")
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, InventoryVehicle.STATUS_AVAILABLE)

        new_sale = confirm_sale(vehicle=vehicle, buyer=self.buyer, sale_date=date(2026, 1, 5), final_sale_price=Decimal("495000.00"))
        self.assertEqual(new_sale.status, VehicleSale.STATUS_CONFIRMED)

    def test_cancel_booking_reverts_vehicle_to_available(self):
        vehicle = self.owned_vehicle
        booking = create_booking(vehicle=vehicle, customer=self.buyer, booking_date=date(2026, 1, 1))
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, InventoryVehicle.STATUS_BOOKED)
        cancel_booking(booking, reason="Customer cancelled")
        vehicle.refresh_from_db()
        self.assertEqual(vehicle.status, InventoryVehicle.STATUS_AVAILABLE)


class SettlementTests(DealerSalesPhase2TestCase):
    """Reproduces the spec's exact Hyundai Creta consignment example for all
    three commission types: owner expected ₹5,00,000, final sale ₹5,40,000."""

    def _make_consignment_sale(self, *, commission_type, commission_value):
        owner = Customer.objects.create(tenant=self.tenant, full_name="Creta Owner", phone="+919000000020")
        VehicleAcquisition.objects.create(
            tenant=self.tenant, vehicle=self.consignment_vehicle, acquisition_date=date(2025, 12, 1),
            owner_customer=owner, owner_expected_price=Decimal("500000.00"),
            commission_type=commission_type, commission_value=commission_value,
        )
        sale = confirm_sale(
            vehicle=self.consignment_vehicle, buyer=self.buyer, sale_date=date(2026, 1, 1),
            final_sale_price=Decimal("540000.00"),
        )
        return sale

    def test_percentage_commission(self):
        sale = self._make_consignment_sale(commission_type="percentage", commission_value=Decimal("5.00"))
        settlement = create_settlement(sale)
        self.assertEqual(settlement.commission_amount, Decimal("27000.00"))
        self.assertEqual(settlement.owner_payable, Decimal("513000.00"))

    def test_fixed_commission(self):
        sale = self._make_consignment_sale(commission_type="fixed", commission_value=Decimal("27000.00"))
        settlement = create_settlement(sale)
        self.assertEqual(settlement.commission_amount, Decimal("27000.00"))
        self.assertEqual(settlement.owner_payable, Decimal("513000.00"))

    def test_price_difference_commission(self):
        sale = self._make_consignment_sale(commission_type="price_difference", commission_value=None)
        settlement = create_settlement(sale)
        # commission = final_sale_price - owner_expected_price = 540000 - 500000
        self.assertEqual(settlement.commission_amount, Decimal("40000.00"))
        self.assertEqual(settlement.owner_payable, Decimal("500000.00"))

    def test_net_dealer_profit_subtracts_dealer_expenses(self):
        sale = self._make_consignment_sale(commission_type="percentage", commission_value=Decimal("5.00"))
        VehicleWorkExpense.objects.create(
            tenant=self.tenant, vehicle=self.consignment_vehicle, category="detailing",
            amount=Decimal("5000.00"), expense_date=date(2026, 1, 1),
        )
        settlement = create_settlement(sale)
        self.assertEqual(settlement.dealer_expenses_total, Decimal("5000.00"))
        self.assertEqual(settlement.net_dealer_profit, Decimal("22000.00"))

    def test_mark_settlement_paid(self):
        sale = self._make_consignment_sale(commission_type="percentage", commission_value=Decimal("5.00"))
        settlement = create_settlement(sale)
        self.assertEqual(settlement.settlement_status, "pending")
        mark_settlement_paid(settlement)
        settlement.refresh_from_db()
        self.assertEqual(settlement.settlement_status, "paid")

    def test_settlement_requires_acquisition(self):
        sale = confirm_sale(vehicle=self.owned_vehicle, buyer=self.buyer, sale_date=date(2026, 1, 1), final_sale_price=Decimal("500000.00"))
        with self.assertRaises(DealerSalesError):
            create_settlement(sale)

    def test_compute_commission_helper_matches_settlement(self):
        acquisition = VehicleAcquisition.objects.create(
            tenant=self.tenant, vehicle=self.consignment_vehicle, acquisition_date=date(2025, 12, 1),
            owner_expected_price=Decimal("500000.00"), commission_type="percentage", commission_value=Decimal("5.00"),
        )
        self.assertEqual(compute_commission(acquisition, Decimal("540000.00")), Decimal("27000.00"))


class SaleInvoiceTests(DealerSalesPhase2TestCase):
    def test_invoice_numbering_and_snapshot_fields(self):
        sale = confirm_sale(vehicle=self.owned_vehicle, buyer=self.buyer, sale_date=date(2026, 1, 1), final_sale_price=Decimal("500000.00"))
        invoice = generate_sale_invoice(sale)
        self.assertTrue(invoice.invoice_number.startswith("DSI/"))
        self.assertEqual(invoice.buyer_name_snapshot, self.buyer.full_name)
        self.assertEqual(invoice.sale_amount, Decimal("500000.00"))
        self.assertEqual(invoice.payment_status, VehicleSaleInvoice.PAYMENT_STATUS_UNPAID)

    def test_payment_status_transitions_unpaid_partial_paid(self):
        sale = confirm_sale(vehicle=self.owned_vehicle, buyer=self.buyer, sale_date=date(2026, 1, 1), final_sale_price=Decimal("500000.00"))
        invoice = generate_sale_invoice(sale)

        record_sale_invoice_payment(invoice, amount=Decimal("200000.00"), payment_mode="upi")
        invoice.refresh_from_db()
        self.assertEqual(invoice.payment_status, VehicleSaleInvoice.PAYMENT_STATUS_PARTIAL)
        self.assertEqual(invoice.amount_paid, Decimal("200000.00"))

        record_sale_invoice_payment(invoice, amount=Decimal("300000.00"), payment_mode="bank_transfer")
        invoice.refresh_from_db()
        self.assertEqual(invoice.payment_status, VehicleSaleInvoice.PAYMENT_STATUS_PAID)


class InvoiceAdvanceCreditTests(DealerSalesPhase2TestCase):
    """Reservation deposits and booking amounts are money already collected
    before the invoice exists — generate_sale_invoice() auto-credits them so
    only the true remaining balance needs collecting."""

    def test_booking_amount_supersedes_reservation_deposit(self):
        reservation = create_reservation(
            vehicle=self.owned_vehicle, customer=self.buyer, reservation_date=date(2026, 1, 1),
            deposit_amount=Decimal("20000.00"),
        )
        booking = create_booking(
            vehicle=self.owned_vehicle, customer=self.buyer, booking_date=date(2026, 1, 2),
            reservation=reservation, booking_amount=Decimal("200000.00"),
        )
        sale = confirm_sale(
            vehicle=self.owned_vehicle, buyer=self.buyer, sale_date=date(2026, 1, 5),
            final_sale_price=Decimal("480000.00"), booking=booking,
        )
        invoice = generate_sale_invoice(sale)

        # Booking amount (which already includes the deposit) is credited
        # once — not booking_amount + deposit_amount double-counted.
        self.assertEqual(invoice.amount_paid, Decimal("200000.00"))
        self.assertEqual(invoice.payment_status, VehicleSaleInvoice.PAYMENT_STATUS_PARTIAL)
        payments = list(invoice.payments.all())
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0].amount, Decimal("200000.00"))
        self.assertEqual(payments[0].payment_mode, "advance")

    def test_reservation_deposit_credited_when_booking_has_no_amount(self):
        reservation = create_reservation(
            vehicle=self.owned_vehicle, customer=self.buyer, reservation_date=date(2026, 1, 1),
            deposit_amount=Decimal("15000.00"),
        )
        booking = create_booking(
            vehicle=self.owned_vehicle, customer=self.buyer, booking_date=date(2026, 1, 2), reservation=reservation,
        )
        sale = confirm_sale(
            vehicle=self.owned_vehicle, buyer=self.buyer, sale_date=date(2026, 1, 5),
            final_sale_price=Decimal("480000.00"), booking=booking,
        )
        invoice = generate_sale_invoice(sale)
        self.assertEqual(invoice.amount_paid, Decimal("15000.00"))
        self.assertEqual(invoice.payments.first().payment_reference, "Reservation deposit")

    def test_no_booking_means_no_advance_credit(self):
        sale = confirm_sale(
            vehicle=self.owned_vehicle, buyer=self.buyer, sale_date=date(2026, 1, 1),
            final_sale_price=Decimal("500000.00"),
        )
        invoice = generate_sale_invoice(sale)
        self.assertEqual(invoice.amount_paid, Decimal("0.00"))
        self.assertEqual(invoice.payment_status, VehicleSaleInvoice.PAYMENT_STATUS_UNPAID)

    def test_record_payment_after_advance_credit_reaches_paid(self):
        booking = create_booking(
            vehicle=self.owned_vehicle, customer=self.buyer, booking_date=date(2026, 1, 2),
            booking_amount=Decimal("200000.00"),
        )
        sale = confirm_sale(
            vehicle=self.owned_vehicle, buyer=self.buyer, sale_date=date(2026, 1, 5),
            final_sale_price=Decimal("480000.00"), booking=booking,
        )
        invoice = generate_sale_invoice(sale)
        record_sale_invoice_payment(invoice, amount=Decimal("280000.00"), payment_mode="bank_transfer")
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal("480000.00"))
        self.assertEqual(invoice.payment_status, VehicleSaleInvoice.PAYMENT_STATUS_PAID)


class CancellationPreservationTests(DealerSalesPhase2TestCase):
    def test_cancelled_quotation_row_preserved_not_deleted(self):
        quotation = create_quotation(vehicle=self.owned_vehicle, customer=self.buyer, quoted_price=Decimal("500000.00"))
        cancel_quotation(quotation, reason="Customer changed mind")
        self.assertTrue(VehicleSaleQuotation.objects.filter(pk=quotation.pk).exists())
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, VehicleSaleQuotation.STATUS_CANCELLED)
        self.assertEqual(quotation.cancellation_reason, "Customer changed mind")

    def test_rejected_quotation_preserved(self):
        quotation = create_quotation(vehicle=self.owned_vehicle, customer=self.buyer, quoted_price=Decimal("500000.00"))
        send_quotation(quotation)
        reject_quotation(quotation, reason="Price too high")
        self.assertTrue(VehicleSaleQuotation.objects.filter(pk=quotation.pk).exists())
        quotation.refresh_from_db()
        self.assertEqual(quotation.status, VehicleSaleQuotation.STATUS_REJECTED)

    def test_cancelled_sale_row_preserved(self):
        sale = confirm_sale(vehicle=self.owned_vehicle, buyer=self.buyer, sale_date=date(2026, 1, 1), final_sale_price=Decimal("500000.00"))
        cancel_sale(sale, reason="Financing fell through")
        self.assertTrue(VehicleSale.objects.filter(pk=sale.pk).exists())
        sale.refresh_from_db()
        self.assertEqual(sale.status, VehicleSale.STATUS_CANCELLED)


class Phase2TenantIsolationTests(DealerSalesPhase2TestCase):
    def test_quotation_scoped_to_tenant(self):
        quotation = create_quotation(vehicle=self.owned_vehicle, customer=self.buyer, quoted_price=Decimal("500000.00"))
        self.assertEqual(
            VehicleSaleQuotation.objects.filter(pk=quotation.pk, tenant_id=self.other_tenant.id).count(), 0
        )

    def test_sale_scoped_to_tenant(self):
        sale = confirm_sale(vehicle=self.owned_vehicle, buyer=self.buyer, sale_date=date(2026, 1, 1), final_sale_price=Decimal("500000.00"))
        self.assertEqual(VehicleSale.objects.filter(pk=sale.pk, tenant_id=self.other_tenant.id).count(), 0)
