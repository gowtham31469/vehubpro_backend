from __future__ import annotations

from datetime import date

from django.conf import settings
from django.db import models

from apps.common.utils.models import BaseModel


def indian_fy_code(d: date | None = None) -> str:
    """FY string like 25-26 (April–March)."""
    if d is None:
        from django.utils import timezone

        d = timezone.now().date()
    if d.month >= 4:
        y1 = d.year % 100
        y2 = (d.year + 1) % 100
    else:
        y1 = (d.year - 1) % 100
        y2 = d.year % 100
    return f"{y1:02d}-{y2:02d}"


class JobCardFySequence(BaseModel):
    """Per-tenant per–financial-year counter for job card numbers."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="job_card_fy_sequences")
    fy_code = models.CharField(max_length=5, db_index=True)
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "job_card_fy_sequences"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "fy_code"], name="uniq_jobcard_fy_seq_per_tenant"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} {self.fy_code} → {self.last_seq}"


class JobCardLineItem(BaseModel):
    """Billable line on a job card (normalized; optional link to catalog ServiceItem)."""

    job_card = models.ForeignKey(
        "jobcards.JobCard",
        on_delete=models.CASCADE,
        related_name="line_items",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    service_item = models.ForeignKey(
        "services.ServiceItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="job_card_lines",
    )
    description = models.CharField(max_length=500)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    detail_text = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Optional secondary line (e.g. catalog detail); avoid unnecessary PII.",
    )

    class Meta:
        db_table = "job_card_line_items"
        ordering = ["sort_order", "created_at"]
        indexes = [
            models.Index(fields=["job_card", "sort_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.job_card_id} · {self.description[:40]}"


class JobCard(BaseModel):
    """Operational job card per PRD §4.5 (tenant-scoped)."""

    STATUS_DRAFT = "draft"
    STATUS_CONFIRMED = "confirmed"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_ON_HOLD = "on_hold"
    STATUS_COMPLETED = "completed"
    STATUS_INVOICED = "invoiced"
    STATUS_DELIVERED = "delivered"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_IN_PROGRESS, "In progress"),
        (STATUS_ON_HOLD, "On hold"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_INVOICED, "Invoiced"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="job_cards")
    jobcard_number = models.CharField(max_length=32, db_index=True)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="job_cards")
    vehicle = models.ForeignKey("vehicles.ServiceVehicle", on_delete=models.PROTECT, related_name="job_cards")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shop_fees = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Non-GST shop / handling fee added after tax on the job card.",
    )
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    assigned_technician = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_job_cards",
    )
    estimated_delivery = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    km_reading = models.PositiveIntegerField(null=True, blank=True)
    next_service_km = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "job_cards"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "jobcard_number"], name="uniq_jobcard_number_per_tenant"),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "customer"]),
            models.Index(fields=["tenant", "vehicle"]),
        ]

    def __str__(self) -> str:
        return f"{self.jobcard_number} ({self.status})"


# Not registered with django-auditlog: LogEntry inserts can leave changes_text NULL while the
# DB column is NOT NULL, causing 500 on create. Re-enable after ALTER COLUMN changes_text SET DEFAULT '';
# (or auditlog package / migration aligns with your DB).
