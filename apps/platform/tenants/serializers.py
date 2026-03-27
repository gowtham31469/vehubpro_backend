import logging

from rest_framework import serializers

from apps.platform.tenants.models import Tenant, TenantBranding, TenantPII
from core.storage import (
    StorageError,
    StorageValidationError,
    delete_stored_media,
    resolve_media_url,
    upload_branding_asset,
)

logger = logging.getLogger(__name__)


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "domain",
            "status",
            "onboarded_at",
            "is_archived",
            "archived_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "onboarded_at", "archived_at", "created_at", "updated_at"]
        # Avoid UniqueValidator on domain so validate_domain can distinguish archived rows.
        extra_kwargs = {"domain": {"validators": []}}

    def validate_domain(self, value):
        if not value:
            return value
        domain = value.strip()
        qs = Tenant.objects.filter(domain=domain)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        existing = qs.first()
        if not existing:
            return domain
        if existing.is_archived:
            raise serializers.ValidationError(
                "A tenant with this domain already exists but is archived. "
                "Unarchive that tenant (set is_archived=false) or choose a different domain."
            )
        raise serializers.ValidationError("A tenant with this domain already exists.")


class TenantBrandingSerializer(serializers.ModelSerializer):
    """Use multipart form for file fields (logo_file, dark_logo_file, favicon_file)."""

    logo_file = serializers.FileField(write_only=True, required=False, allow_null=True)
    dark_logo_file = serializers.FileField(write_only=True, required=False, allow_null=True)
    favicon_file = serializers.FileField(write_only=True, required=False, allow_null=True)

    logo_url = serializers.SerializerMethodField(read_only=True)
    dark_logo_url = serializers.SerializerMethodField(read_only=True)
    favicon_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TenantBranding
        fields = [
            "id",
            "tenant",
            "logo",
            "dark_logo",
            "favicon",
            "logo_url",
            "dark_logo_url",
            "favicon_url",
            "logo_file",
            "dark_logo_file",
            "favicon_file",
            "primary_color",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "logo",
            "dark_logo",
            "favicon",
        ]

    def _resolve_url(self, stored: str | None) -> str | None:
        if not stored:
            return None
        try:
            return resolve_media_url(stored)
        except StorageError as exc:
            logger.warning("Could not build media URL: %s", exc)
            return None

    def get_logo_url(self, obj):
        return self._resolve_url(obj.logo)

    def get_dark_logo_url(self, obj):
        return self._resolve_url(obj.dark_logo)

    def get_favicon_url(self, obj):
        return self._resolve_url(obj.favicon)

    def _upload_branding_file(self, instance, attr: str, uploaded, asset_kind: str) -> None:
        if uploaded is None:
            return
        old_ref = getattr(instance, attr)
        try:
            ref = upload_branding_asset(
                uploaded,
                tenant_id=str(instance.tenant_id),
                asset_kind=asset_kind,
            )
        except StorageValidationError as exc:
            raise serializers.ValidationError({f"{attr}_file": str(exc)}) from exc
        except StorageError as exc:
            logger.exception("Branding asset upload failed for tenant %s", instance.tenant_id)
            raise serializers.ValidationError({f"{attr}_file": str(exc)}) from exc
        setattr(instance, attr, ref)
        delete_stored_media(old_ref)

    def create(self, validated_data):
        logo_file = validated_data.pop("logo_file", None)
        dark_logo_file = validated_data.pop("dark_logo_file", None)
        favicon_file = validated_data.pop("favicon_file", None)

        instance = TenantBranding.objects.create(**validated_data)

        update_fields: list[str] = []
        if logo_file is not None:
            self._upload_branding_file(instance, "logo", logo_file, "logo")
            update_fields.append("logo")
        if dark_logo_file is not None:
            self._upload_branding_file(instance, "dark_logo", dark_logo_file, "dark_logo")
            update_fields.append("dark_logo")
        if favicon_file is not None:
            self._upload_branding_file(instance, "favicon", favicon_file, "favicon")
            update_fields.append("favicon")
        if update_fields:
            update_fields.append("updated_at")
            instance.save(update_fields=update_fields)

        return instance

    def update(self, instance, validated_data):
        logo_file = validated_data.pop("logo_file", None)
        dark_logo_file = validated_data.pop("dark_logo_file", None)
        favicon_file = validated_data.pop("favicon_file", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        update_fields: list[str] = []
        if logo_file is not None:
            self._upload_branding_file(instance, "logo", logo_file, "logo")
            update_fields.append("logo")
        if dark_logo_file is not None:
            self._upload_branding_file(instance, "dark_logo", dark_logo_file, "dark_logo")
            update_fields.append("dark_logo")
        if favicon_file is not None:
            self._upload_branding_file(instance, "favicon", favicon_file, "favicon")
            update_fields.append("favicon")
        if update_fields:
            update_fields.append("updated_at")
            instance.save(update_fields=update_fields)

        return instance


class TenantPIISerializer(serializers.ModelSerializer):
    gstin = serializers.CharField(write_only=True, required=False, allow_blank=True)
    contact_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    email = serializers.EmailField(write_only=True, required=False, allow_blank=True)
    phone = serializers.CharField(write_only=True, required=False, allow_blank=True)

    gstin_value = serializers.SerializerMethodField(read_only=True)
    contact_name_value = serializers.SerializerMethodField(read_only=True)
    email_value = serializers.SerializerMethodField(read_only=True)
    phone_value = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TenantPII
        fields = [
            "id",
            "tenant",
            "address",
            "gstin",
            "contact_name",
            "email",
            "phone",
            "gstin_value",
            "contact_name_value",
            "email_value",
            "phone_value",
            "gstin_hash",
            "is_anonymized",
            "anonymized_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "gstin_hash",
            "anonymized_at",
            "created_at",
            "updated_at",
            "gstin_value",
            "contact_name_value",
            "email_value",
            "phone_value",
        ]

    def _safe_get(self, getter):
        try:
            return getter()
        except Exception:
            return None

    def get_gstin_value(self, obj):
        return self._safe_get(obj.get_gstin)

    def get_contact_name_value(self, obj):
        return self._safe_get(obj.get_contact_name)

    def get_email_value(self, obj):
        return self._safe_get(obj.get_email)

    def get_phone_value(self, obj):
        return self._safe_get(obj.get_phone)

    def create(self, validated_data):
        gstin = validated_data.pop("gstin", None)
        contact_name = validated_data.pop("contact_name", None)
        email = validated_data.pop("email", None)
        phone = validated_data.pop("phone", None)

        instance = TenantPII.objects.create(**validated_data)
        if gstin is not None:
            instance.set_gstin(gstin)
        if contact_name is not None:
            instance.set_contact_name(contact_name)
        if email is not None:
            instance.set_email(email)
        if phone is not None:
            instance.set_phone(phone)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        gstin = validated_data.pop("gstin", None)
        contact_name = validated_data.pop("contact_name", None)
        email = validated_data.pop("email", None)
        phone = validated_data.pop("phone", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if gstin is not None:
            instance.set_gstin(gstin)
        if contact_name is not None:
            instance.set_contact_name(contact_name)
        if email is not None:
            instance.set_email(email)
        if phone is not None:
            instance.set_phone(phone)
        instance.save()
        return instance
