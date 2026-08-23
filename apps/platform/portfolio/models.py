from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.common.utils.models import BaseModel, SoftArchiveModel


class InventoryFeature(BaseModel, SoftArchiveModel):
    """Tenant-managed key-feature tag (e.g. Sunroof, Leather Seats) for inventory listings."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="inventory_features")
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "inventory_features"
        ordering = ["name"]
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

    STATUS_CHOICES = [
        (STATUS_AVAILABLE, "Available"),
        (STATUS_BOOKED, "Booked"),
        (STATUS_SOLD, "Sold"),
    ]

    TRANSMISSION_AUTOMATIC = "automatic"
    TRANSMISSION_MANUAL = "manual"

    TRANSMISSION_CHOICES = [
        (TRANSMISSION_AUTOMATIC, "Automatic"),
        (TRANSMISSION_MANUAL, "Manual"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="inventory_vehicles")

    vehicle_type = models.ForeignKey("vehicles.VehicleType", on_delete=models.PROTECT, related_name="inventory_vehicles")
    brand = models.ForeignKey("vehicles.VehicleBrand", on_delete=models.PROTECT, related_name="inventory_vehicles")
    vehicle_model = models.ForeignKey("vehicles.VehicleModel", on_delete=models.PROTECT, related_name="inventory_vehicles")
    year = models.SmallIntegerField()

    fuel_type = models.ForeignKey("vehicles.FuelType", on_delete=models.PROTECT, related_name="inventory_vehicles")
    transmission = models.CharField(max_length=20, choices=TRANSMISSION_CHOICES, default=TRANSMISSION_AUTOMATIC)
    mileage_km = models.PositiveIntegerField(default=0, help_text="Odometer reading in kilometers.")
    key_features = models.ManyToManyField(
        InventoryFeature,
        blank=True,
        related_name="inventory_vehicles",
    )

    listing_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    insurance_policy_no = models.CharField(max_length=100, blank=True, default="")
    registration_no = models.CharField(max_length=20, blank=True, default="")
    tax_expiration_date = models.DateField(null=True, blank=True)

    photos = ArrayField(
        models.CharField(max_length=500),
        default=list,
        blank=True,
        help_text="Storage keys (LOCAL path or S3 key) for uploaded listing photos, in display order.",
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_AVAILABLE, db_index=True)

    class Meta:
        db_table = "inventory_vehicles"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "brand"]),
        ]

    def __str__(self) -> str:
        return f"{self.brand.name} {self.vehicle_model.name} ({self.year})"
