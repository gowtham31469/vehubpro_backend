"""
Service layer for the dealer vehicle-inventory workflow (Phase 1: acquisition,
ownership history, vehicle work/expenses, pricing history, timeline,
profitability). Mirrors apps.platform.invoices/quotations's pattern of
putting business logic here rather than in views/serializers.
"""
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.platform.dealer_sales.models import (
    VehicleAcquisition,
    VehicleBooking,
    VehicleDelivery,
    VehicleNegotiation,
    VehiclePriceHistory,
    VehicleReservation,
    VehicleSale,
    VehicleSaleInvoice,
    VehicleSaleInvoicePayment,
    VehicleSaleQuotation,
    VehicleSettlement,
    VehicleTimelineEvent,
    VehicleWorkExpense,
)
from apps.platform.dealer_sales.utils import (
    allocate_next_dealer_quotation_number,
    allocate_next_dealer_sale_invoice_number,
)
from apps.platform.portfolio.models import InventoryVehicle
from core.audit.constants import AuditAction, AuditModule
from core.audit.service import log_audit_event


class DealerSalesError(Exception):
    """Raised for invalid state transitions in the sales workflow (e.g.
    sending an already-cancelled quotation, confirming a second sale on a
    vehicle that already has one). Views catch this and return a 400."""


def record_vehicle_timeline_event(
    *, vehicle, category: str, title: str, description: str = "", metadata: dict | None = None, actor=None
) -> VehicleTimelineEvent:
    """The single authoritative place a new timeline row is created — every
    mutating action in this app should call this instead of writing its own
    history record, so the vehicle detail page has one event feed, not several."""
    return VehicleTimelineEvent.objects.create(
        tenant_id=vehicle.tenant_id,
        vehicle=vehicle,
        category=category,
        title=title,
        description=description or "",
        metadata=metadata or {},
        actor=actor,
    )


def record_price_change(
    *, vehicle, price_type: str, old_value, new_value, user=None, reason: str = ""
) -> VehiclePriceHistory:
    """
    Writes a VehiclePriceHistory row + a timeline event for a price change.
    Called from apps.platform.portfolio.serializers.InventoryVehicleSerializer.update()
    whenever listing_price/original_price actually changes — one-directional
    portfolio -> dealer_sales dependency, no import cycle (dealer_sales never
    imports portfolio.serializers).
    """
    history = VehiclePriceHistory.objects.create(
        tenant_id=vehicle.tenant_id,
        vehicle=vehicle,
        price_type=price_type,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
        changed_by=user,
    )

    old_display = f"₹{old_value:,.2f}" if old_value is not None else "unset"
    record_vehicle_timeline_event(
        vehicle=vehicle,
        category="pricing",
        title=f"{history.get_price_type_display()} changed",
        description=f"{old_display} → ₹{new_value:,.2f}",
        metadata={"price_type": price_type, "old_value": str(old_value) if old_value is not None else None, "new_value": str(new_value)},
        actor=user,
    )

    log_audit_event(
        actor_id=str(user.id) if user else None,
        actor_type="staff" if user else "system",
        action=AuditAction.UPDATE,
        module=AuditModule.INVENTORY,
        ip_address=None,
        method=None,
        endpoint=None,
        before={"value": str(old_value) if old_value is not None else None},
        after={"value": str(new_value)},
    )

    return history


def get_total_work_expenses(vehicle: InventoryVehicle) -> Decimal:
    """
    Sum of work-expense amounts actually incurred for a vehicle — feeds
    landed cost / profitability / settlement dealer-expense figures, so it
    deliberately excludes 'planned' (budgeted, not yet spent) alongside
    cancelled, counting only in_progress + completed. A vehicle's Work &
    Expenses tab total is a separate, simpler display sum that still shows
    planned rows — this function is specifically the money-actually-spent one.
    """
    total = VehicleWorkExpense.objects.filter(
        vehicle=vehicle, is_archived=False,
        status__in=[VehicleWorkExpense.STATUS_IN_PROGRESS, VehicleWorkExpense.STATUS_COMPLETED],
    ).aggregate(total=Sum("amount"))["total"]
    return total or Decimal("0.00")


def _get_confirmed_sale(vehicle: InventoryVehicle):
    return VehicleSale.objects.filter(vehicle=vehicle, status=VehicleSale.STATUS_CONFIRMED).first()


def compute_profitability(vehicle: InventoryVehicle) -> dict:
    """
    Computed live, never cached/stored, so the numbers are always
    self-explanatory from their inputs (see apps.platform.dealer_sales.models
    docstrings). Once a confirmed VehicleSale exists, real gross_profit/
    gross_margin_percent are reported using its final_sale_price; until then
    the owned-stock figures are estimates based on the current listing price.
    """
    acquisition = getattr(vehicle, "acquisition", None)
    total_work_expenses = get_total_work_expenses(vehicle)
    sale = _get_confirmed_sale(vehicle)

    if vehicle.inventory_type == InventoryVehicle.INVENTORY_TYPE_CUSTOMER_CONSIGNMENT:
        owner_expected_price = acquisition.owner_expected_price if acquisition else None
        result = {
            "inventory_type": vehicle.inventory_type,
            "owner_expected_price": owner_expected_price,
            "listing_price": vehicle.listing_price,
            "dealer_expenses_so_far": total_work_expenses,
        }
        settlement = getattr(sale, "settlement", None) if sale else None
        if settlement:
            result.update({
                "final_sale_price": sale.final_sale_price,
                "commission_amount": settlement.commission_amount,
                "owner_payable": settlement.owner_payable,
                "net_dealer_profit": settlement.net_dealer_profit,
                "settlement_status": settlement.settlement_status,
            })
        else:
            result["note"] = "Commission and owner settlement require a confirmed sale + settlement record."
        return result

    purchase_price = acquisition.purchase_price if acquisition else None
    total_landed_cost = (purchase_price or Decimal("0.00")) + total_work_expenses

    result = {
        "inventory_type": vehicle.inventory_type,
        "purchase_price": purchase_price,
        "total_work_expenses": total_work_expenses,
        "total_landed_cost": total_landed_cost,
        "listing_price": vehicle.listing_price,
    }

    if sale:
        gross_profit = sale.final_sale_price - total_landed_cost
        gross_margin_percent = (
            (gross_profit / sale.final_sale_price * 100) if sale.final_sale_price else None
        )
        result.update({
            "final_sale_price": sale.final_sale_price,
            "gross_profit": gross_profit,
            "gross_margin_percent": gross_margin_percent,
        })
    else:
        result["estimated_profit_at_listing"] = (
            (vehicle.listing_price - total_landed_cost) if vehicle.listing_price is not None else None
        )
        result["note"] = (
            "estimated_profit_at_listing uses the current listing price, not a "
            "confirmed sale. Real gross_profit/gross_margin_percent will appear "
            "once the vehicle is sold."
        )

    return result


def compute_sale_profit(sale: VehicleSale) -> dict | None:
    """
    {profit, margin_percent} for a single CONFIRMED sale, computed the same
    way as compute_profitability() for a vehicle — owned: final_sale_price
    minus purchase_price and work expenses actually incurred; consignment:
    the settlement's net_dealer_profit (margin_percent is None there, since
    "margin on sale price" isn't the right lens for a commission payout).
    Returns None for a consignment sale with no settlement yet (profit not
    finalized) — never for an owned sale, which is always computable.
    Shared by compute_portfolio_profitability_insights() and the Vehicle
    Sales Report so both agree on the same numbers.
    """
    vehicle = sale.vehicle
    if vehicle.inventory_type == InventoryVehicle.INVENTORY_TYPE_CUSTOMER_CONSIGNMENT:
        settlement = getattr(sale, "settlement", None)
        if not settlement:
            return None
        return {"profit": settlement.net_dealer_profit, "margin_percent": None}

    acquisition = getattr(vehicle, "acquisition", None)
    purchase_price = acquisition.purchase_price if acquisition else None
    total_landed_cost = (purchase_price or Decimal("0.00")) + get_total_work_expenses(vehicle)
    profit = sale.final_sale_price - total_landed_cost
    margin_percent = (profit / sale.final_sale_price * 100) if sale.final_sale_price else None
    return {"profit": profit, "margin_percent": margin_percent}


def compute_portfolio_profitability_insights(tenant_id) -> dict:
    """
    Aggregate profitability across every confirmed sale for a tenant, for the
    Inventory list page's Insights section. Reuses the same live-computed
    gross_profit (owned, from final_sale_price - purchase_price - work
    expenses) / net_dealer_profit (consignment, from the stored Settlement)
    math as compute_profitability() for a single vehicle — never cached.

    Consignment sales without a settlement yet are excluded from the
    aggregate (their dealer profit isn't finalized), same as
    compute_profitability()'s per-vehicle behavior.
    """
    sales = VehicleSale.objects.filter(
        tenant_id=tenant_id, status=VehicleSale.STATUS_CONFIRMED,
    ).select_related("vehicle", "vehicle__brand", "vehicle__vehicle_model", "vehicle__acquisition", "settlement")

    owned_count = 0
    owned_total_profit = Decimal("0.00")
    owned_margin_sum = Decimal("0.00")
    owned_margin_count = 0

    consignment_count = 0
    consignment_total_profit = Decimal("0.00")

    performers = []

    for sale in sales:
        profit_data = compute_sale_profit(sale)
        if profit_data is None:
            continue
        vehicle = sale.vehicle
        profit = profit_data["profit"]
        margin_percent = profit_data["margin_percent"]

        if vehicle.inventory_type == InventoryVehicle.INVENTORY_TYPE_CUSTOMER_CONSIGNMENT:
            consignment_count += 1
            consignment_total_profit += profit
        else:
            owned_count += 1
            owned_total_profit += profit
            if margin_percent is not None:
                owned_margin_sum += margin_percent
                owned_margin_count += 1

        performers.append({
            "vehicle_id": str(vehicle.id),
            "vehicle_label": f"{vehicle.year} {vehicle.brand.name} {vehicle.vehicle_model.name}",
            "inventory_type": vehicle.inventory_type,
            "sale_date": sale.sale_date,
            "final_sale_price": sale.final_sale_price,
            "profit": profit,
            "margin_percent": margin_percent,
        })

    performers_by_profit_desc = sorted(performers, key=lambda p: p["profit"], reverse=True)

    return {
        "sold_vehicle_count": owned_count + consignment_count,
        "owned": {
            "count": owned_count,
            "total_gross_profit": owned_total_profit,
            "average_gross_margin_percent": (
                (owned_margin_sum / owned_margin_count) if owned_margin_count else None
            ),
        },
        "consignment": {
            "count": consignment_count,
            "total_net_dealer_profit": consignment_total_profit,
        },
        "combined_total_profit": owned_total_profit + consignment_total_profit,
        "top_performers": performers_by_profit_desc[:5],
        "lowest_performers": list(reversed(performers_by_profit_desc[-5:])),
    }


def sales_report_queryset(tenant_id, *, date_from=None, date_to=None, inventory_type=None, status=None):
    """
    Row source shared by the Vehicle Sales Report's summary, paginated
    preview, and CSV export — a single query so all three always agree.
    Includes cancelled sales unless `status` narrows it (same convention as
    the invoice report's is_cancelled filter): callers decide what to sum,
    this just returns the matching rows ordered newest-first.
    """
    queryset = VehicleSale.objects.filter(tenant_id=tenant_id).select_related(
        "vehicle", "vehicle__brand", "vehicle__vehicle_model", "vehicle__acquisition", "settlement",
        "buyer", "salesperson", "salesperson__pii",
    )
    if date_from:
        queryset = queryset.filter(sale_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(sale_date__lte=date_to)
    if inventory_type in (InventoryVehicle.INVENTORY_TYPE_OWNED, InventoryVehicle.INVENTORY_TYPE_CUSTOMER_CONSIGNMENT):
        queryset = queryset.filter(vehicle__inventory_type=inventory_type)
    if status in (VehicleSale.STATUS_CONFIRMED, VehicleSale.STATUS_CANCELLED):
        queryset = queryset.filter(status=status)
    return queryset.order_by("-sale_date", "-created_at")


# ─────────────────────────────────────────────────────────────────────────
# Phase 2 — Quotation → Negotiation → Reservation → Booking → Sale →
# Delivery → Settlement
# ─────────────────────────────────────────────────────────────────────────


def create_quotation(*, vehicle, customer, quoted_price, valid_until=None, notes="", user=None) -> VehicleSaleQuotation:
    quotation = VehicleSaleQuotation.objects.create(
        tenant_id=vehicle.tenant_id,
        vehicle=vehicle,
        customer=customer,
        quotation_number=allocate_next_dealer_quotation_number(vehicle.tenant_id),
        quoted_price=quoted_price,
        valid_until=valid_until,
        notes=notes,
        created_by=user,
    )
    record_vehicle_timeline_event(
        vehicle=vehicle, category="quotation",
        title=f"Quotation {quotation.quotation_number} created",
        description=f"₹{quoted_price:,.2f} for {customer.full_name}",
        actor=user,
    )
    return quotation


def send_quotation(quotation: VehicleSaleQuotation, *, user=None) -> VehicleSaleQuotation:
    if quotation.status != VehicleSaleQuotation.STATUS_DRAFT:
        raise DealerSalesError("Only a draft quotation can be sent.")
    quotation.status = VehicleSaleQuotation.STATUS_SENT
    quotation.sent_at = timezone.now()
    quotation.save(update_fields=["status", "sent_at", "updated_at"])
    record_vehicle_timeline_event(
        vehicle=quotation.vehicle, category="quotation",
        title=f"Quotation {quotation.quotation_number} sent", actor=user,
    )
    return quotation


def add_negotiation_round(quotation: VehicleSaleQuotation, *, offered_by, amount, notes="", user=None) -> VehicleNegotiation:
    if quotation.status not in (VehicleSaleQuotation.STATUS_SENT, VehicleSaleQuotation.STATUS_NEGOTIATING):
        raise DealerSalesError("Negotiation rounds can only be added to a sent or negotiating quotation.")
    next_round = (quotation.negotiations.count() or 0) + 1
    negotiation = VehicleNegotiation.objects.create(
        quotation=quotation, round_number=next_round, offered_by=offered_by,
        amount=amount, notes=notes, created_by=user,
    )
    if quotation.status == VehicleSaleQuotation.STATUS_SENT:
        quotation.status = VehicleSaleQuotation.STATUS_NEGOTIATING
        quotation.save(update_fields=["status", "updated_at"])
    record_vehicle_timeline_event(
        vehicle=quotation.vehicle, category="negotiation",
        title=f"Round {next_round} — {negotiation.get_offered_by_display()} offered ₹{amount:,.2f}",
        description=notes, actor=user,
    )
    return negotiation


def accept_quotation(quotation: VehicleSaleQuotation, *, user=None) -> VehicleSaleQuotation:
    if quotation.status not in (VehicleSaleQuotation.STATUS_SENT, VehicleSaleQuotation.STATUS_NEGOTIATING):
        raise DealerSalesError("Only a sent or negotiating quotation can be accepted.")
    quotation.status = VehicleSaleQuotation.STATUS_ACCEPTED
    quotation.accepted_at = timezone.now()
    quotation.save(update_fields=["status", "accepted_at", "updated_at"])
    record_vehicle_timeline_event(
        vehicle=quotation.vehicle, category="quotation",
        title=f"Quotation {quotation.quotation_number} accepted", actor=user,
    )
    return quotation


def reject_quotation(quotation: VehicleSaleQuotation, *, reason="", user=None) -> VehicleSaleQuotation:
    quotation.status = VehicleSaleQuotation.STATUS_REJECTED
    quotation.rejected_at = timezone.now()
    quotation.rejection_reason = reason
    quotation.save(update_fields=["status", "rejected_at", "rejection_reason", "updated_at"])
    record_vehicle_timeline_event(
        vehicle=quotation.vehicle, category="quotation",
        title=f"Quotation {quotation.quotation_number} rejected", description=reason, actor=user,
    )
    return quotation


def cancel_quotation(quotation: VehicleSaleQuotation, *, reason="", user=None) -> VehicleSaleQuotation:
    quotation.status = VehicleSaleQuotation.STATUS_CANCELLED
    quotation.cancelled_at = timezone.now()
    quotation.cancellation_reason = reason
    quotation.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])
    record_vehicle_timeline_event(
        vehicle=quotation.vehicle, category="quotation",
        title=f"Quotation {quotation.quotation_number} cancelled", description=reason, actor=user,
    )
    return quotation


def create_reservation(
    *, vehicle, customer, reservation_date, quotation=None, expiry_date=None,
    deposit_amount=None, notes="", user=None,
) -> VehicleReservation:
    if VehicleReservation.objects.filter(
        vehicle=vehicle, customer=customer, status=VehicleReservation.STATUS_ACTIVE,
    ).exists():
        raise DealerSalesError(
            f"{customer.full_name} already has an active reservation on this vehicle. "
            "Cancel it first if the terms need to change."
        )

    reservation = VehicleReservation.objects.create(
        tenant_id=vehicle.tenant_id, vehicle=vehicle, customer=customer, quotation=quotation,
        reservation_date=reservation_date, expiry_date=expiry_date, deposit_amount=deposit_amount,
        notes=notes, created_by=user,
    )
    record_vehicle_timeline_event(
        vehicle=vehicle, category="reservation",
        title="Reservation created", description=f"{customer.full_name}", actor=user,
    )
    return reservation


def cancel_reservation(reservation: VehicleReservation, *, reason="", user=None) -> VehicleReservation:
    if reservation.status != VehicleReservation.STATUS_ACTIVE:
        raise DealerSalesError("Only an active reservation can be cancelled.")
    reservation.status = VehicleReservation.STATUS_CANCELLED
    reservation.cancelled_at = timezone.now()
    reservation.cancellation_reason = reason
    reservation.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])
    record_vehicle_timeline_event(
        vehicle=reservation.vehicle, category="reservation", title="Reservation cancelled",
        description=reason, actor=user,
    )
    return reservation


def _vehicle_has_other_active_booking_or_sale(vehicle, *, exclude_booking_id=None) -> bool:
    active_booking = VehicleBooking.objects.filter(
        vehicle=vehicle, status=VehicleBooking.STATUS_ACTIVE
    ).exclude(id=exclude_booking_id).exists()
    active_sale = VehicleSale.objects.filter(vehicle=vehicle, status=VehicleSale.STATUS_CONFIRMED).exists()
    return active_booking or active_sale


def create_booking(
    *, vehicle, customer, booking_date, reservation=None, quotation=None,
    booking_amount=None, notes="", user=None,
) -> VehicleBooking:
    if reservation is not None and reservation.customer_id != customer.id:
        raise DealerSalesError(
            f"This reservation belongs to {reservation.customer.full_name}, not {customer.full_name} — "
            "a booking can only be linked to a reservation made by the same customer."
        )
    if _vehicle_has_other_active_booking_or_sale(vehicle):
        raise DealerSalesError(
            "This vehicle already has an active booking or confirmed sale. "
            "Cancel it first before creating a new booking."
        )

    booking = VehicleBooking.objects.create(
        tenant_id=vehicle.tenant_id, vehicle=vehicle, customer=customer, reservation=reservation,
        quotation=quotation, booking_date=booking_date, booking_amount=booking_amount,
        notes=notes, created_by=user,
    )
    if reservation is not None:
        reservation.status = VehicleReservation.STATUS_CONVERTED_TO_BOOKING
        reservation.save(update_fields=["status", "updated_at"])

    vehicle.status = InventoryVehicle.STATUS_BOOKED
    vehicle.save(update_fields=["status", "updated_at"])

    record_vehicle_timeline_event(
        vehicle=vehicle, category="booking", title="Booking confirmed",
        description=f"{customer.full_name}", actor=user,
    )
    return booking


def cancel_booking(booking: VehicleBooking, *, reason="", user=None) -> VehicleBooking:
    if booking.status != VehicleBooking.STATUS_ACTIVE:
        raise DealerSalesError("Only an active booking can be cancelled.")
    booking.status = VehicleBooking.STATUS_CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancellation_reason = reason
    booking.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])

    vehicle = booking.vehicle
    if not _vehicle_has_other_active_booking_or_sale(vehicle):
        vehicle.status = InventoryVehicle.STATUS_AVAILABLE
        vehicle.save(update_fields=["status", "updated_at"])

    record_vehicle_timeline_event(
        vehicle=vehicle, category="booking", title="Booking cancelled", description=reason, actor=user,
    )
    return booking


def confirm_sale(
    *, vehicle, buyer, sale_date, final_sale_price, quotation=None, booking=None,
    quoted_price=None, discount_amount=0, salesperson=None, notes="", user=None,
) -> VehicleSale:
    if _get_confirmed_sale(vehicle) is not None:
        raise DealerSalesError("This vehicle already has a confirmed sale.")
    if booking is not None and booking.customer_id != buyer.id:
        raise DealerSalesError(
            f"This booking belongs to {booking.customer.full_name}, not {buyer.full_name} — "
            "a sale can only be linked to a booking made by the same buyer."
        )

    sale = VehicleSale.objects.create(
        tenant_id=vehicle.tenant_id, vehicle=vehicle, buyer=buyer, quotation=quotation, booking=booking,
        sale_date=sale_date, quoted_price=quoted_price, final_sale_price=final_sale_price,
        discount_amount=discount_amount, salesperson=salesperson, notes=notes, created_by=user,
    )

    if booking is not None:
        booking.status = VehicleBooking.STATUS_CONVERTED_TO_SALE
        booking.save(update_fields=["status", "updated_at"])
    if quotation is not None:
        quotation.status = VehicleSaleQuotation.STATUS_CONVERTED
        quotation.converted_at = timezone.now()
        quotation.save(update_fields=["status", "converted_at", "updated_at"])

    # Any OTHER still-active booking on this vehicle (for a different
    # customer) is now moot — the car is sold. Auto-cancel it instead of
    # leaving a dangling "active" booking that no longer means anything.
    other_active_bookings = VehicleBooking.objects.filter(
        vehicle=vehicle, status=VehicleBooking.STATUS_ACTIVE,
    ).exclude(id=getattr(booking, "id", None))
    for other in other_active_bookings:
        other.status = VehicleBooking.STATUS_CANCELLED
        other.cancelled_at = timezone.now()
        other.cancellation_reason = "Vehicle sold to a different buyer."
        other.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])
        record_vehicle_timeline_event(
            vehicle=vehicle, category="booking", title="Booking auto-cancelled",
            description=f"{other.customer.full_name}'s booking — vehicle sold to {buyer.full_name}.", actor=user,
        )

    vehicle.status = InventoryVehicle.STATUS_SOLD
    vehicle.save(update_fields=["status", "updated_at"])

    record_price_change(
        vehicle=vehicle, price_type="final_sale_price", old_value=None, new_value=final_sale_price, user=user,
    )
    record_vehicle_timeline_event(
        vehicle=vehicle, category="sale", title="Vehicle sold",
        description=f"₹{final_sale_price:,.2f} to {buyer.full_name}", actor=user,
    )
    return sale


def cancel_sale(sale: VehicleSale, *, reason="", user=None) -> VehicleSale:
    if sale.status != VehicleSale.STATUS_CONFIRMED:
        raise DealerSalesError("Only a confirmed sale can be cancelled.")
    sale.status = VehicleSale.STATUS_CANCELLED
    sale.cancelled_at = timezone.now()
    sale.cancellation_reason = reason
    sale.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])

    vehicle = sale.vehicle
    if _get_confirmed_sale(vehicle) is None:
        vehicle.status = InventoryVehicle.STATUS_AVAILABLE
        vehicle.save(update_fields=["status", "updated_at"])

    record_vehicle_timeline_event(
        vehicle=vehicle, category="sale", title="Sale cancelled", description=reason, actor=user,
    )
    return sale


def create_delivery(*, sale: VehicleSale, delivery_date, delivered_by=None, handover_notes="", user=None) -> VehicleDelivery:
    delivery = VehicleDelivery.objects.create(
        tenant_id=sale.tenant_id, sale=sale, delivery_date=delivery_date,
        delivered_by=delivered_by, handover_notes=handover_notes, created_by=user,
    )
    vehicle = sale.vehicle
    vehicle.status = InventoryVehicle.STATUS_DELIVERED
    vehicle.save(update_fields=["status", "updated_at"])

    record_vehicle_timeline_event(
        vehicle=vehicle, category="sale", title="Vehicle delivered",
        description=handover_notes, actor=user,
    )
    return delivery


def compute_commission(acquisition: VehicleAcquisition, final_sale_price: Decimal) -> Decimal:
    if acquisition.commission_type == VehicleAcquisition.COMMISSION_FIXED:
        return acquisition.commission_value or Decimal("0.00")
    if acquisition.commission_type == VehicleAcquisition.COMMISSION_PERCENTAGE:
        return (final_sale_price * (acquisition.commission_value or Decimal("0.00")) / Decimal("100")).quantize(Decimal("0.01"))
    if acquisition.commission_type == VehicleAcquisition.COMMISSION_PRICE_DIFFERENCE:
        return final_sale_price - (acquisition.owner_expected_price or Decimal("0.00"))
    return Decimal("0.00")


def create_settlement(sale: VehicleSale, *, notes="", user=None) -> VehicleSettlement:
    vehicle = sale.vehicle
    acquisition = getattr(vehicle, "acquisition", None)
    if acquisition is None:
        raise DealerSalesError("Vehicle has no acquisition record to settle against.")

    commission_amount = compute_commission(acquisition, sale.final_sale_price)
    dealer_expenses_total = get_total_work_expenses(vehicle)
    owner_payable = sale.final_sale_price - commission_amount
    net_dealer_profit = commission_amount - dealer_expenses_total

    settlement = VehicleSettlement.objects.create(
        tenant_id=vehicle.tenant_id, sale=sale,
        commission_type=acquisition.commission_type, commission_value=acquisition.commission_value,
        commission_amount=commission_amount, dealer_expenses_total=dealer_expenses_total,
        owner_payable=owner_payable, net_dealer_profit=net_dealer_profit,
        notes=notes, created_by=user,
    )
    record_vehicle_timeline_event(
        vehicle=vehicle, category="settlement", title="Settlement created",
        description=f"Owner payable ₹{owner_payable:,.2f}", actor=user,
    )
    return settlement


def mark_settlement_paid(settlement: VehicleSettlement, *, settlement_date=None, user=None) -> VehicleSettlement:
    settlement.settlement_status = VehicleSettlement.STATUS_PAID
    settlement.settlement_date = settlement_date or timezone.localdate()
    settlement.save(update_fields=["settlement_status", "settlement_date", "updated_at"])
    record_vehicle_timeline_event(
        vehicle=settlement.sale.vehicle, category="settlement", title="Settlement paid", actor=user,
    )
    return settlement


def _apply_invoice_payment(invoice: VehicleSaleInvoice, amount: Decimal) -> None:
    invoice.amount_paid = invoice.amount_paid + amount
    if invoice.amount_paid >= invoice.sale_amount:
        invoice.payment_status = VehicleSaleInvoice.PAYMENT_STATUS_PAID
    elif invoice.amount_paid > 0:
        invoice.payment_status = VehicleSaleInvoice.PAYMENT_STATUS_PARTIAL
    invoice.save(update_fields=["amount_paid", "payment_status", "updated_at"])


def generate_sale_invoice(sale: VehicleSale, *, notes="", user=None) -> VehicleSaleInvoice:
    vehicle = sale.vehicle
    invoice = VehicleSaleInvoice.objects.create(
        tenant_id=vehicle.tenant_id, sale=sale,
        invoice_number=allocate_next_dealer_sale_invoice_number(vehicle.tenant_id),
        buyer_name_snapshot=sale.buyer.full_name,
        buyer_phone_snapshot=sale.buyer.phone,
        buyer_email_snapshot=sale.buyer.email,
        vehicle_label_snapshot=f"{vehicle.year} {vehicle.brand.name} {vehicle.vehicle_model.name}",
        vehicle_registration_no_snapshot=vehicle.registration_no,
        sale_amount=sale.final_sale_price,
        notes=notes,
        created_by=user,
    )

    # Money already collected before the invoice existed — a reservation
    # deposit and/or a booking amount — gets auto-credited here so staff
    # only need to collect the true remaining balance, not the full price
    # again. booking_amount is the running total at booking time (it already
    # includes any earlier deposit, not on top of it), so it takes priority;
    # the reservation deposit is only used as a fallback when a booking
    # exists but never recorded its own amount.
    booking = sale.booking
    advance_amount = None
    advance_label = ""
    if booking is not None:
        if booking.booking_amount:
            advance_amount = booking.booking_amount
            advance_label = "Booking advance"
        elif booking.reservation is not None and booking.reservation.deposit_amount:
            advance_amount = booking.reservation.deposit_amount
            advance_label = "Reservation deposit"

    if advance_amount:
        credited = min(advance_amount, invoice.sale_amount)
        VehicleSaleInvoicePayment.objects.create(
            invoice=invoice, amount=credited, payment_mode=VehicleSaleInvoicePayment.MODE_ADVANCE,
            payment_reference=advance_label, recorded_by=user,
        )
        _apply_invoice_payment(invoice, credited)

    record_vehicle_timeline_event(
        vehicle=vehicle, category="payment", title=f"Invoice {invoice.invoice_number} generated",
        description=f"{advance_label} of ₹{advance_amount:,.2f} credited" if advance_amount else "",
        actor=user,
    )
    return invoice


def record_sale_invoice_payment(
    invoice: VehicleSaleInvoice, *, amount, payment_mode, payment_reference="", user=None
) -> VehicleSaleInvoicePayment:
    payment = VehicleSaleInvoicePayment.objects.create(
        invoice=invoice, amount=amount, payment_mode=payment_mode,
        payment_reference=payment_reference, recorded_by=user,
    )
    _apply_invoice_payment(invoice, amount)

    record_vehicle_timeline_event(
        vehicle=invoice.sale.vehicle, category="payment",
        title=f"Payment recorded — ₹{amount:,.2f}", description=invoice.get_payment_status_display(), actor=user,
    )
    return payment
