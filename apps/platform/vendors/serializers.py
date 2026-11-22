"""Vendor serializers."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.platform.vendors.models import Vendor, VendorBill, VendorCategory, VendorPayment
from apps.platform.vendors.service import vendor_outstanding_balance


def vendor_category_integrity_errors(exc) -> dict[str, Any]:
    msg = str(exc.__cause__ or exc)
    if "uniq_vendor_category_name_per_tenant" in msg:
        return {"name": "A vendor category with this name already exists for your tenant."}
    return {"non_field_errors": ["This vendor category conflicts with an existing record for your tenant."]}


class VendorCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorCategory
        fields = [
            "id", "tenant", "name", "sort_order", "is_active",
            "is_archived", "archived_at", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "tenant", "is_archived", "archived_at", "created_at", "updated_at"]

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Vendor category name is required.")
        return name


class VendorListSerializer(serializers.ModelSerializer):
    outstanding_balance = serializers.SerializerMethodField()
    active_bill_count = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = [
            "id", "name", "category", "contact_person", "phone", "email",
            "gstin", "pan", "payment_terms_days", "is_archived",
            "outstanding_balance", "active_bill_count", "created_at",
        ]
        read_only_fields = fields

    def get_outstanding_balance(self, obj) -> str:
        return str(vendor_outstanding_balance(obj))

    def get_active_bill_count(self, obj) -> int:
        return obj.bills.filter(status=VendorBill.STATUS_ISSUED).count()


class VendorDetailSerializer(VendorListSerializer):
    class Meta(VendorListSerializer.Meta):
        fields = VendorListSerializer.Meta.fields + [
            "address", "bank_account_name", "bank_account_number", "bank_ifsc",
            "bank_name", "notes", "updated_at",
        ]
        read_only_fields = fields


class VendorWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = [
            "name", "category", "contact_person", "phone", "email", "address",
            "gstin", "pan", "bank_account_name", "bank_account_number",
            "bank_ifsc", "bank_name", "payment_terms_days", "notes",
        ]

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name is required.")
        return value


class VendorPaymentSerializer(serializers.ModelSerializer):
    recorded_by_name = serializers.SerializerMethodField()
    voided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = VendorPayment
        fields = [
            "id", "vendor", "vendor_bill", "payment_number", "amount",
            "payment_date", "payment_mode", "payment_reference", "notes",
            "recorded_by_name", "is_voided", "voided_at", "void_reason",
            "voided_by_name", "created_at",
        ]
        read_only_fields = fields

    def get_recorded_by_name(self, obj) -> str | None:
        if not obj.recorded_by_id:
            return None
        try:
            return obj.recorded_by.pii.get_full_name()
        except Exception:
            return None

    def get_voided_by_name(self, obj) -> str | None:
        if not obj.voided_by_id:
            return None
        try:
            return obj.voided_by.pii.get_full_name()
        except Exception:
            return None


class VendorBillListSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    attachment_url = serializers.SerializerMethodField()
    balance_due = serializers.SerializerMethodField()

    class Meta:
        model = VendorBill
        fields = [
            "id", "vendor", "vendor_name", "bill_number", "vendor_bill_reference",
            "bill_date", "due_date", "description", "subtotal", "gst_percentage",
            "is_interstate", "cgst_amount", "sgst_amount", "igst_amount",
            "total_amount", "tds_percentage", "tds_amount", "net_payable_amount",
            "payment_status", "amount_paid", "balance_due", "status",
            "attachment_url", "created_at",
        ]
        read_only_fields = fields

    def get_attachment_url(self, obj) -> str | None:
        if not obj.attachment:
            return None
        from core.storage import resolve_media_url
        return resolve_media_url(obj.attachment)

    def get_balance_due(self, obj) -> str:
        return str(Decimal(str(obj.net_payable_amount)) - Decimal(str(obj.amount_paid)))


class VendorBillDetailSerializer(VendorBillListSerializer):
    payments = serializers.SerializerMethodField()
    cancelled_by_name = serializers.SerializerMethodField()

    class Meta(VendorBillListSerializer.Meta):
        fields = VendorBillListSerializer.Meta.fields + [
            "round_off_amount", "cancelled_at", "cancellation_reason",
            "cancelled_by_name", "payments", "updated_at",
        ]
        read_only_fields = fields

    def get_payments(self, obj):
        qs = obj.payments.order_by("-created_at")
        return VendorPaymentSerializer(qs, many=True).data

    def get_cancelled_by_name(self, obj) -> str | None:
        if not obj.cancelled_by_id:
            return None
        try:
            return obj.cancelled_by.pii.get_full_name()
        except Exception:
            return str(obj.cancelled_by_id)


class GenerateVendorBillSerializer(serializers.Serializer):
    vendor_id = serializers.UUIDField()
    bill_date = serializers.DateField()
    due_date = serializers.DateField(required=False, allow_null=True)
    vendor_bill_reference = serializers.CharField(required=False, allow_blank=True, max_length=100)
    description = serializers.CharField(required=False, allow_blank=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    gst_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, min_value=Decimal("0"))
    is_interstate = serializers.BooleanField(required=False, default=False)
    tds_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, min_value=Decimal("0"))
    attachment = serializers.FileField(required=False, allow_null=True)


class CancelVendorBillSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class RecordVendorPaymentSerializer(serializers.Serializer):
    vendor_id = serializers.UUIDField()
    vendor_bill_id = serializers.UUIDField(required=False, allow_null=True)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    payment_date = serializers.DateField()
    payment_mode = serializers.ChoiceField(choices=VendorPayment.PAYMENT_MODE_CHOICES)
    payment_reference = serializers.CharField(required=False, allow_blank=True, max_length=255)
    notes = serializers.CharField(required=False, allow_blank=True)


class VoidVendorPaymentSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)
