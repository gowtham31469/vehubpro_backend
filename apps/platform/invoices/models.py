"""
Invoice models — converts a completed JobCard into a GST-compliant tax invoice.

Compliance notes
----------------
DPDP Act 2023 / GDPR:
  - Customer PII (name, phone, email, address) is snapshot-encrypted at invoice creation time
    using the same AES-based PIIEncryptor used across the platform (key-versioned, rotatable).
  - Financial totals (subtotal, cgst, sgst, igst, total) are stored in plaintext because
    GST law (CGST Act 2017) mandates retention of tax records for 6–8 years. Erasing them
    would constitute a statutory offence. On a DPDP / GDPR erasure request, only the PII
    snapshot columns are nulled; totals remain untouched.
  - `is_pii_erased` flag signals downstream systems and audit trails that customer identity
    data has been removed from this record.

ISO 27001:
  - Invoice financial fields are immutable after issuance (enforced in InvoiceService.generate).
  - Payment fields (payment_status, payment_mode, amount_paid, payment_reference) are the
    only mutable post-issuance fields, access-controlled to OWNER / MANAGER / ACCOUNTANT roles.
  - All invoice access and mutations must be logged via the platform audit service.

GST (CGST Act 2017):
  - Invoice number format: INV/{FY_CODE}/{6-digit-sequence} — unique per tenant per FY.
  - Sequence allocated via InvoiceFySequence with SELECT FOR UPDATE (no gaps on concurrent saves).
  - CGST + SGST for intra-state transactions; IGST for inter-state (future).
  - Line items are immutable snapshots of the job card at the time of invoicing.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.utils.models import BaseModel
from apps.platform.jobcards.models import indian_fy_code


class InvoiceFySequence(BaseModel):
    """Per-tenant per–financial-year counter for invoice numbers."""

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="invoice_fy_sequences",
    )
    fy_code = models.CharField(max_length=5, db_index=True)
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "invoice_fy_sequences"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "fy_code"],
                name="uniq_invoice_fy_seq_per_tenant",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} {self.fy_code} → {self.last_seq}"


class Invoice(BaseModel):
    """
    GST tax invoice generated from a completed JobCard.

    Financial columns (subtotal … total_amount) are immutable post-issuance.
    PII snapshot columns (*_encrypted, *_key_version) may be nulled on erasure requests.
    """

    PAYMENT_STATUS_UNPAID = "unpaid"
    PAYMENT_STATUS_PARTIAL = "partial"
    PAYMENT_STATUS_PAID = "paid"
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_STATUS_UNPAID, "Unpaid"),
        (PAYMENT_STATUS_PARTIAL, "Partial"),
        (PAYMENT_STATUS_PAID, "Paid"),
    ]

    PAYMENT_MODE_CASH = "cash"
    PAYMENT_MODE_UPI = "upi"
    PAYMENT_MODE_CARD = "card"
    PAYMENT_MODE_BANK_TRANSFER = "bank_transfer"
    PAYMENT_MODE_CHEQUE = "cheque"
    PAYMENT_MODE_CHOICES = [
        (PAYMENT_MODE_CASH, "Cash"),
        (PAYMENT_MODE_UPI, "UPI"),
        (PAYMENT_MODE_CARD, "Card"),
        (PAYMENT_MODE_BANK_TRANSFER, "Bank Transfer"),
        (PAYMENT_MODE_CHEQUE, "Cheque"),
    ]

    # ── Core identity ──────────────────────────────────────────────────────────
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    job_card = models.OneToOneField(
        "jobcards.JobCard",
        on_delete=models.PROTECT,
        related_name="invoice",
    )
    invoice_number = models.CharField(max_length=32, db_index=True)
    fy_code = models.CharField(max_length=5)
    sequence_no = models.PositiveIntegerField()
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_invoices",
    )

    # ── Customer PII snapshots (AES-encrypted, key-versioned, erasable) ────────
    # Name
    customer_name_encrypted = models.TextField(null=True, blank=True)
    customer_name_key_version = models.CharField(max_length=16, blank=True, default="")
    # Phone
    customer_phone_encrypted = models.TextField(null=True, blank=True)
    customer_phone_key_version = models.CharField(max_length=16, blank=True, default="")
    # Email
    customer_email_encrypted = models.TextField(null=True, blank=True)
    customer_email_key_version = models.CharField(max_length=16, blank=True, default="")
    # Address (multi-line)
    customer_address_encrypted = models.TextField(null=True, blank=True)
    customer_address_key_version = models.CharField(max_length=16, blank=True, default="")
    # GSTIN — statutory, stored plaintext for GST filings
    customer_gstin = models.CharField(max_length=15, null=True, blank=True)

    # DPDP / GDPR erasure flag — set True when PII snapshots are nulled
    is_pii_erased = models.BooleanField(default=False)
    pii_erased_at = models.DateTimeField(null=True, blank=True)

    # ── Tenant snapshot (plaintext statutory) ─────────────────────────────────
    tenant_name_snapshot = models.CharField(max_length=255, blank=True, default="")
    tenant_gstin_snapshot = models.CharField(max_length=15, blank=True, default="")
    tenant_address_snapshot = models.TextField(blank=True, default="")

    # ── Vehicle snapshot (non-PII, plaintext) ─────────────────────────────────
    vehicle_registration_no_snapshot = models.CharField(max_length=20, blank=True, default="")
    vehicle_label_snapshot = models.CharField(max_length=255, blank=True, default="")
    vehicle_vin_snapshot = models.CharField(max_length=17, blank=True, default="")
    vehicle_odometer_snapshot = models.PositiveIntegerField(null=True, blank=True)

    # ── Financial totals (IMMUTABLE after issuance — GST statutory) ───────────
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shop_fees = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Payment (mutable, access-controlled) ──────────────────────────────────
    payment_status = models.CharField(
        max_length=10,
        choices=PAYMENT_STATUS_CHOICES,
        default=PAYMENT_STATUS_UNPAID,
        db_index=True,
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = models.TextField(blank=True, default="")

    # ── PDF storage ───────────────────────────────────────────────────────────
    # Relative MEDIA_ROOT path (LOCAL) or S3 object key. Mirrors the same
    # convention used by tenant branding and vehicle photo uploads.
    # Nulled when PII is erased (DPDP/GDPR) because the PDF contains customer
    # personal data baked into the rendered document.
    pdf_key = models.CharField(
        max_length=512,
        null=True,
        blank=True,
        help_text="Relative path (LOCAL) or S3 object key for the generated invoice PDF.",
    )

    class Meta:
        db_table = "invoices"
        ordering = ["-created_at", "-invoice_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "invoice_number"],
                name="uniq_invoice_number_per_tenant",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "payment_status"]),
            models.Index(fields=["tenant", "fy_code"]),
            models.Index(fields=["tenant", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_number} ({self.payment_status})"

    # ── PII accessors ─────────────────────────────────────────────────────────

    def get_customer_name(self) -> str | None:
        if not self.customer_name_encrypted:
            return None
        from apps.common.encryption.pii import encryptor
        return encryptor.decrypt(self.customer_name_encrypted, self.customer_name_key_version)

    def get_customer_phone(self) -> str | None:
        if not self.customer_phone_encrypted:
            return None
        from apps.common.encryption.pii import encryptor
        return encryptor.decrypt(self.customer_phone_encrypted, self.customer_phone_key_version)

    def get_customer_email(self) -> str | None:
        if not self.customer_email_encrypted:
            return None
        from apps.common.encryption.pii import encryptor
        return encryptor.decrypt(self.customer_email_encrypted, self.customer_email_key_version)

    def get_customer_address(self) -> str | None:
        if not self.customer_address_encrypted:
            return None
        from apps.common.encryption.pii import encryptor
        return encryptor.decrypt(self.customer_address_encrypted, self.customer_address_key_version)

    def erase_pii(self) -> None:
        """
        Null all PII snapshot columns in place.
        Call save() after this to persist. Financial totals are intentionally untouched.
        """
        from django.utils import timezone
        self.customer_name_encrypted = None
        self.customer_name_key_version = ""
        self.customer_phone_encrypted = None
        self.customer_phone_key_version = ""
        self.customer_email_encrypted = None
        self.customer_email_key_version = ""
        self.customer_address_encrypted = None
        self.customer_address_key_version = ""
        self.customer_gstin = None
        self.is_pii_erased = True
        self.pii_erased_at = timezone.now()
        # The PDF contains customer PII baked into the rendered document.
        # Null the key so the stored file is no longer referenced (caller
        # must also delete the physical file via delete_stored_media).
        self.pdf_key = None


class InvoiceLineItem(BaseModel):
    """
    Point-in-time snapshot of a job card line item.
    Immutable after creation — never update, never delete for GST compliance.
    """

    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.PROTECT,
        related_name="line_items",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    description = models.CharField(max_length=500)
    detail_text = models.CharField(max_length=500, blank=True, default="")
    hsn_sac_code = models.CharField(max_length=20, blank=True, default="")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = "invoice_line_items"
        ordering = ["sort_order", "created_at"]
        indexes = [
            models.Index(fields=["invoice", "sort_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_id} · {self.description[:40]}"


class InvoicePayment(BaseModel):
    """
    Immutable payment record against an invoice.
    """

    invoice = models.ForeignKey(
        "invoices.Invoice",
        on_delete=models.CASCADE,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_mode = models.CharField(
        max_length=20,
        choices=Invoice.PAYMENT_MODE_CHOICES,
    )
    payment_reference = models.CharField(max_length=255, blank=True, default="")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_invoice_payments",
    )

    class Meta:
        db_table = "invoice_payments"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["invoice", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_id} · {self.amount} · {self.payment_mode}"
