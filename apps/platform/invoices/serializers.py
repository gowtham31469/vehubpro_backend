"""
Invoice serializers.

Serialization principles
------------------------
- PII fields are NEVER returned as raw encrypted bytes. Decryption happens inside the
  serializer at read time; the decrypted plaintext is returned only on detail views.
- List views use InvoiceListSerializer which omits PII fields entirely.
- Detail views use InvoiceDetailSerializer which decrypts and returns PII (log the access
  in the view layer via the audit service).
- RecordPaymentSerializer is used exclusively for the payment action — it never touches
  financial totals.
- All amounts are returned as strings to preserve precision on the API boundary.
"""
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.platform.invoices.models import Invoice, InvoiceLineItem, InvoicePayment


class InvoiceLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLineItem
        fields = [
            "id",
            "sort_order",
            "service_type",
            "description",
            "detail_text",
            "hsn_sac_code",
            "quantity",
            "unit_price",
            "discount_amount",
            "gst_percentage",
            "cgst_amount",
            "sgst_amount",
            "line_total",
            "created_at",
        ]
        read_only_fields = fields


class InvoicePaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoicePayment
        fields = [
            "id",
            "amount",
            "payment_mode",
            "payment_reference",
            "created_at",
        ]
        read_only_fields = fields


class InvoiceListSerializer(serializers.ModelSerializer):
    """Compact representation for list views — no PII, no line items."""

    balance_due = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()
    cancelled_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "invoice_number",
            "fy_code",
            "job_card",
            "tenant_name_snapshot",
            "vehicle_registration_no_snapshot",
            "vehicle_label_snapshot",
            "subtotal",
            "discount_amount",
            "shop_fees",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "total_amount",
            "payment_status",
            "amount_paid",
            "balance_due",
            "is_pii_erased",
            "is_cancelled",
            "cancelled_at",
            "cancellation_reason",
            "cancelled_by_name",
            "pdf_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_cancelled_by_name(self, obj) -> str | None:
        if not obj.cancelled_by_id:
            return None
        try:
            return obj.cancelled_by.pii.get_full_name()
        except Exception:
            return str(obj.cancelled_by_id)

    def get_balance_due(self, obj) -> str:
        balance = max(Decimal("0"), Decimal(str(obj.total_amount)) - Decimal(str(obj.amount_paid)))
        return str(balance)

    def get_pdf_url(self, obj) -> str | None:
        if not obj.pdf_key:
            return None
        try:
            from core.storage.resolve import resolve_media_url
            return resolve_media_url(obj.pdf_key)
        except Exception:
            return None


class InvoiceDetailSerializer(InvoiceListSerializer):
    """
    Full representation for detail views — includes decrypted PII and line items.
    Access to this serializer must be logged by the calling view (PII_ACCESS audit event).
    """

    customer_name = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    customer_email = serializers.SerializerMethodField()
    customer_address = serializers.SerializerMethodField()
    line_items = InvoiceLineItemSerializer(many=True, read_only=True)
    payments = InvoicePaymentSerializer(many=True, read_only=True)

    class Meta(InvoiceListSerializer.Meta):
        fields = InvoiceListSerializer.Meta.fields + [
            "customer_name",
            "customer_phone",
            "customer_email",
            "customer_address",
            "customer_gstin",
            "tenant_gstin_snapshot",
            "tenant_address_snapshot",
            "vehicle_vin_snapshot",
            "vehicle_odometer_snapshot",
            "vehicle_brand_snapshot",
            "vehicle_model_snapshot",
            "vehicle_engine_no_snapshot",
            "vehicle_year_snapshot",
            "sequence_no",
            "notes",
            "next_service_recommendation",
            "customer_signature",
            "customer_signature_date",
            "admin_signature",
            "admin_signature_date",
            "line_items",
            "payments",
        ]
        # All fields are read-only except signature fields
        read_only_fields = [
            "id",
            "tenant",
            "jobcard_number",
            "invoice_number",
            "fy_code",
            "job_card",
            "tenant_name_snapshot",
            "vehicle_registration_no_snapshot",
            "vehicle_label_snapshot",
            "subtotal",
            "discount_amount",
            "shop_fees",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "total_amount",
            "payment_status",
            "amount_paid",
            "balance_due",
            "is_pii_erased",
            "is_cancelled",
            "cancelled_at",
            "cancellation_reason",
            "cancelled_by_name",
            "pdf_url",
            "created_at",
            "updated_at",
            "customer_name",
            "customer_phone",
            "customer_email",
            "customer_address",
            "customer_gstin",
            "tenant_gstin_snapshot",
            "tenant_address_snapshot",
            "vehicle_vin_snapshot",
            "vehicle_odometer_snapshot",
            "vehicle_brand_snapshot",
            "vehicle_model_snapshot",
            "vehicle_engine_no_snapshot",
            "vehicle_year_snapshot",
            "sequence_no",
            "notes",
            "next_service_recommendation",
            "line_items",
            "payments",
        ]

    def _safe_decrypt(self, getter) -> str | None:
        try:
            return getter()
        except Exception:
            return None

    def get_customer_name(self, obj) -> str | None:
        if obj.is_pii_erased:
            return "[ERASED]"
        return self._safe_decrypt(obj.get_customer_name)

    def get_customer_phone(self, obj) -> str | None:
        if obj.is_pii_erased:
            return "[ERASED]"
        return self._safe_decrypt(obj.get_customer_phone)

    def get_customer_email(self, obj) -> str | None:
        if obj.is_pii_erased:
            return "[ERASED]"
        return self._safe_decrypt(obj.get_customer_email)

    def get_customer_address(self, obj) -> str | None:
        if obj.is_pii_erased:
            return "[ERASED]"
        return self._safe_decrypt(obj.get_customer_address)


class GenerateInvoiceSerializer(serializers.Serializer):
    """Input for POST /job-cards/{id}/generate-invoice/ — no body required, but accepts optional notes."""

    notes = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class CancelInvoiceSerializer(serializers.Serializer):
    """Input for PATCH /invoices/{id}/cancel/ — no body required, but accepts an optional reason."""

    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class RecordPaymentSerializer(serializers.Serializer):
    """Input for PATCH /invoices/{id}/record-payment/."""

    payment_mode = serializers.ChoiceField(choices=Invoice.PAYMENT_MODE_CHOICES)
    amount_paid = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    payment_reference = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def validate_amount_paid(self, value) -> Decimal:
        if value < 0:
            raise serializers.ValidationError("Amount paid cannot be negative.")
        return value
