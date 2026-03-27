from django.db import models

from apps.common.utils.models import BaseModel, SoftArchiveModel


class Customer(BaseModel, SoftArchiveModel):
    STATUS_CHOICES = (
        ("active", "Active"),
        ("inactive", "Inactive"),
    )

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="customers")
    customer_code = models.CharField(max_length=32, null=True, blank=True)
    full_name = models.CharField(max_length=255)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=20)
    alternate_phone = models.CharField(max_length=20, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    state = models.ForeignKey(
        "masters.State",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customers",
    )
    city = models.ForeignKey(
        "masters.City",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="customers",
    )
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "customers"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["full_name"]),
            models.Index(fields=["phone"]),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.phone})"
