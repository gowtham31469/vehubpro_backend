from datetime import date
from typing import Any

from django.db import IntegrityError
from rest_framework import serializers

from apps.platform.portfolio.models import InventoryFeature, InventoryVehicle
from core.storage import delete_stored_media, resolve_media_url, upload_image_file
from core.storage.exceptions import StorageValidationError


def _inventory_feature_integrity_errors(exc: IntegrityError) -> dict[str, Any]:
    msg = str(exc.__cause__ or exc)
    if "uniq_inventory_feature_name_per_tenant_active" in msg:
        return {"name": "A feature with this name already exists for your tenant."}
    return {"non_field_errors": ["This feature conflicts with an existing record for your tenant."]}


class InventoryFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryFeature
        fields = ["id", "tenant", "name", "is_active", "is_archived", "archived_at", "created_at", "updated_at"]
        read_only_fields = ["id", "tenant", "is_archived", "archived_at", "created_at", "updated_at"]

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Name is required.")
        return name

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except IntegrityError as e:
            raise serializers.ValidationError(_inventory_feature_integrity_errors(e)) from None

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except IntegrityError as e:
            raise serializers.ValidationError(_inventory_feature_integrity_errors(e)) from None


class InventoryVehicleSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    vehicle_model_name = serializers.CharField(source="vehicle_model.name", read_only=True)
    vehicle_type_name = serializers.CharField(source="vehicle_type.name", read_only=True)
    fuel_type_name = serializers.CharField(source="fuel_type.name", read_only=True)

    # Read-only: {id, name} pairs for the selected key features (for display).
    key_features_detail = serializers.SerializerMethodField()

    # Write-only: new files to upload (appended to existing photos).
    photo_files = serializers.ListField(
        child=serializers.ImageField(), write_only=True, required=False, allow_empty=True
    )
    # Write-only: storage keys of existing photos to remove.
    remove_photos = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False, allow_empty=True
    )
    # Read-only: resolved {key, url} pairs in display order.
    photo_urls = serializers.SerializerMethodField()

    class Meta:
        model = InventoryVehicle
        fields = [
            "id",
            "tenant",
            "vehicle_type",
            "vehicle_type_name",
            "brand",
            "brand_name",
            "vehicle_model",
            "vehicle_model_name",
            "year",
            "fuel_type",
            "fuel_type_name",
            "transmission",
            "mileage_km",
            "key_features",
            "key_features_detail",
            "listing_price",
            "insurance_policy_no",
            "registration_no",
            "tax_expiration_date",
            "photos",
            "photo_files",
            "remove_photos",
            "photo_urls",
            "status",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tenant",
            "photos",
            "photo_urls",
            "brand_name",
            "vehicle_model_name",
            "vehicle_type_name",
            "fuel_type_name",
            "key_features_detail",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]

    def get_photo_urls(self, obj):
        return [{"key": key, "url": resolve_media_url(key)} for key in (obj.photos or [])]

    def get_key_features_detail(self, obj):
        return [{"id": str(f.id), "name": f.name} for f in obj.key_features.all()]

    def validate_year(self, value):
        current_year = date.today().year
        if value < 1980 or value > current_year + 1:
            raise serializers.ValidationError(f"Year must be between 1980 and {current_year + 1}.")
        return value

    def validate_brand(self, value):
        if value is not None and not value.is_active:
            raise serializers.ValidationError("Selected brand is inactive.")
        if value is not None and getattr(value, "is_archived", False):
            raise serializers.ValidationError("Selected brand is archived.")
        return value

    def validate_vehicle_model(self, value):
        if value is not None and not value.is_active:
            raise serializers.ValidationError("Selected model is inactive.")
        if value is not None and getattr(value, "is_archived", False):
            raise serializers.ValidationError("Selected model is archived.")
        return value

    def validate_fuel_type(self, value):
        if value is not None and not value.is_active:
            raise serializers.ValidationError("Selected fuel type is inactive.")
        return value

    def validate_key_features(self, value):
        request = self.context.get("request")
        tenant_id = getattr(getattr(request, "user", None), "tenant_id", None)
        for feature in value:
            if str(feature.tenant_id) != str(tenant_id):
                raise serializers.ValidationError("One or more selected features do not belong to your tenant.")
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        tenant_id = getattr(getattr(request, "user", None), "tenant_id", None)
        if not tenant_id:
            raise serializers.ValidationError(
                {"non_field_errors": ["Tenant context is required (tenant_id from token)."]}
            )

        brand = attrs.get("brand", getattr(self.instance, "brand", None))
        if brand and str(brand.tenant_id) != str(tenant_id):
            raise serializers.ValidationError({"brand": "Selected brand does not belong to your tenant."})

        vehicle_model = attrs.get("vehicle_model", getattr(self.instance, "vehicle_model", None))
        if vehicle_model and str(vehicle_model.tenant_id) != str(tenant_id):
            raise serializers.ValidationError(
                {"vehicle_model": "Selected model does not belong to your tenant."}
            )
        if brand and vehicle_model and vehicle_model.brand_id != brand.id:
            raise serializers.ValidationError(
                {"vehicle_model": "Selected model does not belong to the selected brand."}
            )

        return attrs

    def _upload_photos(self, photo_files, record_id) -> list[str]:
        keys = []
        try:
            for f in photo_files:
                keys.append(upload_image_file(f, folder="inventory_vehicles", record_id=str(record_id)))
        except StorageValidationError as exc:
            raise serializers.ValidationError({"photo_files": str(exc)}) from exc
        return keys

    def create(self, validated_data):
        photo_files = validated_data.pop("photo_files", None) or []
        validated_data.pop("remove_photos", None)

        instance = super().create(validated_data)

        if photo_files:
            instance.photos = self._upload_photos(photo_files, instance.id)
            instance.save(update_fields=["photos", "updated_at"])
        return instance

    def update(self, instance, validated_data):
        photo_files = validated_data.pop("photo_files", None) or []
        remove_photos = validated_data.pop("remove_photos", None) or []

        instance = super().update(instance, validated_data)

        if remove_photos or photo_files:
            photos = list(instance.photos or [])
            if remove_photos:
                keep = [k for k in photos if k not in remove_photos]
                for k in photos:
                    if k in remove_photos:
                        delete_stored_media(k)
                photos = keep
            if photo_files:
                photos.extend(self._upload_photos(photo_files, instance.id))
            instance.photos = photos
            instance.save(update_fields=["photos", "updated_at"])

        return instance


class PublicInventoryVehicleSerializer(serializers.ModelSerializer):
    """
    Read-only, no-auth serializer for the public showroom page.

    Deliberately excludes registration_no, insurance_policy_no, tax_expiration_date,
    and status — statutory/internal details with no reason to be public.
    """

    brand_name = serializers.CharField(source="brand.name", read_only=True)
    vehicle_model_name = serializers.CharField(source="vehicle_model.name", read_only=True)
    vehicle_type_name = serializers.CharField(source="vehicle_type.name", read_only=True)
    fuel_type_name = serializers.CharField(source="fuel_type.name", read_only=True)
    photo_urls = serializers.SerializerMethodField()
    key_features_detail = serializers.SerializerMethodField()

    class Meta:
        model = InventoryVehicle
        fields = [
            "id",
            "brand_name",
            "vehicle_model_name",
            "vehicle_type_name",
            "year",
            "fuel_type_name",
            "transmission",
            "mileage_km",
            "key_features_detail",
            "listing_price",
            "photo_urls",
            "created_at",
        ]

    def get_photo_urls(self, obj):
        return [resolve_media_url(k) for k in (obj.photos or [])]

    def get_key_features_detail(self, obj):
        return [f.name for f in obj.key_features.all()]
