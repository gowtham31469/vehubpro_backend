from typing import Any

from django.db import IntegrityError
from rest_framework import serializers

from apps.platform.services.models import LabourCategory, ServiceCategory, ServiceItem


def _category_integrity_errors(exc: IntegrityError) -> dict[str, Any]:
    msg = str(exc.__cause__ or exc)
    if "uniq_service_category_name_per_tenant" in msg:
        return {"name": "A service category with this name already exists for your tenant."}
    return {"non_field_errors": ["This category conflicts with an existing record for your tenant."]}


def _labour_category_integrity_errors(exc: IntegrityError) -> dict[str, Any]:
    msg = str(exc.__cause__ or exc)
    if "uniq_labour_category_name_per_tenant" in msg:
        return {"name": "A labour category with this name already exists for your tenant."}
    return {"non_field_errors": ["This labour category conflicts with an existing record for your tenant."]}


def _item_integrity_errors(exc: IntegrityError) -> dict[str, Any]:
    msg = str(exc.__cause__ or exc)
    if "uniq_service_item_name_per_category" in msg:
        return {"name": "A service item with this name already exists in this category."}
    return {"non_field_errors": ["This service item conflicts with an existing record for your tenant."]}


def _resolve_image_url(obj):
    if not obj.image:
        return None
    try:
        from core.storage.resolve import resolve_media_url
        return resolve_media_url(obj.image)
    except Exception:
        return None


class ServiceCategorySerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCategory
        fields = [
            "id",
            "tenant",
            "name",
            "applicable_vehicle_types",
            "icon_code",
            "image",
            "image_url",
            "sort_order",
            "is_active",
            "is_featured",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "tenant", "image", "image_url", "is_archived", "archived_at", "created_at", "updated_at",
        ]

    def get_image_url(self, obj):
        return _resolve_image_url(obj)

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Category name is required.")
        return name


class LabourCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LabourCategory
        fields = [
            "id",
            "tenant",
            "name",
            "sort_order",
            "is_active",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "tenant", "is_archived", "archived_at", "created_at", "updated_at"]

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Labour category name is required.")
        return name


class ServiceItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    labour_category_name = serializers.CharField(source="labour_category.name", read_only=True, default=None)
    image_url = serializers.SerializerMethodField()
    service_type = serializers.ChoiceField(choices=ServiceItem.SERVICE_TYPE_CHOICES)
    price_type = serializers.ChoiceField(choices=ServiceItem.PRICE_TYPE_CHOICES, required=False)
    applicable_vehicle_types = serializers.ListField(
        child=serializers.CharField(), allow_empty=False,
    )

    class Meta:
        model = ServiceItem
        fields = [
            "id",
            "tenant",
            "category",
            "category_name",
            "name",
            "description",
            "service_type",
            "labour_category",
            "labour_category_name",
            "base_price",
            "hsn_code",
            "gst_percentage",
            "price_type",
            "unit_type",
            "applicable_vehicle_types",
            "image",
            "image_url",
            "is_active",
            "is_featured",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tenant",
            "category_name",
            "labour_category_name",
            "image",
            "image_url",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]

    def get_image_url(self, obj):
        if not obj.image:
            return None
        try:
            from core.storage.resolve import resolve_media_url
            return resolve_media_url(obj.image)
        except Exception:
            return None

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Service item name is required.")
        return name

    def validate_base_price(self, value):
        if value is None or value < 0:
            raise serializers.ValidationError("Base price must be zero or greater.")
        return value

    def validate_gst_percentage(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("GST percentage cannot be negative.")
        return value

    def validate(self, attrs):
        service_type = attrs.get("service_type", getattr(self.instance, "service_type", None))
        if "labour_category" in attrs:
            labour_category = attrs["labour_category"]
        else:
            labour_category = getattr(self.instance, "labour_category", None) if self.instance else None
        if labour_category and service_type != ServiceItem.SERVICE_TYPE_LABOUR:
            raise serializers.ValidationError(
                {"labour_category": "Labour category can only be set for labour-type items."}
            )
        return attrs


class PublicServiceCategorySerializer(serializers.ModelSerializer):
    """Read-only, no-auth serializer for the public Services homepage/catalog."""

    image_url = serializers.SerializerMethodField()

    class Meta:
        model = ServiceCategory
        fields = ["id", "name", "icon_code", "image_url", "sort_order", "is_featured"]

    def get_image_url(self, obj):
        return _resolve_image_url(obj)


class PublicServiceItemSerializer(serializers.ModelSerializer):
    """Read-only, no-auth serializer for the public Services homepage."""

    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = ServiceItem
        fields = [
            "id",
            "category",
            "category_name",
            "name",
            "description",
            "base_price",
            "service_type",
            "unit_type",
            "image_url",
            "is_featured",
        ]

    def get_image_url(self, obj):
        if not obj.image:
            return None
        try:
            from core.storage.resolve import resolve_media_url
            return resolve_media_url(obj.image)
        except Exception:
            return None
