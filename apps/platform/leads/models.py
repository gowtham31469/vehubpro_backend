from django.conf import settings
from django.db import models

from apps.common.utils.models import BaseModel, SoftArchiveModel


class Lead(BaseModel, SoftArchiveModel):
    """
    A prospective buyer's enquiry, captured before a formal customers.Customer
    record (and therefore before dealer_sales.VehicleSaleQuotation, which
    requires one) exists. Sits chronologically ahead of the whole dealer_sales
    pipeline — VisitRequest, Quotation, Negotiation, Reservation, Booking,
    Sale all assume either a vehicle-specific booking or an existing Customer;
    a Lead is the only record here that can exist with neither.
    """

    ENQUIRY_SPECIFIC_VEHICLE = "specific_vehicle"
    ENQUIRY_GENERAL_SEARCH = "general_search"
    ENQUIRY_TRADE_IN = "trade_in"
    ENQUIRY_TYPE_CHOICES = [
        (ENQUIRY_SPECIFIC_VEHICLE, "Specific Vehicle"),
        (ENQUIRY_GENERAL_SEARCH, "General Search"),
        (ENQUIRY_TRADE_IN, "Trade-In"),
    ]

    SOURCE_WALK_IN = "walk_in"
    SOURCE_PHONE = "phone"
    SOURCE_PUBLIC_ENQUIRY = "public_enquiry"
    SOURCE_VISIT_REQUEST = "visit_request"
    SOURCE_REFERRAL = "referral"
    SOURCE_SOCIAL_MEDIA = "social_media"
    SOURCE_CLASSIFIEDS = "classifieds"
    SOURCE_OTHER = "other"
    SOURCE_CHOICES = [
        (SOURCE_WALK_IN, "Walk-in"),
        (SOURCE_PHONE, "Phone Call"),
        (SOURCE_PUBLIC_ENQUIRY, "Website Enquiry"),
        (SOURCE_VISIT_REQUEST, "Visit Request"),
        (SOURCE_REFERRAL, "Referral"),
        (SOURCE_SOCIAL_MEDIA, "Social Media"),
        (SOURCE_CLASSIFIEDS, "Classifieds/Portal"),
        (SOURCE_OTHER, "Other"),
    ]

    STATUS_NEW = "new"
    STATUS_CONTACTED = "contacted"
    STATUS_QUALIFIED = "qualified"
    STATUS_FOLLOW_UP = "follow_up"
    STATUS_CONVERTED = "converted"
    STATUS_LOST = "lost"
    STATUS_CHOICES = [
        (STATUS_NEW, "New"),
        (STATUS_CONTACTED, "Contacted"),
        (STATUS_QUALIFIED, "Qualified"),
        (STATUS_FOLLOW_UP, "Follow-up"),
        (STATUS_CONVERTED, "Converted"),
        (STATUS_LOST, "Lost"),
    ]

    LOST_REASON_PRICE = "price"
    LOST_REASON_BOUGHT_ELSEWHERE = "bought_elsewhere"
    LOST_REASON_FINANCE_DECLINED = "finance_declined"
    LOST_REASON_UNRESPONSIVE = "unresponsive"
    LOST_REASON_VEHICLE_SOLD = "vehicle_sold"
    LOST_REASON_OTHER = "other"
    LOST_REASON_CHOICES = [
        (LOST_REASON_PRICE, "Price too high"),
        (LOST_REASON_BOUGHT_ELSEWHERE, "Bought elsewhere"),
        (LOST_REASON_FINANCE_DECLINED, "Finance declined"),
        (LOST_REASON_UNRESPONSIVE, "Unresponsive"),
        (LOST_REASON_VEHICLE_SOLD, "Vehicle sold"),
        (LOST_REASON_OTHER, "Other"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="leads")
    vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )
    customer = models.ForeignKey(
        "customers.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )
    # Set only for enquiry_type=trade_in once convert_lead_to_inventory() has
    # run — the NEW InventoryVehicle this lead produced (distinct from
    # `vehicle` above, which is an EXISTING listing the lead is asking about).
    converted_vehicle = models.ForeignKey(
        "portfolio.InventoryVehicle", on_delete=models.SET_NULL, null=True, blank=True, related_name="originating_leads"
    )
    origin_visit_request = models.ForeignKey(
        "portfolio.VisitRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )

    # Snapshotted plain text, same rationale as VisitRequest — the staff list
    # must never need PII decryption just to see who to call.
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    email = models.EmailField(null=True, blank=True)

    enquiry_type = models.CharField(
        max_length=20, choices=ENQUIRY_TYPE_CHOICES, default=ENQUIRY_SPECIFIC_VEHICLE, db_index=True
    )
    preferred_brand = models.ForeignKey(
        "vehicles.VehicleBrand", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )
    # vehicles.BodyType, not VehicleType — BodyType (Hatchback/Sedan/SUV/...)
    # is what InventoryVehicle itself is actually categorized by (despite its
    # own field being misleadingly named "vehicle_type"); VehicleType is a
    # different, unrelated taxonomy used by ServiceVehicle/VehicleModel.
    preferred_vehicle_type = models.ForeignKey(
        "vehicles.BodyType", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads"
    )
    budget_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    budget_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    message = models.TextField(null=True, blank=True)

    # Trade-in intake (enquiry_type=trade_in only) — what the customer told
    # you about THEIR vehicle. Plain text/numbers, not catalog FKs: this car
    # isn't in the tenant's VehicleBrand/VehicleModel catalog yet (it may
    # never be, until someone actually appraises and accepts it), so there's
    # nothing valid to point a FK at until convert_lead_to_inventory() has
    # staff pick/confirm the real catalog entries.
    trade_in_brand = models.CharField(max_length=100, null=True, blank=True)
    trade_in_model = models.CharField(max_length=100, null=True, blank=True)
    trade_in_year = models.PositiveSmallIntegerField(null=True, blank=True)
    trade_in_registration_no = models.CharField(max_length=20, null=True, blank=True)
    trade_in_odometer_km = models.PositiveIntegerField(null=True, blank=True)
    trade_in_expected_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, db_index=True)
    is_self_logged = models.BooleanField(
        default=False, help_text="True when staff entered this directly (walk-in/phone call)."
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_leads"
    )
    next_follow_up_at = models.DateField(null=True, blank=True, db_index=True)
    last_contacted_at = models.DateTimeField(null=True, blank=True)
    staff_notes = models.TextField(null=True, blank=True)

    lost_reason = models.CharField(max_length=30, choices=LOST_REASON_CHOICES, null=True, blank=True)
    lost_notes = models.TextField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_leads"
    )

    class Meta:
        db_table = "leads"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "next_follow_up_at"]),
            models.Index(fields=["tenant", "assigned_to"]),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.status})"


class LeadStatusEvent(BaseModel):
    """One row per status transition on a Lead — the timeline shown in the
    staff admin's Manage modal. The first event (from_status=None) is the
    original enquiry. changed_by=None means it wasn't a staff action (e.g. an
    anonymous public enquiry)."""

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="status_events")
    from_status = models.CharField(max_length=20, null=True, blank=True)
    to_status = models.CharField(max_length=20)
    note = models.TextField(null=True, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lead_status_changes",
    )

    class Meta:
        db_table = "lead_status_events"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.lead_id}: {self.from_status} -> {self.to_status}"
