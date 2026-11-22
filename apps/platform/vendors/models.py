"""
Vendor models — accounts payable: a vendor master plus bills recorded
against vendors and payments made to settle them.

Unlike Invoice (a statutory document we issue to a customer), a VendorBill
records a document a vendor already issued to us — there's no PDF to
generate or send; the vendor's own bill is kept as an uploaded attachment.

GST / TDS:
  - VendorBill is header-only (one taxable amount + a single CGST+SGST or
    IGST split), not itemized — a simplification decision for this feature.
  - TDS (Tax Deducted at Source) is computed on the taxable value
    (subtotal), not the GST-inclusive total, matching CBDT Circular
    23/2017 practice. net_payable_amount = total_amount - tds_amount is
    what's actually due to the vendor in cash; the withheld TDS portion is
    a separate statutory liability, never paid out via VendorPayment.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from apps.common.utils.models import BaseModel, SoftArchiveModel
from apps.platform.jobcards.models import indian_fy_code  # noqa: F401 (re-exported for service.py)


class VendorCategory(BaseModel, SoftArchiveModel):
    """
    Tenant-curated classification for vendors (e.g. Parts Supplier, Contractor).
    Mirrors credit_notes.CreditNoteReasonCategory / services.LabourCategory —
    managed in Configuration, gated to tenants with Vendor module access.
    """

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vendor_categories")
    name = models.CharField(max_length=100)
    sort_order = models.SmallIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "vendor_categories"
        ordering = ["sort_order", "name"]
        verbose_name_plural = "vendor categories"
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "tenant",
                condition=models.Q(is_archived=False),
                name="uniq_vendor_category_name_per_tenant_active",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.name


class Vendor(BaseModel, SoftArchiveModel):
    """Tenant-curated vendor/supplier master."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vendors")
    name = models.CharField(max_length=255)
    # Snapshot of VendorCategory.name (free text, not an FK) — same pattern as
    # CreditNote.reason_category / CreditNoteLineItem.labour_category_name:
    # the tenant-curated master drives what's selectable, but a vendor's own
    # tag doesn't silently change if the category is later renamed/archived.
    category = models.CharField(max_length=100, blank=True, default="Other")
    contact_person = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    address = models.TextField(blank=True, default="")
    gstin = models.CharField(max_length=15, blank=True, default="")
    pan = models.CharField(max_length=10, blank=True, default="")
    bank_account_name = models.CharField(max_length=255, blank=True, default="")
    bank_account_number = models.CharField(max_length=30, blank=True, default="")
    bank_ifsc = models.CharField(max_length=11, blank=True, default="")
    bank_name = models.CharField(max_length=255, blank=True, default="")
    payment_terms_days = models.PositiveIntegerField(
        default=0, help_text="Used only as a default due-date suggestion on new bills."
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "vendors"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "tenant",
                condition=models.Q(is_archived=False),
                name="uniq_vendor_name_per_tenant_active",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "is_archived"]),
        ]

    def __str__(self) -> str:
        return self.name


class VendorBillFySequence(BaseModel):
    """Per-tenant, per-financial-year counter for our internal vendor bill reference."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vendor_bill_fy_sequences")
    fy_code = models.CharField(max_length=5, db_index=True)
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "vendor_bill_fy_sequences"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "fy_code"], name="uniq_vendor_bill_fy_seq_per_tenant"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} {self.fy_code} -> {self.last_seq}"


class VendorPaymentFySequence(BaseModel):
    """Per-tenant, per-financial-year counter for vendor payment voucher numbers."""

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vendor_payment_fy_sequences")
    fy_code = models.CharField(max_length=5, db_index=True)
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "vendor_payment_fy_sequences"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "fy_code"], name="uniq_vendor_payment_fy_seq_per_tenant"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} {self.fy_code} -> {self.last_seq}"


class VendorBill(BaseModel):
    """
    A bill recorded against a vendor (accounts payable). Header-only: one
    taxable amount + a single GST split, not itemized line items.

    Financial totals are immutable after issuance; payment_status/amount_paid
    are the only mutable post-issuance fields (maintained by VendorPaymentService).
    """

    STATUS_ISSUED = "issued"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_ISSUED, "Issued"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    PAYMENT_STATUS_UNPAID = "unpaid"
    PAYMENT_STATUS_PARTIAL = "partial"
    PAYMENT_STATUS_PAID = "paid"
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_STATUS_UNPAID, "Unpaid"),
        (PAYMENT_STATUS_PARTIAL, "Partial"),
        (PAYMENT_STATUS_PAID, "Paid"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="vendor_bills")
    vendor = models.ForeignKey("vendors.Vendor", on_delete=models.PROTECT, related_name="bills")

    # Our own internal, FY-sequenced reference — distinct from the vendor's
    # own bill number (captured below as free text), useful for audit/search.
    bill_number = models.CharField(max_length=32, db_index=True)
    fy_code = models.CharField(max_length=5)
    sequence_no = models.PositiveIntegerField()
    vendor_bill_reference = models.CharField(max_length=100, blank=True, default="")

    bill_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    description = models.TextField(blank=True, default="")

    # ── Financial totals (immutable post-issuance) ───────────────────────────
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_interstate = models.BooleanField(default=False)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    round_off_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    tds_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tds_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_payable_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="total_amount minus tds_amount — what's actually due to the vendor in cash.",
    )

    # ── Payment (mutable, maintained by VendorPaymentService) ────────────────
    payment_status = models.CharField(
        max_length=10, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_STATUS_UNPAID, db_index=True,
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Cancellation (never hard-deleted) ─────────────────────────────────────
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ISSUED, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    cancellation_reason = models.TextField(blank=True, default="")

    # Relative MEDIA_ROOT path (LOCAL) or S3 object key for the vendor's own
    # bill scan/photo, via core.storage.upload_document_file.
    attachment = models.CharField(max_length=500, blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "vendor_bills"
        ordering = ["-created_at", "-bill_number"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "bill_number"], name="uniq_vendor_bill_number_per_tenant"),
        ]
        indexes = [
            models.Index(fields=["tenant", "vendor"]),
            models.Index(fields=["tenant", "payment_status"]),
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.bill_number} ({self.payment_status})"


class VendorPayment(BaseModel):
    """
    Payment made to a vendor. Immutable except for voiding.

    vendor_bill is nullable — null means an on-account/advance payment not
    tied to any specific bill, reducing the vendor's overall running balance.
    """

    MODE_CASH = "cash"
    MODE_UPI = "upi"
    MODE_CARD = "card"
    MODE_BANK_TRANSFER = "bank_transfer"
    MODE_CHEQUE = "cheque"
    PAYMENT_MODE_CHOICES = [
        (MODE_CASH, "Cash"),
        (MODE_UPI, "UPI"),
        (MODE_CARD, "Card"),
        (MODE_BANK_TRANSFER, "Bank Transfer"),
        (MODE_CHEQUE, "Cheque"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="vendor_payments")
    vendor = models.ForeignKey("vendors.Vendor", on_delete=models.PROTECT, related_name="payments")
    vendor_bill = models.ForeignKey(
        "vendors.VendorBill", on_delete=models.SET_NULL, null=True, blank=True, related_name="payments"
    )

    payment_number = models.CharField(max_length=32, db_index=True)
    fy_code = models.CharField(max_length=5)
    sequence_no = models.PositiveIntegerField()

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES)
    payment_reference = models.CharField(max_length=255, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    is_voided = models.BooleanField(default=False, db_index=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    void_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "vendor_payments"
        ordering = ["-created_at", "-payment_number"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "payment_number"], name="uniq_vendor_payment_number_per_tenant"),
        ]
        indexes = [
            models.Index(fields=["tenant", "vendor"]),
            models.Index(fields=["tenant", "vendor_bill"]),
        ]

    def __str__(self) -> str:
        return f"{self.payment_number} · {self.amount} · {self.payment_mode}"
