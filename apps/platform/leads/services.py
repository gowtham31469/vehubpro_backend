"""Service-layer functions for Lead creation, status transitions, and
conversion — either into a customers.Customer (satisfying
VehicleSaleQuotation.customer's PROTECT FK, with everything past that point
being dealer_sales' own, untouched responsibility), or, for trade-in leads,
all the way into a new portfolio.InventoryVehicle backed by a
dealer_sales.VehicleAcquisition(acquisition_method="trade_in") record — the
same record any other trade-in acquisition uses. That one import is
deliberate: VehicleAcquisition is "how a vehicle entered stock," a standalone
log entry with no FK back into the Quotation/Negotiation/Reservation/Booking/
Sale pipeline, so reusing it here doesn't couple leads to dealer_sales'
sales-pipeline state machine at all — it would be pure duplication not to."""
from __future__ import annotations

from datetime import date

from django.db import transaction

from apps.platform.customers.models import Customer
from apps.platform.dealer_sales.models import VehicleAcquisition
from apps.platform.leads.models import Lead, LeadStatusEvent
from apps.platform.modules.models import UserSubmodulePermission
from apps.platform.notifications.models import Notification
from apps.platform.portfolio.models import InventoryVehicle


class LeadError(Exception):
    """Base error for lead service failures."""


class LostReasonRequired(LeadError):
    pass


def _notify_leads_viewers(lead: Lead, *, title: str, message: str, link: str = "/admin/portfolio/leads") -> None:
    recipient_ids = (
        UserSubmodulePermission.objects.filter(
            tenant_id=lead.tenant_id,
            is_active=True,
            user__is_archived=False,
            submodule_permission__submodule__key="leads",
            submodule_permission__permission__key="view",
        )
        .values_list("user_id", flat=True)
        .distinct()
    )
    Notification.objects.bulk_create(
        [
            Notification(tenant_id=lead.tenant_id, user_id=recipient_id, title=title, message=message, link=link)
            for recipient_id in recipient_ids
        ]
    )


@transaction.atomic
def create_lead(*, tenant_id, created_by=None, changed_by=None, **fields) -> Lead:
    """
    Creates a Lead plus its initial LeadStatusEvent, and notifies every staff
    user with 'view' permission on the leads submodule. Used by both the
    staff "Add Lead" endpoint (created_by/changed_by = the staff user) and the
    anonymous public enquiry endpoint (created_by=None, changed_by=None).
    """
    lead = Lead.objects.create(tenant_id=tenant_id, created_by=created_by, status=Lead.STATUS_NEW, **fields)

    LeadStatusEvent.objects.create(
        lead=lead,
        from_status=None,
        to_status=Lead.STATUS_NEW,
        note=lead.message,
        changed_by=changed_by,
    )

    vehicle_label = None
    if lead.vehicle_id:
        vehicle = lead.vehicle
        vehicle_label = f"{vehicle.year} {vehicle.brand.name} {vehicle.vehicle_model.name}"
    subject = f"about the {vehicle_label}" if vehicle_label else "for a car"
    _notify_leads_viewers(
        lead,
        title="New lead",
        message=f"{lead.full_name} enquired {subject}.",
    )

    return lead


@transaction.atomic
def transition_lead_status(
    lead: Lead, to_status: str, *, note: str | None = None, changed_by=None, lost_reason=None, lost_notes=None
) -> Lead:
    if to_status == Lead.STATUS_LOST and not lost_reason:
        raise LostReasonRequired("A lost reason is required when marking a lead as lost.")

    previous_status = lead.status
    lead.status = to_status
    if to_status == Lead.STATUS_LOST:
        lead.lost_reason = lost_reason
        lead.lost_notes = lost_notes or ""
    update_fields = ["status", "lost_reason", "lost_notes", "updated_at"]
    lead.save(update_fields=update_fields)

    if to_status != previous_status:
        LeadStatusEvent.objects.create(
            lead=lead,
            from_status=previous_status,
            to_status=to_status,
            note=note,
            changed_by=changed_by,
        )

    return lead


@transaction.atomic
def convert_lead_to_customer(lead: Lead, *, customer: Customer | None = None, new_customer_fields=None, created_by=None) -> Customer:
    """
    Links an existing Customer, or creates one from new_customer_fields
    (defaulting from the Lead's own snapshotted contact info). Sets
    lead.customer, flips status to 'converted', and writes a LeadStatusEvent.
    Returns the Customer — the caller (frontend) decides what to do next
    (e.g. deep-link into starting a VehicleSaleQuotation); this function does
    not call into dealer_sales at all.
    """
    if customer is None:
        fields = dict(new_customer_fields or {})
        fields.setdefault("full_name", lead.full_name)
        fields.setdefault("phone", lead.phone)
        fields.setdefault("email", lead.email)
        customer = Customer.objects.create(tenant_id=lead.tenant_id, **fields)

    previous_status = lead.status
    lead.customer = customer
    lead.status = Lead.STATUS_CONVERTED
    lead.save(update_fields=["customer", "status", "updated_at"])

    if previous_status != Lead.STATUS_CONVERTED:
        LeadStatusEvent.objects.create(
            lead=lead,
            from_status=previous_status,
            to_status=Lead.STATUS_CONVERTED,
            note=f"Converted to customer {customer.full_name}.",
            changed_by=created_by,
        )

    return customer


@transaction.atomic
def convert_lead_to_inventory(
    lead: Lead,
    *,
    vehicle_type,
    brand,
    vehicle_model,
    fuel_type,
    year,
    mileage_km=0,
    registration_no="",
    listing_price=0,
    purchase_price=None,
    acquisition_date=None,
    created_by=None,
) -> InventoryVehicle:
    """
    Trade-in leads only: creates the new InventoryVehicle staff appraised the
    customer's car into, plus the VehicleAcquisition(acquisition_method=
    "trade_in") record logging how it was acquired. Auto-converts the lead to
    a Customer first if that hasn't happened yet (a trade-in always needs a
    seller_customer on record). Sets lead.converted_vehicle, flips status to
    'converted', and writes a LeadStatusEvent.
    """
    customer = lead.customer
    if customer is None:
        customer = convert_lead_to_customer(lead, created_by=created_by)

    vehicle = InventoryVehicle.objects.create(
        tenant_id=lead.tenant_id,
        vehicle_type=vehicle_type,
        brand=brand,
        vehicle_model=vehicle_model,
        fuel_type=fuel_type,
        year=year,
        mileage_km=mileage_km,
        registration_no=registration_no,
        listing_price=listing_price,
        inventory_type=InventoryVehicle.INVENTORY_TYPE_OWNED,
        status=InventoryVehicle.STATUS_AVAILABLE,
    )

    VehicleAcquisition.objects.create(
        tenant_id=lead.tenant_id,
        vehicle=vehicle,
        acquisition_date=acquisition_date or date.today(),
        seller_customer=customer,
        seller_name=lead.full_name,
        seller_phone=lead.phone,
        purchase_price=purchase_price,
        acquisition_method=VehicleAcquisition.METHOD_TRADE_IN,
        odometer_reading=mileage_km,
        created_by=created_by,
    )

    previous_status = lead.status
    lead.converted_vehicle = vehicle
    lead.status = Lead.STATUS_CONVERTED
    lead.save(update_fields=["converted_vehicle", "status", "updated_at"])

    if previous_status != Lead.STATUS_CONVERTED:
        LeadStatusEvent.objects.create(
            lead=lead,
            from_status=previous_status,
            to_status=Lead.STATUS_CONVERTED,
            note=f"Converted to inventory vehicle {vehicle.year} {brand.name} {vehicle_model.name}.",
            changed_by=created_by,
        )

    return vehicle
