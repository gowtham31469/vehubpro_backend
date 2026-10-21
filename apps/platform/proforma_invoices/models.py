"""
Proforma Invoice + Advance Payment models.

A ProformaInvoice is a preliminary estimate generated FROM an existing
JobCard's current state — same snapshot relationship Invoice has to JobCard
(see apps.platform.invoices.service.InvoiceService.generate), not an
independently-authored document the way apps.platform.quotations.Quotation
is. It is explicitly NOT a GST tax invoice (see pdf_generator.py — the PDF's
doc_type_label is literally "PROFORMA INVOICE — NOT A TAX INVOICE").

AdvancePayment records money collected against an issued/approved proforma,
before the real Invoice exists. At conversion (ProformaInvoiceService.
convert_to_invoice), received-and-unapplied advances are credited into the
new Invoice via the existing, unmodified InvoiceService.record_payment() —
see service.py for the exact mechanics.

Revision: like Quotation, a proforma that needs to change after being issued
gets a new sibling row (version N+1, same proforma_number, parent_proforma
FK, is_latest flag) rather than mutating the issued document in place. Unlike
Quotation's create_revision() (which copies the OLD version's own lines), a
proforma revision RE-SNAPSHOTS from the job card's CURRENT line items/totals
— a proforma exists to reflect what the job card actually costs right now,
so a revision is "the estimate changed because the job changed," not "let me
hand-edit a frozen draft." See ProformaInvoiceService.create_revision().
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import CheckConstraint, F, Q, UniqueConstraint

from apps.common.utils.models import BaseModel
from apps.platform.invoices.models import INVOICE_TYPE_CHOICES, INVOICE_TYPE_GST


class ProformaInvoiceFySequence(BaseModel):
    """Per-tenant, per-financial-year counter for proforma numbers (prefix 'PI')."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="proforma_invoice_fy_sequences"
    )
    fy_code = models.CharField(max_length=5, db_index=True)
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "proforma_invoice_fy_sequences"
        constraints = [
            UniqueConstraint(fields=["tenant", "fy_code"], name="uniq_proforma_fy_seq_per_tenant"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} {self.fy_code} → {self.last_seq}"


class AdvanceReceiptFySequence(BaseModel):
    """Per-tenant, per-financial-year counter for advance-receipt numbers (prefix 'RCPT') —
    independent from proforma numbering, same idiom as GST/Non-GST invoices having
    independent InvoiceFySequence rows."""

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="advance_receipt_fy_sequences"
    )
    fy_code = models.CharField(max_length=5, db_index=True)
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "advance_receipt_fy_sequences"
        constraints = [
            UniqueConstraint(fields=["tenant", "fy_code"], name="uniq_advance_receipt_fy_seq_per_tenant"),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} {self.fy_code} → {self.last_seq}"


class ProformaInvoice(BaseModel):
    """
    Preliminary estimate generated from a JobCard's current state. Not a GST
    tax invoice — see the module docstring and pdf_generator.py.
    """

    STATUS_DRAFT = "draft"
    STATUS_ISSUED = "issued"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELLED = "cancelled"
    STATUS_CONVERTED = "converted"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ISSUED, "Issued"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_CONVERTED, "Converted"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="proforma_invoices")
    # Not unique/not OneToOne — a job card may accumulate several historical
    # proformas over its lifecycle (same rationale as Invoice.job_card).
    job_card = models.ForeignKey("jobcards.JobCard", on_delete=models.PROTECT, related_name="proforma_invoices")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="proforma_invoices")
    vehicle = models.ForeignKey("vehicles.ServiceVehicle", on_delete=models.PROTECT, related_name="proforma_invoices")

    proforma_number = models.CharField(max_length=32, db_index=True)
    fy_code = models.CharField(max_length=5)
    sequence_no = models.PositiveIntegerField()
    invoice_type = models.CharField(
        max_length=10, choices=INVOICE_TYPE_CHOICES, default=INVOICE_TYPE_GST,
        help_text="Decided once at generation time, carried forward unchanged at conversion.",
    )

    version = models.PositiveSmallIntegerField(default=1)
    parent_proforma = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="revisions"
    )
    is_latest = models.BooleanField(default=True)
    revision_reason = models.TextField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)

    issue_date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)

    # ── Totals — snapshotted verbatim (GST) or zeroed+recomputed (Non-GST)
    #     from the job card at generation/revision time, same as Invoice. ──────
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shop_fees = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    round_off_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    terms_and_conditions = models.TextField(null=True, blank=True)
    customer_notes = models.TextField(null=True, blank=True)
    internal_notes = models.TextField(null=True, blank=True)

    issued_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(null=True, blank=True)
    converted_at = models.DateTimeField(null=True, blank=True)

    # Set once converted — links the estimate to the real tax invoice it became.
    invoice = models.ForeignKey(
        "invoices.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="source_proformas"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="proforma_invoices_created",
    )
    pdf_key = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "proforma_invoices"
        ordering = ["-created_at", "-proforma_number"]
        constraints = [
            UniqueConstraint(
                fields=["tenant", "proforma_number", "version"],
                name="uniq_proforma_number_version_per_tenant",
            ),
            UniqueConstraint(
                fields=["tenant", "proforma_number"],
                condition=Q(is_latest=True),
                name="uniq_latest_proforma_per_number",
            ),
            CheckConstraint(
                check=Q(valid_until__isnull=True) | Q(valid_until__gte=F("issue_date")),
                name="proforma_valid_until_after_issue_date",
            ),
            CheckConstraint(
                check=(
                    Q(subtotal__gte=0) & Q(discount_amount__gte=0) & Q(shop_fees__gte=0)
                    & Q(cgst_amount__gte=0) & Q(sgst_amount__gte=0) & Q(igst_amount__gte=0)
                    & Q(total_amount__gte=0)
                ),
                name="proforma_amounts_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "job_card"]),
            models.Index(fields=["tenant", "fy_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.proforma_number} v{self.version} ({self.status})"


class ProformaInvoiceLineItem(BaseModel):
    """
    Point-in-time snapshot of a job card line item at proforma generation/
    revision time. Never recomputed from the live catalog afterward — same
    "never silently rewrite a historical document" rule as InvoiceLineItem.
    """

    SERVICE_TYPE_PART = "part"
    SERVICE_TYPE_LABOUR = "labour"
    SERVICE_TYPE_CHOICES = [
        (SERVICE_TYPE_PART, "Part"),
        (SERVICE_TYPE_LABOUR, "Labour"),
    ]
    PRICE_TYPE_EXCLUSIVE = "exclusive"
    PRICE_TYPE_INCLUSIVE = "inclusive"
    PRICE_TYPE_CHOICES = [
        (PRICE_TYPE_EXCLUSIVE, "Exclusive of GST"),
        (PRICE_TYPE_INCLUSIVE, "Inclusive of GST"),
    ]

    proforma_invoice = models.ForeignKey(
        "proforma_invoices.ProformaInvoice", on_delete=models.CASCADE, related_name="line_items"
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    service_item = models.ForeignKey(
        "services.ServiceItem", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="proforma_invoice_lines",
    )
    service_type = models.CharField(max_length=10, choices=SERVICE_TYPE_CHOICES, default=SERVICE_TYPE_LABOUR)
    description = models.CharField(max_length=500)
    detail_text = models.CharField(max_length=500, blank=True, default="")
    hsn_sac_code = models.CharField(max_length=20, blank=True, default="")
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    price_type = models.CharField(max_length=10, choices=PRICE_TYPE_CHOICES, default=PRICE_TYPE_EXCLUSIVE)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = "proforma_invoice_line_items"
        ordering = ["sort_order", "created_at"]
        indexes = [
            models.Index(fields=["proforma_invoice", "sort_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.proforma_invoice_id} · {self.description[:40]}"


class AdvancePayment(BaseModel):
    """
    Money collected against an issued/approved ProformaInvoice, before the
    real Invoice exists. Append-only ledger row, same shape/intent as
    InvoicePayment, plus a status lifecycle (pending/received/failed/
    reversed/refunded) that InvoicePayment doesn't need — every InvoicePayment
    is an after-the-fact record of money already in hand; an AdvancePayment
    can additionally represent a gateway payment still awaiting manual
    confirmation (no gateway webhook integration exists anywhere in this
    codebase — see service.py).
    """

    STATUS_PENDING = "pending"
    STATUS_RECEIVED = "received"
    STATUS_FAILED = "failed"
    STATUS_REVERSED = "reversed"
    STATUS_REFUNDED = "refunded"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RECEIVED, "Received"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REVERSED, "Reversed"),
        (STATUS_REFUNDED, "Refunded"),
    ]

    MODE_CASH = "cash"
    MODE_UPI = "upi"
    MODE_CARD = "card"
    MODE_BANK_TRANSFER = "bank_transfer"
    MODE_CHEQUE = "cheque"
    MODE_ONLINE_GATEWAY = "online_gateway"
    MODE_OTHER = "other"
    PAYMENT_MODE_CHOICES = [
        (MODE_CASH, "Cash"),
        (MODE_UPI, "UPI"),
        (MODE_CARD, "Card"),
        (MODE_BANK_TRANSFER, "Bank Transfer"),
        (MODE_CHEQUE, "Cheque"),
        (MODE_ONLINE_GATEWAY, "Online Payment Gateway"),
        (MODE_OTHER, "Other"),
    ]
    # Modes recorded manually by staff as an already-completed transaction —
    # these go straight to 'received'. Only the gateway mode starts 'pending'.
    MANUAL_MODES = {MODE_CASH, MODE_UPI, MODE_CARD, MODE_BANK_TRANSFER, MODE_CHEQUE, MODE_OTHER}

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="advance_payments")
    proforma_invoice = models.ForeignKey(
        "proforma_invoices.ProformaInvoice", on_delete=models.CASCADE, related_name="advance_payments"
    )
    # Denormalized copy of proforma_invoice.job_card_id — convenient querying
    # ("all advances against this job card"), never a second source of truth
    # (always set from the proforma at creation time, never updated after).
    job_card = models.ForeignKey(
        "jobcards.JobCard", on_delete=models.PROTECT, related_name="advance_payments"
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES)
    payment_reference = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_RECEIVED, db_index=True)
    remarks = models.TextField(blank=True, default="")

    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="advance_payments_received",
    )

    # ── Receipt ────────────────────────────────────────────────────────────
    receipt_number = models.CharField(max_length=32, blank=True, default="")
    receipt_pdf_key = models.CharField(max_length=512, null=True, blank=True)

    # ── Application to the final invoice at conversion time ───────────────
    applied = models.BooleanField(default=False)
    applied_to_invoice = models.ForeignKey(
        "invoices.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="applied_advance_payments"
    )

    # ── Reversal / refund tracking ──────────────────────────────────────────
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.TextField(blank=True, default="")
    refunded_at = models.DateTimeField(null=True, blank=True)
    refund_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "advance_payments"
        ordering = ["created_at"]
        constraints = [
            CheckConstraint(check=Q(amount__gt=0), name="advance_payment_amount_positive"),
        ]
        indexes = [
            models.Index(fields=["tenant", "proforma_invoice"]),
            models.Index(fields=["tenant", "job_card"]),
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.proforma_invoice_id} · {self.amount} · {self.payment_mode} ({self.status})"
