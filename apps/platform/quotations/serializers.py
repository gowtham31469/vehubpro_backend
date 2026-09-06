from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from rest_framework import serializers

from apps.platform.jobcards.serializers import (
    ServiceItemPrimaryKeyField,
    normalize_job_card_line_items_payload,
)
from apps.platform.quotations.models import Quotation, QuotationLineItem
from apps.platform.quotations.utils import (
    allocate_next_quotation_number,
    refresh_quotation_totals,
    sync_quotation_line_items,
)
from apps.platform.services.models import ServiceItem


class QuotationLineItemSerializer(serializers.ModelSerializer):
    service_item = ServiceItemPrimaryKeyField(
        queryset=ServiceItem.objects.all(),
        allow_null=True,
        required=False,
    )
    service_type = serializers.ChoiceField(choices=QuotationLineItem.SERVICE_TYPE_CHOICES, required=False)

    class Meta:
        model = QuotationLineItem
        fields = [
            "id",
            "sort_order",
            "service_item",
            "service_type",
            "description",
            "detail_text",
            "quantity",
            "unit_price",
            "discount_amount",
            "line_total",
            "gst_percentage",
            "cgst_amount",
            "sgst_amount",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "line_total",
            "gst_percentage",
            "cgst_amount",
            "sgst_amount",
            "created_at",
            "updated_at",
        ]


class QuotationSerializer(serializers.ModelSerializer):
    """
    Create/update serializer for DRAFT quotations — mirrors JobCardSerializer's
    nested-create pattern exactly. Creating a fresh quotation (no parent) here
    always makes version 1 of a new family; revisions are created exclusively
    through QuotationService.create_revision, never through this serializer's
    create(), since a revision must copy items from its parent rather than
    accept a blank line_items list.
    """

    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    vehicle_registration = serializers.CharField(source="vehicle.registration_no", read_only=True)
    vehicle_label = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    job_card_id = serializers.SerializerMethodField()
    job_card_number = serializers.SerializerMethodField()
    line_items = QuotationLineItemSerializer(many=True, required=False, allow_empty=True)

    class Meta:
        model = Quotation
        fields = [
            "id",
            "tenant",
            "quotation_number",
            "version",
            "parent_quotation",
            "is_latest",
            "revision_reason",
            "customer",
            "customer_name",
            "customer_phone",
            "vehicle",
            "vehicle_registration",
            "vehicle_label",
            "line_items",
            "quotation_date",
            "valid_until",
            "status",
            "subtotal",
            "discount_amount",
            "taxable_amount",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "round_off_amount",
            "total_amount",
            "notes",
            "terms_and_conditions",
            "sent_at",
            "approved_at",
            "rejected_at",
            "rejection_reason",
            "cancelled_at",
            "cancellation_reason",
            "converted_at",
            "created_by",
            "created_by_name",
            "job_card_id",
            "job_card_number",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tenant",
            "quotation_number",
            "version",
            "parent_quotation",
            "is_latest",
            "revision_reason",
            "customer_name",
            "customer_phone",
            "vehicle_registration",
            "vehicle_label",
            "subtotal",
            "taxable_amount",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "round_off_amount",
            "total_amount",
            "status",
            "sent_at",
            "approved_at",
            "rejected_at",
            "rejection_reason",
            "cancelled_at",
            "cancellation_reason",
            "converted_at",
            "created_by",
            "created_by_name",
            "job_card_id",
            "job_card_number",
            "created_at",
            "updated_at",
        ]

    def get_vehicle_label(self, obj: Quotation) -> str:
        v = obj.vehicle
        if not v:
            return ""
        try:
            return f"{v.brand.name} {v.vehicle_model.name}"
        except Exception:
            return obj.vehicle.registration_no or ""

    def get_created_by_name(self, obj: Quotation) -> str | None:
        u = obj.created_by
        if not u:
            return None
        pii = getattr(u, "pii", None)
        if pii:
            try:
                return pii.get_full_name() or str(u.id)
            except Exception:
                return str(u.id)
        return str(u.id)

    def get_job_card_id(self, obj: Quotation) -> str | None:
        jc = obj.job_cards.first()
        return str(jc.id) if jc else None

    def get_job_card_number(self, obj: Quotation) -> str | None:
        jc = obj.job_cards.first()
        return jc.jobcard_number if jc else None

    def to_internal_value(self, data):
        if isinstance(data, Mapping):
            data = dict(data)
            if "line_items" in data:
                data["line_items"] = normalize_job_card_line_items_payload(data["line_items"])
        return super().to_internal_value(data)

    def validate_line_items(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("line_items must be a list.")
        tenant_id = self.context.get("tenant_id")
        for i, row in enumerate(value):
            if not isinstance(row, dict):
                raise serializers.ValidationError(f"Line {i} must be an object.")
            sid = row.get("service_item")
            if sid is None or not tenant_id:
                continue
            pk = sid.pk if hasattr(sid, "pk") else sid
            if not ServiceItem.objects.filter(pk=pk, tenant_id=tenant_id).exists():
                raise serializers.ValidationError(
                    f"Invalid catalog service at line {i + 1} for this tenant."
                )
        return value

    def validate(self, attrs):
        tenant_id = self.context.get("tenant_id")
        instance = self.instance

        if instance is not None and instance.status != Quotation.STATUS_DRAFT:
            raise serializers.ValidationError(
                "Only a draft quotation can be edited directly. Create a revision instead."
            )

        customer = attrs.get("customer", instance.customer if instance else None)
        vehicle = attrs.get("vehicle", instance.vehicle if instance else None)

        if not customer or not vehicle:
            return attrs

        if tenant_id and str(customer.tenant_id) != str(tenant_id):
            raise serializers.ValidationError({"customer": "Customer does not belong to your tenant."})

        if tenant_id and str(vehicle.tenant_id) != str(tenant_id):
            raise serializers.ValidationError({"vehicle": "Vehicle does not belong to your tenant."})

        if str(vehicle.customer_id) != str(customer.id):
            raise serializers.ValidationError({"vehicle": "Selected vehicle must belong to the selected customer."})

        valid_until = attrs.get("valid_until", instance.valid_until if instance else None)
        quotation_date = attrs.get("quotation_date", instance.quotation_date if instance else None)
        if valid_until and quotation_date and valid_until < quotation_date:
            raise serializers.ValidationError({"valid_until": "Valid until date cannot be before the quotation date."})

        return attrs

    def validate_discount_amount(self, value):
        v = Decimal(str(value or 0))
        if v < 0:
            raise serializers.ValidationError("Discount cannot be negative.")
        return v

    def create(self, validated_data):
        tenant_id = self.context["tenant_id"]
        items = validated_data.pop("line_items", [])
        validated_data["tenant_id"] = tenant_id
        validated_data["quotation_number"] = allocate_next_quotation_number(tenant_id)
        validated_data.setdefault("created_by", self.context["request"].user)
        quotation = Quotation.objects.create(**validated_data)
        sync_quotation_line_items(quotation, items, tenant_id)
        refresh_quotation_totals(quotation)
        quotation.refresh_from_db()
        return quotation

    def update(self, instance, validated_data):
        tenant_id = self.context["tenant_id"]
        _unset = object()
        items = validated_data.pop("line_items", _unset)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        if items is not _unset:
            sync_quotation_line_items(instance, items, tenant_id)
        refresh_quotation_totals(instance)
        instance.refresh_from_db()
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self.context.get("compact"):
            data.pop("line_items", None)
        return data


class RevisionActionSerializer(serializers.Serializer):
    """Input for POST /quotations/{id}/revise/."""

    revision_reason = serializers.CharField(required=True, allow_blank=False, max_length=1000)


class RejectQuotationSerializer(serializers.Serializer):
    """Input for PATCH /quotations/{id}/reject/."""

    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class CancelQuotationSerializer(serializers.Serializer):
    """Input for PATCH /quotations/{id}/cancel/."""

    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)
