from datetime import date
from typing import Any

from django.db import IntegrityError
from rest_framework import serializers

from apps.platform.portfolio.models import InventoryFeature, InventoryVehicle
from apps.platform.vehicles.models import VehicleBrand
from core.storage import delete_stored_media, resolve_media_url, upload_image_file, upload_thumbnail_only
from core.storage.exceptions import StorageValidationError


def _inventory_feature_integrity_errors(exc: IntegrityError) -> dict[str, Any]:
    msg = str(exc.__cause__ or exc)
    if "uniq_inventory_feature_name_per_tenant_active" in msg:
        return {"name": "A feature with this name already exists for your tenant."}
    return {"non_field_errors": ["This feature conflicts with an existing record for your tenant."]}


class InventoryFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryFeature
        fields = ["id", "tenant", "name", "category", "is_active", "is_archived", "archived_at", "created_at", "updated_at"]
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
    # Read-only: URL for the one small preview copy of photos[0] — use this
    # for grids/listings instead of photo_urls[0].
    cover_thumbnail_url = serializers.SerializerMethodField()

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
            "color",
            "mileage_km",
            "key_features",
            "key_features_detail",
            "listing_price",
            "original_price",
            "offer_valid_until",
            "reasons_to_buy",
            "insurance_policy_no",
            "registration_no",
            "tax_expiration_date",
            "photos",
            "photo_files",
            "remove_photos",
            "photo_urls",
            "cover_thumbnail_url",
            "status",
            "is_featured",
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
            "cover_thumbnail_url",
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

    def get_cover_thumbnail_url(self, obj):
        if obj.cover_thumbnail:
            return resolve_media_url(obj.cover_thumbnail)
        if obj.photos:
            return resolve_media_url(obj.photos[0])
        return None

    def get_key_features_detail(self, obj):
        return [{"id": str(f.id), "name": f.name} for f in obj.key_features.all()]

    def validate_reasons_to_buy(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Reasons to buy must be a list.")
        if len(value) > 6:
            raise serializers.ValidationError("You can add at most 6 reasons to buy.")
        cleaned = []
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("Each reason must have a title and description.")
            title = str(item.get("title") or "").strip()
            description = str(item.get("description") or "").strip()
            if not title:
                continue
            cleaned.append({"title": title[:100], "description": description[:200]})
        return cleaned

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

        original_price = attrs.get("original_price", getattr(self.instance, "original_price", None))
        listing_price = attrs.get("listing_price", getattr(self.instance, "listing_price", None))
        if original_price is not None and listing_price is not None and original_price <= listing_price:
            raise serializers.ValidationError(
                {"original_price": "Original price must be greater than the listing price for a discount to apply."}
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

    def _replace_cover_thumbnail(self, instance, new_first_file) -> None:
        """
        Regenerate the single cover thumbnail from the raw bytes of the photo
        that is now first — always a just-uploaded file, since we thumbnail
        it in-memory rather than re-downloading an already-stored photo.
        """
        if instance.cover_thumbnail:
            delete_stored_media(instance.cover_thumbnail)
        thumb_key = upload_thumbnail_only(new_first_file, folder="inventory_vehicles", record_id=str(instance.id))
        instance.cover_thumbnail = thumb_key or ""

    def create(self, validated_data):
        photo_files = validated_data.pop("photo_files", None) or []
        validated_data.pop("remove_photos", None)

        instance = super().create(validated_data)

        if photo_files:
            instance.photos = self._upload_photos(photo_files, instance.id)
            if instance.photos:
                self._replace_cover_thumbnail(instance, photo_files[0])
            instance.save(update_fields=["photos", "cover_thumbnail", "updated_at"])
        return instance

    def update(self, instance, validated_data):
        photo_files = validated_data.pop("photo_files", None) or []
        remove_photos = validated_data.pop("remove_photos", None) or []

        old_first = instance.photos[0] if instance.photos else None

        instance = super().update(instance, validated_data)

        if remove_photos or photo_files:
            photos = list(instance.photos or [])
            if remove_photos:
                keep = [k for k in photos if k not in remove_photos]
                for k in photos:
                    if k in remove_photos:
                        delete_stored_media(k)
                photos = keep

            new_uploaded_keys = []
            if photo_files:
                new_uploaded_keys = self._upload_photos(photo_files, instance.id)
                photos.extend(new_uploaded_keys)
            instance.photos = photos

            new_first = photos[0] if photos else None
            if new_first != old_first:
                if new_first and new_first in new_uploaded_keys:
                    # We have the raw bytes for this one in-memory — thumbnail
                    # it directly instead of reading the stored file back.
                    self._replace_cover_thumbnail(instance, photo_files[new_uploaded_keys.index(new_first)])
                else:
                    # The new first photo is an existing one we no longer
                    # have raw bytes for (e.g. the old first was removed and
                    # an older photo shifted up) — clear the thumbnail rather
                    # than pay to re-download and re-process a stored file;
                    # get_cover_thumbnail_url falls back to the full photo
                    # until the tenant next uploads.
                    if instance.cover_thumbnail:
                        delete_stored_media(instance.cover_thumbnail)
                    instance.cover_thumbnail = ""

            instance.save(update_fields=["photos", "cover_thumbnail", "updated_at"])

        return instance


class PublicInventoryVehicleSerializer(serializers.ModelSerializer):
    """
    Read-only, no-auth serializer for the public showroom page.

    Deliberately excludes registration_no, insurance_policy_no, tax_expiration_date,
    and status — statutory/internal details with no reason to be public.
    """

    brand_name = serializers.CharField(source="brand.name", read_only=True)
    brand_logo_url = serializers.SerializerMethodField()
    vehicle_model_name = serializers.CharField(source="vehicle_model.name", read_only=True)
    vehicle_type_name = serializers.CharField(source="vehicle_type.name", read_only=True)
    fuel_type_name = serializers.CharField(source="fuel_type.name", read_only=True)
    photo_urls = serializers.SerializerMethodField()
    cover_thumbnail_url = serializers.SerializerMethodField()
    key_features_detail = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    offer_valid_until = serializers.SerializerMethodField()

    class Meta:
        model = InventoryVehicle
        fields = [
            "id",
            "brand_name",
            "brand_logo_url",
            "vehicle_model_name",
            "vehicle_type_name",
            "year",
            "fuel_type_name",
            "transmission",
            "color",
            "mileage_km",
            "key_features_detail",
            "listing_price",
            "original_price",
            "offer_valid_until",
            "reasons_to_buy",
            "photo_urls",
            "cover_thumbnail_url",
            "is_featured",
            "created_at",
        ]

    def get_brand_logo_url(self, obj):
        return resolve_media_url(obj.brand.logo) if obj.brand_id else None

    def get_photo_urls(self, obj):
        return [resolve_media_url(k) for k in (obj.photos or [])]

    def get_cover_thumbnail_url(self, obj):
        if obj.cover_thumbnail:
            return resolve_media_url(obj.cover_thumbnail)
        if obj.photos:
            return resolve_media_url(obj.photos[0])
        return None

    def get_key_features_detail(self, obj):
        return [{"name": f.name, "category": f.category} for f in obj.key_features.all()]

    def _offer_is_live(self, obj):
        return (
            obj.original_price is not None
            and obj.offer_valid_until is not None
            and obj.offer_valid_until >= date.today()
        )

    def get_original_price(self, obj):
        return obj.original_price if self._offer_is_live(obj) else None

    def get_offer_valid_until(self, obj):
        return obj.offer_valid_until if self._offer_is_live(obj) else None


class PublicVehicleBrandSerializer(serializers.ModelSerializer):
    """Read-only, no-auth serializer listing every brand a tenant has created."""

    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = VehicleBrand
        fields = ["id", "name", "logo_url"]

    def get_logo_url(self, obj):
        return resolve_media_url(obj.logo)
