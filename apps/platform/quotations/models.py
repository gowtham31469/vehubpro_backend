from django.conf import settings
from django.db import models
from django.db.models import CheckConstraint, F, Q, UniqueConstraint

from apps.common.utils.models import BaseModel


class Quotation(BaseModel):
    """
    Pre-service estimate/proposal, separate from JobCard (actual work) and Invoice
    (final financial document). See apps.platform.quotations.service for the
    lifecycle/revision/conversion logic.

    Revisions are modeled as sibling rows sharing `quotation_number` — each revision
    is a full Quotation row with its own QuotationLineItem snapshot, linked via
    `parent_quotation`, with exactly one row per (tenant, quotation_number) flagged
    `is_latest` (enforced by a partial unique constraint below). This mirrors
    JobCard/Invoice's flat-model convention instead of introducing a separate
    versions table.
    """

    STATUS_DRAFT = "draft"
    STATUS_SENT = "sent"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELLED = "cancelled"
    STATUS_CONVERTED = "converted"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SENT, "Sent"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_CONVERTED, "Converted"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="quotations")
    quotation_number = models.CharField(max_length=32, db_index=True)
    version = models.PositiveSmallIntegerField(default=1)
    parent_quotation = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="revisions"
    )
    is_latest = models.BooleanField(default=True)
    revision_reason = models.TextField(null=True, blank=True)

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="quotations")
    vehicle = models.ForeignKey("vehicles.ServiceVehicle", on_delete=models.PROTECT, related_name="quotations")

    quotation_date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    round_off_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    notes = models.TextField(null=True, blank=True)
    terms_and_conditions = models.TextField(null=True, blank=True)

    sent_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(null=True, blank=True)
    converted_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotations_created",
    )
    pdf_key = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "quotations"
        constraints = [
            UniqueConstraint(
                fields=["tenant", "quotation_number", "version"],
                name="uniq_quotation_number_version_per_tenant",
            ),
            UniqueConstraint(
                fields=["tenant", "quotation_number"],
                condition=Q(is_latest=True),
                name="uniq_latest_quotation_per_number",
            ),
            CheckConstraint(
                check=Q(valid_until__isnull=True) | Q(valid_until__gte=F("quotation_date")),
                name="quotation_valid_until_after_date",
            ),
            CheckConstraint(
                check=(
                    Q(subtotal__gte=0)
                    & Q(discount_amount__gte=0)
                    & Q(taxable_amount__gte=0)
                    & Q(cgst_amount__gte=0)
                    & Q(sgst_amount__gte=0)
                    & Q(igst_amount__gte=0)
                    & Q(total_amount__gte=0)
                ),
                name="quotation_amounts_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quotation_number} v{self.version}"


class QuotationLineItem(BaseModel):
    """
    A quotation line preserves a pricing snapshot (unit_price, gst_percentage) taken
    at creation time — it must NEVER be recomputed from the current ServiceItem
    catalog price, so historical quotations keep showing what was actually quoted.
    Mirrors JobCardLineItem's shape exactly.
    """

    SERVICE_TYPE_PART = "part"
    SERVICE_TYPE_LABOUR = "labour"
    SERVICE_TYPE_CHOICES = [
        (SERVICE_TYPE_PART, "Part"),
        (SERVICE_TYPE_LABOUR, "Labour"),
    ]

    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="line_items")
    sort_order = models.PositiveSmallIntegerField(default=0)
    service_item = models.ForeignKey(
        "services.ServiceItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotation_lines",
    )
    service_type = models.CharField(max_length=10, choices=SERVICE_TYPE_CHOICES, default=SERVICE_TYPE_LABOUR)
    description = models.CharField(max_length=500)
    detail_text = models.CharField(max_length=500, blank=True, default="")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = "quotation_line_items"
        constraints = [
            CheckConstraint(check=Q(quantity__gt=0), name="quotation_line_quantity_positive"),
            CheckConstraint(check=Q(unit_price__gte=0), name="quotation_line_unit_price_non_negative"),
            CheckConstraint(check=Q(discount_amount__gte=0), name="quotation_line_discount_non_negative"),
            CheckConstraint(check=Q(gst_percentage__gte=0), name="quotation_line_gst_percentage_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.description} x{self.quantity}"


class QuotationFySequence(BaseModel):
    """Per-tenant-per-FY counter for quotation_number allocation (mirrors JobCardFySequence)."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="quotation_fy_sequences")
    fy_code = models.CharField(max_length=5, db_index=True)
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "quotation_fy_sequences"
        constraints = [
            UniqueConstraint(fields=["tenant", "fy_code"], name="uniq_quotation_fy_seq_per_tenant"),
        ]
