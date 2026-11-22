"""Credit Note serializers."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.platform.credit_notes.models import CreditNote, CreditNoteLineItem, CreditNoteReasonCategory


def reason_category_integrity_errors(exc) -> dict[str, Any]:
    msg = str(exc.__cause__ or exc)
    if "uniq_credit_note_reason_category_name_per_tenant" in msg:
        return {"name": "A reason category with this name already exists for your tenant."}
    return {"non_field_errors": ["This reason category conflicts with an existing record for your tenant."]}


class CreditNoteReasonCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditNoteReasonCategory
        fields = [
            "id", "tenant", "name", "sort_order", "is_active",
            "is_archived", "archived_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "tenant", "is_archived", "archived_at", "created_at", "updated_at"]

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Reason category name is required.")
        return name


class CreditNoteLineItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditNoteLineItem
        fields = [
            "id",
            "invoice_line_item",
            "sort_order",
            "service_type",
            "description",
            "detail_text",
            "hsn_sac_code",
            "quantity",
            "unit_price",
            "gst_percentage",
            "price_type",
            "cgst_amount",
            "sgst_amount",
            "line_total",
            "created_at",
        ]
        read_only_fields = fields


class CreditNoteListSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)
    issued_by_name = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = CreditNote
        fields = [
            "id",
            "credit_note_number",
            "fy_code",
            "invoice",
            "invoice_number",
            "status",
            "reason",
            "reason_category",
            "total_amount",
            "is_refund_applicable",
            "refund_status",
            "refund_amount",
            "issued_by_name",
            "pdf_url",
            "created_at",
        ]
        read_only_fields = fields

    def get_issued_by_name(self, obj) -> str | None:
        if not obj.issued_by_id:
            return None
        try:
            return obj.issued_by.pii.get_full_name()
        except Exception:
            return None

    def get_pdf_url(self, obj) -> str | None:
        if not obj.pdf_key:
            return None
        try:
            from core.storage.resolve import resolve_media_url
            return resolve_media_url(obj.pdf_key)
        except Exception:
            return None


class CreditNoteDetailSerializer(CreditNoteListSerializer):
    line_items = CreditNoteLineItemSerializer(many=True, read_only=True)
    cancelled_by_name = serializers.SerializerMethodField()

    class Meta(CreditNoteListSerializer.Meta):
        fields = CreditNoteListSerializer.Meta.fields + [
            "sequence_no",
            "subtotal",
            "discount_amount",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "round_off_amount",
            "refunded_at",
            "refund_reason",
            "cancelled_at",
            "cancelled_by_name",
            "cancellation_reason",
            "line_items",
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


class LineItemCreditSerializer(serializers.Serializer):
    invoice_line_item_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class GenerateCreditNoteSerializer(serializers.Serializer):
    """Input for POST /invoices/{id}/credit-notes/."""

    reason = serializers.CharField(max_length=2000)
    reason_category = serializers.CharField(required=False, allow_blank=True, max_length=100)
    custom_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, min_value=Decimal("0.01"))
    custom_gst_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, min_value=Decimal("0"))
    line_item_credits = LineItemCreditSerializer(many=True, required=False)

    def validate(self, attrs):
        if not attrs.get("line_item_credits") and not attrs.get("custom_amount"):
            raise serializers.ValidationError(
                "Provide at least one line item credit or a custom amount."
            )
        return attrs


class MarkRefundedSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class CancelCreditNoteSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)
