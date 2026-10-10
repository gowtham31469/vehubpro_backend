from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.common.utils.models import BaseModel, SoftArchiveModel


class InventoryFeature(BaseModel, SoftArchiveModel):
    """Tenant-managed key-feature tag (e.g. Sunroof, Leather Seats) for inventory listings."""

    CATEGORY_COMFORT = "comfort_convenience"
    CATEGORY_SAFETY = "safety"
    CATEGORY_ENTERTAINMENT = "entertainment_communication"
    CATEGORY_EXTERIOR = "exterior"
    CATEGORY_INTERIOR = "interior"
    CATEGORY_CHOICES = [
        (CATEGORY_COMFORT, "Comfort & Convenience"),
        (CATEGORY_SAFETY, "Safety"),
        (CATEGORY_ENTERTAINMENT, "Entertainment & Communication"),
        (CATEGORY_EXTERIOR, "Exterior"),
        (CATEGORY_INTERIOR, "Interior"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="inventory_features")
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default=CATEGORY_COMFORT)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "inventory_features"
        ordering = ["category", "name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "tenant",
                condition=Q(is_archived=False),
                name="uniq_inventory_feature_name_per_tenant_active",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "name"]),
        ]

    def __str__(self) -> str:
        return self.name


class InventoryVehicle(BaseModel, SoftArchiveModel):
    """Dealership stock vehicle listed for sale (Portfolio module)."""

    STATUS_AVAILABLE = "available"
    STATUS_BOOKED = "booked"
    STATUS_SOLD = "sold"
    STATUS_DELIVERED = "delivered"

    STATUS_CHOICES = [
        (STATUS_AVAILABLE, "Available"),
        (STATUS_BOOKED, "Booked"),
        (STATUS_SOLD, "Sold"),
        (STATUS_DELIVERED, "Delivered"),
    ]

    INVENTORY_TYPE_OWNED = "owned"
    INVENTORY_TYPE_CUSTOMER_CONSIGNMENT = "customer_consignment"

    INVENTORY_TYPE_CHOICES = [
        (INVENTORY_TYPE_OWNED, "Owned"),
        (INVENTORY_TYPE_CUSTOMER_CONSIGNMENT, "Customer Consignment"),
    ]

    TRANSMISSION_AUTOMATIC = "automatic"
    TRANSMISSION_MANUAL = "manual"

    TRANSMISSION_CHOICES = [
        (TRANSMISSION_AUTOMATIC, "Automatic"),
        (TRANSMISSION_MANUAL, "Manual"),
    ]

    # A fixed, universal palette rather than tenant-managed master data (like
    # VehicleBrand/FuelType) — car color is a standard concept, not something
    # a dealership would want to define per-tenant. Mirrored on the frontend
    # (with hex swatches) in AdminInventoryVehicleForm.jsx and
    # PublicInventoryListing.jsx — keep the codes in sync if this changes.
    COLOR_CHOICES = [
        ("white", "White"),
        ("black", "Black"),
        ("silver", "Silver"),
        ("gray", "Gray"),
        ("red", "Red"),
        ("blue", "Blue"),
        ("green", "Green"),
        ("yellow", "Yellow"),
        ("orange", "Orange"),
        ("beige", "Beige"),
        ("purple", "Purple"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="inventory_vehicles")

    # Body shape (Hatchback/Sedan/SUV/...) — a separate master table from the
    # generic VehicleType used by ServiceVehicle/VehicleModel (car/bus/van).
    # Field name kept as `vehicle_type` for API/frontend compatibility even
    # though the target model is now BodyType (see vehicles.models.BodyType).
    vehicle_type = models.ForeignKey("vehicles.BodyType", on_delete=models.PROTECT, related_name="inventory_vehicles")
    brand = models.ForeignKey("vehicles.VehicleBrand", on_delete=models.PROTECT, related_name="inventory_vehicles")
    vehicle_model = models.ForeignKey("vehicles.VehicleModel", on_delete=models.PROTECT, related_name="inventory_vehicles")
    year = models.SmallIntegerField()

    fuel_type = models.ForeignKey("vehicles.FuelType", on_delete=models.PROTECT, related_name="inventory_vehicles")
    transmission = models.CharField(max_length=20, choices=TRANSMISSION_CHOICES, default=TRANSMISSION_AUTOMATIC)
    color = models.CharField(max_length=20, choices=COLOR_CHOICES, blank=True, default="")
    mileage_km = models.PositiveIntegerField(default=0, help_text="Odometer reading in kilometers.")
    key_features = models.ManyToManyField(
        InventoryFeature,
        blank=True,
        related_name="inventory_vehicles",
    )

    listing_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Optional limited-time offer on top of listing_price. When set (and not
    # expired), the public detail page shows original_price struck through,
    # a "₹X OFF" badge, and a "Valid for N day(s)" countdown to offer_valid_until.
    # Both blank means no offer — listing_price displays as a plain price.
    original_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    offer_valid_until = models.DateField(null=True, blank=True)

    insurance_policy_no = models.CharField(max_length=100, blank=True, default="")
    registration_no = models.CharField(max_length=20, blank=True, default="")
    tax_expiration_date = models.DateField(null=True, blank=True)

    photos = ArrayField(
        models.CharField(max_length=500),
        default=list,
        blank=True,
        help_text="Storage keys (LOCAL path or S3 key) for uploaded listing photos, in display order.",
    )
    # A single small resized JPEG copy of photos[0] only — not one thumbnail
    # per photo, to keep storage bounded regardless of how many full-size
    # photos a listing has. Used wherever many cars render at once (public
    # listing grid, homepage cards, admin list). Kept in sync with photos[0]
    # by InventoryVehicleSerializer whenever the first photo changes; falls
    # back to photos[0] itself at read time when empty (e.g. the first photo
    # was removed and the new first photo hasn't been re-thumbnailed yet).
    cover_thumbnail = models.CharField(max_length=500, blank=True, default="")

    # Free-text marketing bullets specific to this one listing (e.g. "3 new
    # tyres", "Bangalore's most affordable car") — deliberately NOT reusable
    # master data like InventoryFeature, since each is a one-off claim about
    # this particular car. Stored as [{"title": str, "description": str}, ...],
    # capped/validated in InventoryVehicleSerializer.
    reasons_to_buy = models.JSONField(default=list, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_AVAILABLE, db_index=True)

    # Owned stock the dealer purchased vs. a customer's vehicle being sold on
    # their behalf (consignment) — see apps.platform.dealer_sales for
    # acquisition/work-expense/pricing tracking keyed off this split. Default
    # "owned" is correct for every pre-existing row — no other concept
    # existed before this field was added.
    inventory_type = models.CharField(
        max_length=25, choices=INVENTORY_TYPE_CHOICES, default=INVENTORY_TYPE_OWNED, db_index=True
    )

    # Manually curated by the tenant — only flagged vehicles appear in the
    # public homepage's "Featured Cars" section (PublicPortfolio.jsx).
    is_featured = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = "inventory_vehicles"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "brand"]),
        ]

    def __str__(self) -> str:
        return f"{self.brand.name} {self.vehicle_model.name} ({self.year})"


class VisitRequest(BaseModel, SoftArchiveModel):
    """A customer's request to visit the showroom for a specific InventoryVehicle."""

    STATUS_PENDING = "pending"
    STATUS_CONTACTED = "contacted"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_CONTACTED, "Contacted"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="visit_requests")
    vehicle = models.ForeignKey(InventoryVehicle, on_delete=models.CASCADE, related_name="visit_requests")
    customer_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="visit_requests"
    )

    # Snapshotted plain text at booking time (like Customer's plain-text
    # contact fields, not UserPII's encrypted ones) so the staff list doesn't
    # need decryption to display who to call.
    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20)
    email = models.EmailField(null=True, blank=True)

    preferred_date = models.DateField(null=True, blank=True)
    preferred_time = models.TimeField(null=True, blank=True)
    message = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    staff_notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "portfolio_visit_requests"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer_user", "vehicle"], name="uniq_visit_request_customer_vehicle"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self) -> str:
        return f"Visit request — {self.full_name} — {self.vehicle_id}"


class VisitRequestStatusEvent(BaseModel):
    """One row per status transition on a VisitRequest — the timeline shown in
    the staff admin's Manage modal. The first event (from_status=None) is the
    customer's original booking; changed_by=None means it wasn't a staff action."""

    visit_request = models.ForeignKey(VisitRequest, on_delete=models.CASCADE, related_name="status_events")
    from_status = models.CharField(max_length=20, null=True, blank=True)
    to_status = models.CharField(max_length=20)
    note = models.TextField(null=True, blank=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visit_request_status_changes",
    )

    class Meta:
        db_table = "portfolio_visit_request_status_events"
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.visit_request_id}: {self.from_status} -> {self.to_status}"
