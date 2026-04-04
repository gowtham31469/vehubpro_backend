from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.common.utils.models import BaseModel, SoftArchiveModel


class ServiceCategory(BaseModel, SoftArchiveModel):
    """Grouping layer for billable service items (e.g. Engine & Lubrication, Brake System)."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="service_categories"
    )
    name = models.CharField(max_length=100)
    applicable_vehicle_types = ArrayField(
        models.CharField(max_length=50),
        default=list,
        blank=True,
        help_text="Vehicle type codes this category applies to (e.g. ['car','motorcycle']). Empty = all types.",
    )
    icon_code = models.CharField(max_length=50, null=True, blank=True)
    sort_order = models.SmallIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "service_categories"
        ordering = ["sort_order", "name"]
        verbose_name_plural = "service categories"
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "tenant",
                condition=Q(is_archived=False),
                name="uniq_service_category_name_per_tenant_active",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "name"]),
            models.Index(fields=["tenant", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.name


class ServiceItem(BaseModel, SoftArchiveModel):
    """Individual billable service belonging to a category (e.g. Oil Change, Brake Pad Replacement)."""

    UNIT_TYPE_CHOICES = [
        ("per_service", "Per Service"),
        ("per_hour", "Per Hour"),
        ("per_km", "Per KM"),
    ]

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="service_items"
    )
    category = models.ForeignKey(
        "services.ServiceCategory", on_delete=models.CASCADE, related_name="items"
    )
    name = models.CharField(max_length=150)
    description = models.TextField(null=True, blank=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    hsn_code = models.CharField(max_length=8, null=True, blank=True)
    gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    unit_type = models.CharField(max_length=20, choices=UNIT_TYPE_CHOICES, default="per_service")
    applicable_vehicle_types = ArrayField(
        models.CharField(max_length=50),
        default=list,
        blank=True,
        help_text="Overrides category filter. Empty = inherits from category.",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "service_items"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                "category",
                Lower("name"),
                condition=Q(is_archived=False),
                name="uniq_service_item_name_per_category_active",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "category"]),
            models.Index(fields=["tenant", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.category.name} — {self.name}"
