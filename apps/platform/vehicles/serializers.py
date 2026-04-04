from datetime import date
from typing import Any

from django.db import IntegrityError
from rest_framework import serializers

from apps.platform.customers.models import Customer
from apps.platform.vehicles.models import FuelType, ServiceVehicle, VehicleBrand, VehicleModel, VehicleType
from core.storage import delete_stored_media, resolve_media_url, upload_image_file
from core.storage.exceptions import StorageValidationError


def _vehicle_brand_integrity_errors(exc: IntegrityError) -> dict[str, Any]:
    msg = str(exc.__cause__ or exc)
    if "uniq_vehicle_brand_name_per_tenant" in msg or "uniq_vehicle_brand_name_per_tenant_active" in msg:
        return {"name": "A brand with this name already exists for your tenant."}
    return {"non_field_errors": ["This brand conflicts with an existing record for your tenant."]}


def _vehicle_model_integrity_errors(exc: IntegrityError) -> dict[str, Any]:
    msg = str(exc.__cause__ or exc)
    if "uniq_vehicle_model_name_per_brand" in msg or "uniq_vehicle_model_name_per_brand_active" in msg:
        return {"name": "A model with this name already exists for this brand."}
    return {"non_field_errors": ["This model conflicts with an existing record for your tenant."]}


class VehicleTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleType
        fields = ["id", "code", "name", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_code(self, value):
        code = (value or "").strip().lower()
        if not code:
            raise serializers.ValidationError("Vehicle type code is required.")
        return code

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Vehicle type name is required.")
        return name


class FuelTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = FuelType
        fields = ["id", "code", "name", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_code(self, value):
        code = (value or "").strip().lower()
        if not code:
            raise serializers.ValidationError("Fuel type code is required.")
        return code

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Fuel type name is required.")
        return name


class VehicleBrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleBrand
        fields = [
            "id",
            "tenant",
            "name",
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
            raise serializers.ValidationError("Vehicle brand name is required.")
        return name

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except IntegrityError as e:
            raise serializers.ValidationError(_vehicle_brand_integrity_errors(e)) from None

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except IntegrityError as e:
            raise serializers.ValidationError(_vehicle_brand_integrity_errors(e)) from None


class VehicleModelSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    vehicle_type_name = serializers.CharField(source="vehicle_type.name", read_only=True, default=None)

    class Meta:
        model = VehicleModel
        fields = [
            "id",
            "tenant",
            "brand",
            "brand_name",
            "vehicle_type",
            "vehicle_type_name",
            "name",
            "is_active",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "tenant", "is_archived", "archived_at", "created_at", "updated_at",
            "brand_name", "vehicle_type_name",
        ]

    def validate_name(self, value):
        name = (value or "").strip()
        if not name:
            raise serializers.ValidationError("Vehicle model name is required.")
        return name

    def validate(self, attrs):
        request = self.context.get("request")
        tenant_id = getattr(getattr(request, "user", None), "tenant_id", None)
        brand = attrs.get("brand", getattr(self.instance, "brand", None))
        if brand and tenant_id and str(brand.tenant_id) != str(tenant_id):
            raise serializers.ValidationError({"brand": "Selected brand does not belong to your tenant."})
        if brand and getattr(brand, "is_archived", False):
            raise serializers.ValidationError({"brand": "Selected brand is archived."})
        return attrs

    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except IntegrityError as e:
            raise serializers.ValidationError(_vehicle_model_integrity_errors(e)) from None

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except IntegrityError as e:
            raise serializers.ValidationError(_vehicle_model_integrity_errors(e)) from None


class ServiceVehicleSerializer(serializers.ModelSerializer):
    vehicle_type_name = serializers.CharField(source="vehicle_type.name", read_only=True)
    fuel_type_name = serializers.CharField(source="fuel_type.name", read_only=True)
    customer_name = serializers.CharField(source="customer.full_name", read_only=True)
    brand_name = serializers.CharField(source="brand.name", read_only=True)
    vehicle_model_name = serializers.CharField(source="vehicle_model.name", read_only=True)

    # Write-only: accepts multipart file upload
    photo_file = serializers.ImageField(write_only=True, required=False, allow_null=True)
    # Read-only: always returns a usable URL (LOCAL or S3 pre-signed)
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = ServiceVehicle
        fields = [
            "id",
            "tenant",
            "customer",
            "customer_name",
            "registration_no",
            "vehicle_type",
            "vehicle_type_name",
            "brand",
            "brand_name",
            "vehicle_model",
            "vehicle_model_name",
            "year",
            "fuel_type",
            "fuel_type_name",
            "engine_cc",
            "battery_capacity_kwh",
            "vin_number",
            "color",
            "insurance_expiry",
            "puc_expiry",
            "permit_expiry",
            "fitness_cert_expiry",
            "no_of_wheels",
            "load_capacity_kg",
            "photo_file",
            "photo_url",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "tenant",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
            "vehicle_type_name",
            "fuel_type_name",
            "customer_name",
            "brand_name",
            "vehicle_model_name",
            "photo_url",
        ]

    def get_photo_url(self, obj) -> str | None:
        return resolve_media_url(obj.photo)

    def _handle_photo_upload(self, photo_file, record_id) -> str | None:
        try:
            return upload_image_file(
                photo_file,
                folder="service_vehicles",
                record_id=str(record_id),
            )
        except StorageValidationError as exc:
            raise serializers.ValidationError({"photo_file": str(exc)}) from exc

    def validate_registration_no(self, value):
        registration_no = (value or "").strip().upper()
        if not registration_no:
            raise serializers.ValidationError("Registration number is required.")
        request = self.context.get("request")
        tenant_id = getattr(getattr(request, "user", None), "tenant_id", None)
        if tenant_id:
            qs = ServiceVehicle.objects.filter(tenant_id=tenant_id, registration_no=registration_no)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(
                    "A vehicle with this registration number already exists for your tenant."
                )
        return registration_no

    def validate_vehicle_type(self, value):
        if value is not None and not value.is_active:
            raise serializers.ValidationError("Selected vehicle type is inactive.")
        return value

    def validate_fuel_type(self, value):
        if value is not None and not value.is_active:
            raise serializers.ValidationError("Selected fuel type is inactive.")
        return value

    def validate_brand(self, value):
        if value is not None and not value.is_active:
            raise serializers.ValidationError("Selected brand is inactive.")
        if value is not None and getattr(value, "is_archived", False):
            raise serializers.ValidationError("Selected brand is archived.")
        return value

    def validate_vehicle_model(self, value):
        if value is not None and not value.is_active:
            raise serializers.ValidationError("Selected vehicle model is inactive.")
        if value is not None and getattr(value, "is_archived", False):
            raise serializers.ValidationError("Selected vehicle model is archived.")
        return value

    def validate_engine_cc(self, value):
        if value is None:
            return value
        if value < 1:
            raise serializers.ValidationError("Engine displacement (cc) must be at least 1.")
        if value > 50000:
            raise serializers.ValidationError("Engine displacement (cc) is too large.")
        return value

    def validate_battery_capacity_kwh(self, value):
        if value is None:
            return value
        if value < 0:
            raise serializers.ValidationError("Battery capacity cannot be negative.")
        return value

    def validate_year(self, value):
        current_year = date.today().year
        if value < 1980 or value > current_year:
            raise serializers.ValidationError(f"Year must be between 1980 and {current_year}.")
        return value

    def validate_vin_number(self, value):
        vin = (value or "").strip().upper()
        if vin and len(vin) != 17:
            raise serializers.ValidationError("VIN number must be exactly 17 characters.")
        return vin or None

    def validate(self, attrs):
        request = self.context.get("request")
        tenant_id = getattr(getattr(request, "user", None), "tenant_id", None)
        if not tenant_id:
            raise serializers.ValidationError(
                {"non_field_errors": ["Tenant context is required (tenant_id from token)."]}
            )

        customer = attrs.get("customer", getattr(self.instance, "customer", None))

        if customer and tenant_id and str(customer.tenant_id) != str(tenant_id):
            raise serializers.ValidationError({"customer": "Selected customer does not belong to your tenant."})

        no_of_wheels = attrs.get("no_of_wheels", getattr(self.instance, "no_of_wheels", None))
        if no_of_wheels is not None and no_of_wheels < 2:
            raise serializers.ValidationError({"no_of_wheels": "Number of wheels must be 2 or greater."})

        load_capacity_kg = attrs.get("load_capacity_kg", getattr(self.instance, "load_capacity_kg", None))
        if load_capacity_kg is not None and load_capacity_kg < 0:
            raise serializers.ValidationError({"load_capacity_kg": "Load capacity cannot be negative."})

        if customer and not Customer.objects.filter(pk=customer.pk, is_archived=False).exists():
            raise serializers.ValidationError({"customer": "Selected customer is archived."})

        brand = attrs.get("brand", getattr(self.instance, "brand", None))
        vehicle_model = attrs.get("vehicle_model", getattr(self.instance, "vehicle_model", None))
        if brand and tenant_id and str(brand.tenant_id) != str(tenant_id):
            raise serializers.ValidationError({"brand": "Selected brand does not belong to your tenant."})
        if vehicle_model and tenant_id and str(vehicle_model.tenant_id) != str(tenant_id):
            raise serializers.ValidationError(
                {"vehicle_model": "Selected vehicle model does not belong to your tenant."}
            )
        if brand and vehicle_model and vehicle_model.brand_id != brand.id:
            raise serializers.ValidationError(
                {"vehicle_model": "Selected model does not belong to the selected brand."}
            )

        return attrs

    def create(self, validated_data):
        photo_file = validated_data.pop("photo_file", None)
        try:
            instance = super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError(
                {"registration_no": "A vehicle with this registration number already exists for your tenant."}
            ) from None
        if photo_file:
            instance.photo = self._handle_photo_upload(photo_file, instance.id)
            instance.save(update_fields=["photo", "updated_at"])
        return instance

    def update(self, instance, validated_data):
        photo_file = validated_data.pop("photo_file", None)
        try:
            instance = super().update(instance, validated_data)
        except IntegrityError:
            raise serializers.ValidationError(
                {"registration_no": "A vehicle with this registration number already exists for your tenant."}
            ) from None
        if photo_file:
            old_photo = instance.photo
            instance.photo = self._handle_photo_upload(photo_file, instance.id)
            instance.save(update_fields=["photo", "updated_at"])
            if old_photo:
                delete_stored_media(old_photo)
        return instance
