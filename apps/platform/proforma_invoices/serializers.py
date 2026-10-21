"""Proforma Invoice / Advance Payment serializers — mirrors
apps.platform.invoices.serializers's structure and conventions (amounts as
strings, list vs detail split, plain input serializers for actions)."""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.platform.invoices.models import Invoice
from apps.platform.proforma_invoices.models import AdvancePayment, ProformaInvoice, ProformaInvoiceLineItem


class ProformaInvoiceLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProformaInvoiceLineItem
        fields = [
            "id", "sort_order", "service_type", "description", "detail_text", "hsn_sac_code",
            "quantity", "unit_price", "discount_amount", "gst_percentage", "price_type",
            "cgst_amount", "sgst_amount", "line_total", "created_at",
        ]
        read_only_fields = fields


class AdvancePaymentSerializer(serializers.ModelSerializer):
    payment_mode_display = serializers.CharField(source="get_payment_mode_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    received_by_name = serializers.SerializerMethodField()
    receipt_pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = AdvancePayment
        fields = [
            "id", "proforma_invoice", "job_card", "amount", "payment_mode", "payment_mode_display",
            "payment_reference", "status", "status_display", "remarks", "received_by_name",
            "receipt_number", "receipt_pdf_url", "applied", "applied_to_invoice",
            "reversed_at", "reversal_reason", "refunded_at", "refund_reason", "created_at",
        ]
        read_only_fields = fields

    def get_received_by_name(self, obj) -> str | None:
        if not obj.received_by_id:
            return None
        try:
            return obj.received_by.pii.get_full_name()
        except Exception:
            return None

    def get_receipt_pdf_url(self, obj) -> str | None:
        if not obj.receipt_pdf_key:
            return None
        try:
            from core.storage.resolve import resolve_media_url
            return resolve_media_url(obj.receipt_pdf_key)
        except Exception:
            return None


class ProformaInvoiceListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    vehicle_registration_no = serializers.CharField(source="vehicle.registration_no", read_only=True)
    jobcard_number = serializers.CharField(source="job_card.jobcard_number", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    advance_received_total = serializers.SerializerMethodField()

    class Meta:
        model = ProformaInvoice
        fields = [
            "id", "proforma_number", "version", "is_latest", "fy_code", "invoice_type", "status",
            "job_card", "jobcard_number", "customer", "customer_name", "vehicle", "vehicle_registration_no",
            "issue_date", "valid_until", "subtotal", "discount_amount", "shop_fees",
            "cgst_amount", "sgst_amount", "igst_amount", "round_off_amount", "total_amount",
            "advance_received_total", "pdf_url", "invoice", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_pdf_url(self, obj) -> str | None:
        if not obj.pdf_key:
            return None
        try:
            from core.storage.resolve import resolve_media_url
            return resolve_media_url(obj.pdf_key)
        except Exception:
            return None

    def get_advance_received_total(self, obj) -> str:
        from django.db.models import Sum
        total = obj.advance_payments.filter(status=AdvancePayment.STATUS_RECEIVED).aggregate(total=Sum("amount"))["total"]
        return str(total or Decimal("0.00"))


class ProformaInvoiceDetailSerializer(ProformaInvoiceListSerializer):
    line_items = ProformaInvoiceLineItemSerializer(many=True, read_only=True)
    advance_payments = AdvancePaymentSerializer(many=True, read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta(ProformaInvoiceListSerializer.Meta):
        fields = ProformaInvoiceListSerializer.Meta.fields + [
            "sequence_no", "parent_proforma", "revision_reason", "terms_and_conditions",
            "customer_notes", "internal_notes", "issued_at", "approved_at", "rejected_at",
            "rejection_reason", "cancelled_at", "cancellation_reason", "converted_at",
            "created_by_name", "line_items", "advance_payments",
        ]
        read_only_fields = fields

    def get_created_by_name(self, obj) -> str | None:
        if not obj.created_by_id:
            return None
        try:
            return obj.created_by.pii.get_full_name()
        except Exception:
            return None


# ── Action input serializers ──────────────────────────────────────────────

class GenerateProformaInvoiceSerializer(serializers.Serializer):
    """Input for POST /job-cards/{id}/generate-proforma-invoice/."""

    invoice_type = serializers.ChoiceField(choices=Invoice.INVOICE_TYPE_CHOICES, default=Invoice.INVOICE_TYPE_GST)


class ReasonInputSerializer(serializers.Serializer):
    """Shared by reject/cancel/reverse/refund — reason is always optional free text."""

    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class ReviseProformaInvoiceSerializer(serializers.Serializer):
    revision_reason = serializers.CharField(max_length=1000)


class RecordAdvancePaymentSerializer(serializers.Serializer):
    """Input for POST /proforma-invoices/{id}/advance-payments/."""

    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    payment_mode = serializers.ChoiceField(choices=AdvancePayment.PAYMENT_MODE_CHOICES)
    payment_reference = serializers.CharField(required=False, allow_blank=True, max_length=255)
    remarks = serializers.CharField(required=False, allow_blank=True, max_length=1000)
