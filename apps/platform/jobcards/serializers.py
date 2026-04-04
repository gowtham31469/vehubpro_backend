from __future__ import annotations

import uuid
from collections.abc import Mapping
from decimal import Decimal

from rest_framework import serializers

from apps.platform.jobcards.models import JobCard, JobCardLineItem
from apps.platform.jobcards.utils import (
    allocate_next_jobcard_number,
    refresh_job_card_totals,
    sync_job_card_line_items,
)
from apps.platform.services.models import ServiceItem


def _is_uuid_str(value) -> bool:
    if value in (None, ""):
        return False
    try:
        uuid.UUID(str(value).strip())
        return True
    except (ValueError, TypeError, AttributeError):
        return False


def normalize_job_card_line_items_payload(raw):
    """
    - Nested line objects: drop non-UUID `service_item` strings (catalog labels) to null.
    - Legacy / mistaken clients: `line_items` as a list of plain strings becomes one row per
      string (description or `service_item` UUID if the string parses as UUID).
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        return raw
    out = []
    for idx, item in enumerate(raw):
        if isinstance(item, dict):
            row = {**item}
            si = row.get("service_item")
            if not _is_uuid_str(si) and si not in (None, ""):
                row["service_item"] = None
            elif isinstance(si, str):
                row["service_item"] = si.strip() or None
            out.append(row)
        elif isinstance(item, str):
            s = item.strip()
            if _is_uuid_str(s):
                out.append(
                    {
                        "sort_order": idx,
                        "service_item": s,
                        "description": "",
                        "detail_text": "",
                        "quantity": "1",
                        "unit_price": "0",
                        "discount_amount": "0",
                    }
                )
            else:
                out.append(
                    {
                        "sort_order": idx,
                        "service_item": None,
                        "description": s or "—",
                        "detail_text": "",
                        "quantity": "1",
                        "unit_price": "0",
                        "discount_amount": "0",
                    }
                )
        else:
            out.append(item)
    return out


class ServiceItemPrimaryKeyField(serializers.PrimaryKeyRelatedField):
    """
    `service_item` must be a catalog UUID or empty. Clients sometimes send display
    labels (e.g. "Brake — pad change"); coerce those to null before PK validation
    so the line is treated as custom instead of raising 400.
    """

    def to_internal_value(self, data):
        if data in (None, ""):
            if self.allow_null:
                return None
            self.fail("required")
        if not _is_uuid_str(data):
            if self.allow_null:
                return None
            self.fail("invalid", value=data)
        return super().to_internal_value(data)


class JobCardLineItemSerializer(serializers.ModelSerializer):
    service_item = ServiceItemPrimaryKeyField(
        queryset=ServiceItem.objects.all(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = JobCardLineItem
        fields = [
            "id",
            "sort_order",
            "service_item",
            "description",
            "detail_text",
            "quantity",
            "unit_price",
            "discount_amount",
            "line_total",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "line_total", "created_at", "updated_at"]


class JobCardSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    customer_email = serializers.CharField(source="customer.email", read_only=True, allow_blank=True)
    vehicle_registration = serializers.CharField(source="vehicle.registration_no", read_only=True)
    vehicle_vin = serializers.CharField(source="vehicle.vin_number", read_only=True, allow_null=True)
    vehicle_year = serializers.IntegerField(source="vehicle.year", read_only=True, allow_null=True)
    vehicle_label = serializers.SerializerMethodField()
    technician_name = serializers.SerializerMethodField()
    line_items = JobCardLineItemSerializer(many=True, required=False, allow_empty=True)

    class Meta:
        model = JobCard
        fields = [
            "id",
            "tenant",
            "jobcard_number",
            "customer",
            "customer_name",
            "customer_phone",
            "customer_email",
            "vehicle",
            "vehicle_registration",
            "vehicle_vin",
            "vehicle_year",
            "vehicle_label",
            "line_items",
            "subtotal",
            "discount_amount",
            "shop_fees",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "total_amount",
            "status",
            "assigned_technician",
            "technician_name",
            "estimated_delivery",
            "notes",
            "km_reading",
            "next_service_km",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tenant",
            "jobcard_number",
            "subtotal",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "total_amount",
            "created_at",
            "updated_at",
            "customer_name",
            "customer_phone",
            "customer_email",
            "vehicle_registration",
            "vehicle_vin",
            "vehicle_year",
            "vehicle_label",
            "technician_name",
        ]

    def get_vehicle_label(self, obj: JobCard) -> str:
        v = obj.vehicle
        if not v:
            return ""
        try:
            return f"{v.brand.name} {v.vehicle_model.name}"
        except Exception:
            return obj.vehicle_registration or ""

    def get_technician_name(self, obj: JobCard) -> str | None:
        u = obj.assigned_technician
        if not u:
            return None
        pii = getattr(u, "pii", None)
        if pii:
            try:
                return pii.get_full_name() or str(u.id)
            except Exception:
                return str(u.id)
        return str(u.id)

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
            # After nested validation `sid` is a ServiceItem instance; never pass the model
            # into filter(pk=...) on a UUID PK — Django coerces it via str() and UUID validation fails.
            pk = sid.pk if hasattr(sid, "pk") else sid
            if not ServiceItem.objects.filter(pk=pk, tenant_id=tenant_id).exists():
                raise serializers.ValidationError(
                    f"Invalid catalog service at line {i + 1} for this tenant."
                )
        return value

    def validate(self, attrs):
        tenant_id = self.context.get("tenant_id")
        instance = self.instance

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

        tech = attrs.get("assigned_technician", serializers.empty)
        if tech is serializers.empty:
            tech = instance.assigned_technician if instance else None
        if tech is not None:
            tid = getattr(tech, "tenant_id", None)
            if tenant_id and tid is not None and str(tid) != str(tenant_id):
                raise serializers.ValidationError({"assigned_technician": "Technician must belong to your tenant."})

        return attrs

    def validate_shop_fees(self, value):
        v = Decimal(str(value or 0))
        if v < 0:
            raise serializers.ValidationError("Shop fees cannot be negative.")
        return v

    def create(self, validated_data):
        tenant_id = self.context["tenant_id"]
        items = validated_data.pop("line_items", [])
        validated_data["tenant_id"] = tenant_id
        validated_data["jobcard_number"] = allocate_next_jobcard_number(tenant_id)
        jc = JobCard.objects.create(**validated_data)
        sync_job_card_line_items(jc, items, tenant_id)
        refresh_job_card_totals(jc)
        jc.refresh_from_db()
        return jc

    def update(self, instance, validated_data):
        tenant_id = self.context["tenant_id"]
        _unset = object()
        items = validated_data.pop("line_items", _unset)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()
        if items is not _unset:
            sync_job_card_line_items(instance, items, tenant_id)
        refresh_job_card_totals(instance)
        instance.refresh_from_db()
        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self.context.get("compact"):
            data.pop("line_items", None)
        return data
