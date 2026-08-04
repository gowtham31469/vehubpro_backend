import logging

from rest_framework import serializers

from apps.platform.tenants.models import Tenant, TenantBranding, TenantInvoiceSettings, TenantPII
from core.storage import (
    StorageError,
    StorageValidationError,
    delete_stored_media,
    resolve_media_url,
    upload_branding_asset,
)

logger = logging.getLogger(__name__)


def _resolve_branding_url(stored: str | None) -> str | None:
    if not stored:
        return None
    try:
        return resolve_media_url(stored)
    except StorageError as exc:
        logger.warning("Could not build media URL: %s", exc)
        return None


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
    business_name = serializers.CharField(source="tenant.name", read_only=True)

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
            "business_name",
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

    def get_logo_url(self, obj):
        return _resolve_branding_url(obj.logo)

    def get_dark_logo_url(self, obj):
        return _resolve_branding_url(obj.dark_logo)

    def get_favicon_url(self, obj):
        return _resolve_branding_url(obj.favicon)

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


class TenantInvoiceSettingsSerializer(serializers.ModelSerializer):
    """Bank details use write-only plaintext + *_value read fields, mirroring TenantPIISerializer.
    QR code uses a write-only upload field, mirroring TenantBrandingSerializer."""

    account_number = serializers.CharField(write_only=True, required=False, allow_blank=True)
    account_number_value = serializers.SerializerMethodField(read_only=True)

    qr_code_file = serializers.FileField(write_only=True, required=False, allow_null=True)
    qr_code_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = TenantInvoiceSettings
        fields = [
            "id",
            "tenant",
            "account_holder_name",
            "account_number",
            "account_number_value",
            "account_type",
            "ifsc_code",
            "bank_name",
            "branch_name",
            "upi_id",
            "qr_code",
            "qr_code_file",
            "qr_code_url",
            "terms_and_conditions",
            "currency_symbol",
            "advance_payment_percentage",
            "estimate_charge_percentage",
            "replaced_parts_retention_days",
            "service_warranty_days",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "qr_code",
            "account_number_value",
            "qr_code_url",
        ]

    def get_account_number_value(self, obj):
        try:
            return obj.get_account_number()
        except Exception:
            return None

    def get_qr_code_url(self, obj):
        return _resolve_branding_url(obj.qr_code)

    def _upload_qr_code(self, instance, uploaded) -> None:
        if uploaded is None:
            return
        old_ref = instance.qr_code
        try:
            ref = upload_branding_asset(
                uploaded,
                tenant_id=str(instance.tenant_id),
                asset_kind="qr_code",
            )
        except StorageValidationError as exc:
            raise serializers.ValidationError({"qr_code_file": str(exc)}) from exc
        except StorageError as exc:
            logger.exception("QR code upload failed for tenant %s", instance.tenant_id)
            raise serializers.ValidationError({"qr_code_file": str(exc)}) from exc
        instance.qr_code = ref
        delete_stored_media(old_ref)

    def create(self, validated_data):
        account_number = validated_data.pop("account_number", None)
        qr_code_file = validated_data.pop("qr_code_file", None)

        instance = TenantInvoiceSettings.objects.create(**validated_data)
        if account_number is not None:
            instance.set_account_number(account_number)
        if qr_code_file is not None:
            self._upload_qr_code(instance, qr_code_file)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        account_number = validated_data.pop("account_number", None)
        qr_code_file = validated_data.pop("qr_code_file", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if account_number is not None:
            instance.set_account_number(account_number)
        if qr_code_file is not None:
            self._upload_qr_code(instance, qr_code_file)
        instance.save()
        return instance


class PublicTenantBrandingSerializer(serializers.ModelSerializer):
    """Read-only, no-auth serializer exposing only safe branding fields."""

    logo_url = serializers.SerializerMethodField()
    business_name = serializers.CharField(source="tenant.name", read_only=True)

    class Meta:
        model = TenantBranding
        fields = ["logo_url", "primary_color", "business_name"]

    def get_logo_url(self, obj):
        return _resolve_branding_url(obj.logo)
