"""
Credit Note models — a statutory GST document (Section 34, CGST Act) issued
against an already-generated Invoice to reduce/reverse billed amounts (full or
partial), after the fact. Unlike Invoice.cancel() (which only voids an UNPAID
invoice outright), a Credit Note is the mechanism for an invoice that may
already be paid, or only needs a partial reduction (a returned part, a
post-sale discount, a billing error, a cancelled job).

Compliance notes
-----------------
GST (CGST Act 2017, Section 34):
  - Must reference the original invoice it credits.
  - Mirrors the original invoice's tax structure (CGST/SGST/IGST), never
    recomputed from a fresh flat rate — scaled proportionally from what was
    actually charged on the credited line(s).
  - Numbered CN/{FY}/{00000}, independent per-tenant-per-FY sequence (same
    idiom as InvoiceFySequence).

Financial model:
  - Invoice.amount_paid is NEVER modified by a credit note — it must stay
    permanently equal to Sum(InvoicePayment.amount) for
    InvoiceService.record_payment()'s own ledger invariant. A credit note
    only reduces what's still owed (an "effective total" layered on top);
    if the credited amount was already paid, the excess is tracked as a
    refund obligation here — never auto-paid, since no payment-gateway API
    exists anywhere in this codebase (same posture as
    proforma_invoices.AdvancePayment's refund tracking).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from apps.common.utils.models import BaseModel, SoftArchiveModel


class CreditNoteReasonCategory(BaseModel, SoftArchiveModel):
    """
    Tenant-curated classification for why a credit note was issued (e.g.
    Pricing Error, Product Return, Goodwill). Mirrors services.LabourCategory
    exactly — managed in Configuration, gated to tenants with Services module
    access (credit notes are a Services-suite feature).
    """

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.CASCADE, related_name="credit_note_reason_categories"
    )
    name = models.CharField(max_length=100)
    sort_order = models.SmallIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "credit_note_reason_categories"
        ordering = ["sort_order", "name"]
        verbose_name_plural = "credit note reason categories"
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "tenant",
                condition=models.Q(is_archived=False),
                name="uniq_credit_note_reason_category_name_per_tenant_active",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "is_active"]),
        ]

    def __str__(self) -> str:
        return self.name


class CreditNoteFySequence(BaseModel):
    """
    Per-tenant, per-financial-year counter for credit note numbers.

    One counter per tenant per FY — unlike InvoiceFySequence, there's no
    GST/Non-GST split here: a credit note always follows the GST-ness of the
    invoice it credits, so it has no numbering duality of its own.
    """

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.CASCADE,
        related_name="credit_note_fy_sequences",
    )
    fy_code = models.CharField(max_length=5, db_index=True)
    last_seq = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "credit_note_fy_sequences"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "fy_code"],
                name="uniq_credit_note_fy_seq_per_tenant",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tenant_id} {self.fy_code} → {self.last_seq}"


class CreditNote(BaseModel):
    """
    A credit note issued against an Invoice — full or partial, for a specific
    reason, with its own immutable tax-breakdown snapshot and (if applicable)
    a tracked refund obligation.
    """

    STATUS_ISSUED = "issued"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_ISSUED, "Issued"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    REFUND_STATUS_NOT_APPLICABLE = "not_applicable"
    REFUND_STATUS_PENDING = "pending"
    REFUND_STATUS_REFUNDED = "refunded"
    REFUND_STATUS_CHOICES = [
        (REFUND_STATUS_NOT_APPLICABLE, "Not Applicable"),
        (REFUND_STATUS_PENDING, "Pending"),
        (REFUND_STATUS_REFUNDED, "Refunded"),
    ]

    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.PROTECT, related_name="credit_notes")
    # PROTECT, not unique — many credit notes may be issued against one
    # invoice over time (several partial credits, or a full one after
    # partials already reduced the remaining creditable amount).
    invoice = models.ForeignKey(
        "invoices.Invoice", on_delete=models.PROTECT, related_name="credit_notes"
    )

    credit_note_number = models.CharField(max_length=32, db_index=True)
    fy_code = models.CharField(max_length=5)
    sequence_no = models.PositiveIntegerField()

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ISSUED, db_index=True)

    reason = models.TextField()
    # Snapshot of CreditNoteReasonCategory.name at issuance time (free text,
    # not an FK) — same pattern as CreditNoteLineItem.labour_category_name:
    # stays correct even if the tenant later renames/archives the category.
    reason_category = models.CharField(max_length=100, blank=True, default="")

    # ── Credited portion's financial snapshot — same shape as Invoice, so
    #     the same money-formatting/PDF helpers apply unchanged. ────────────
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Always 0 — apportioning the original invoice's header-level discount
    # across an arbitrary, staff-picked subset of credited lines has no
    # single correct answer, and GST law doesn't require it. Kept only for
    # template/shape symmetry with Invoice.
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    round_off_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Refund tracking — exact AdvancePayment.refund() shape: a tracked
    #     status flag only, no real money movement (no payment-gateway API
    #     exists anywhere in this codebase to call). ─────────────────────────
    is_refund_applicable = models.BooleanField(default=False)
    refund_status = models.CharField(
        max_length=20, choices=REFUND_STATUS_CHOICES, default=REFUND_STATUS_NOT_APPLICABLE, db_index=True
    )
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    refunded_at = models.DateTimeField(null=True, blank=True)
    refund_reason = models.TextField(blank=True, default="")

    # ── Cancellation — an erroneously-issued credit note can be voided,
    #     restoring its amount to the invoice's creditable pool. ────────────
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="cancelled_credit_notes"
    )
    cancellation_reason = models.TextField(blank=True, default="")

    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="issued_credit_notes"
    )
    pdf_key = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "credit_notes"
        ordering = ["-created_at", "-credit_note_number"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "credit_note_number"], name="uniq_credit_note_number_per_tenant"),
        ]
        indexes = [
            models.Index(fields=["tenant", "invoice"]),
            models.Index(fields=["tenant", "fy_code"]),
            models.Index(fields=["tenant", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.credit_note_number} ({self.status})"


class CreditNoteLineItem(BaseModel):
    """
    Immutable snapshot of a credited portion of one original InvoiceLineItem
    (or a custom, non-line-specific credit when invoice_line_item is null).
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

    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE, related_name="line_items")
    # SET_NULL (not PROTECT like InvoiceLineItem itself) — defensive only;
    # invoice line items are never actually deleted, so this FK realistically
    # never nulls in practice. Null means a custom/non-line-specific credit.
    invoice_line_item = models.ForeignKey(
        "invoices.InvoiceLineItem", on_delete=models.SET_NULL, null=True, blank=True, related_name="credit_note_lines"
    )

    sort_order = models.PositiveSmallIntegerField(default=0)
    service_type = models.CharField(max_length=10, choices=SERVICE_TYPE_CHOICES, default=SERVICE_TYPE_LABOUR)
    description = models.CharField(max_length=500)
    detail_text = models.CharField(max_length=500, blank=True, default="")
    hsn_sac_code = models.CharField(max_length=20, blank=True, default="")
    labour_category_name = models.CharField(max_length=100, blank=True, default="")

    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    price_type = models.CharField(max_length=10, choices=PRICE_TYPE_CHOICES, default=PRICE_TYPE_EXCLUSIVE)
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    class Meta:
        db_table = "credit_note_line_items"
        ordering = ["sort_order", "created_at"]
        indexes = [
            models.Index(fields=["credit_note", "sort_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.credit_note_id} · {self.description[:40]}"
