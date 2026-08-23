from rest_framework import serializers
from django.db import transaction
from apps.common.encryption.pii import encryptor
from apps.platform.users.models import User, UserPII
from apps.platform.masters.models import Role
from apps.platform.modules.models import SubmodulePermission
from apps.platform.modules.services import (
    grant_all_tenant_module_permissions,
    sync_user_submodule_permissions,
)
from core.audit.service import log_audit_event
from core.audit.constants import AuditAction, AuditModule

class TenantAdminSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(write_only=True)
    email = serializers.EmailField(write_only=True)
    phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    permissions = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False
    )
    
    full_name_value = serializers.SerializerMethodField(read_only=True)
    email_value = serializers.SerializerMethodField(read_only=True)
    phone_value = serializers.SerializerMethodField(read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "tenant", "status", "role", "role_name",
            "full_name", "email", "phone", "password", "permissions",
            "full_name_value", "email_value", "phone_value",
            "is_active", "created_at", "updated_at"
        ]
        read_only_fields = ["id", "role_name", "created_at", "updated_at"]

    def get_full_name_value(self, obj):
        return obj.pii.get_full_name() if hasattr(obj, 'pii') else None

    def get_email_value(self, obj):
        return obj.pii.get_email() if hasattr(obj, 'pii') else None

    def get_phone_value(self, obj):
        return obj.pii.get_phone() if hasattr(obj, 'pii') else None

    @transaction.atomic
    def create(self, validated_data):
        full_name = validated_data.pop("full_name")
        email = validated_data.pop("email")
        phone = validated_data.pop("phone", "")
        password = validated_data.pop("password", None)
        # Explicit permission selection is not used on create: every permission
        # for the tenant's assigned modules is granted automatically below.
        validated_data.pop("permissions", None)

        # Ensure role is ADMIN if not provided
        if not validated_data.get("role"):
            role = Role.objects.get(code="ADMIN")
            validated_data["role"] = role

        user = User.objects.create_user(password=password, **validated_data)

        pii = UserPII(user=user)
        pii.set_full_name(full_name)
        pii.set_email(email)
        if phone:
            pii.set_phone(phone)
        pii.save()

        grant_all_tenant_module_permissions(user)

        return user

    @transaction.atomic
    def update(self, instance, validated_data):
        full_name = validated_data.pop("full_name", None)
        email = validated_data.pop("email", None)
        phone = validated_data.pop("phone", None)
        password = validated_data.pop("password", None)
        permission_ids = validated_data.pop("permissions", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        if password:
            instance.set_password(password)
            
        instance.save()

        if hasattr(instance, 'pii'):
            pii = instance.pii
            if full_name: pii.set_full_name(full_name)
            if email: pii.set_email(email)
            if phone is not None: pii.set_phone(phone)
            pii.save()

        if permission_ids is not None:
            sync_user_submodule_permissions(instance, permission_ids)

        return instance


class StaffUserSerializer(serializers.ModelSerializer):
    """
    Tenant-portal CRUD for staff users (User Management module). Unlike
    TenantAdminSerializer (superadmin-only, always grants every permission on
    create), this accepts an explicit, selective ``permissions`` list at both
    create and update time — the whole point of the tenant portal's
    permission-assignment UI is choosing exactly what a staff member can see.
    """

    full_name = serializers.CharField(write_only=True)
    email = serializers.EmailField(write_only=True)
    phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    permissions = serializers.ListField(
        child=serializers.UUIDField(), write_only=True, required=False
    )

    full_name_value = serializers.SerializerMethodField(read_only=True)
    email_value = serializers.SerializerMethodField(read_only=True)
    phone_value = serializers.SerializerMethodField(read_only=True)
    role_name = serializers.CharField(source="role.name", read_only=True)
    permission_ids = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "status", "role", "role_name",
            "full_name", "email", "phone", "password", "permissions", "permission_ids",
            "full_name_value", "email_value", "phone_value",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "role_name", "permission_ids", "created_at", "updated_at"]

    def get_full_name_value(self, obj):
        return obj.pii.get_full_name() if hasattr(obj, "pii") else None

    def get_email_value(self, obj):
        return obj.pii.get_email() if hasattr(obj, "pii") else None

    def get_phone_value(self, obj):
        return obj.pii.get_phone() if hasattr(obj, "pii") else None

    def get_permission_ids(self, obj):
        return list(
            obj.submodule_permissions.filter(is_active=True)
            .values_list("submodule_permission_id", flat=True)
        )

    def validate_email(self, value):
        email_hash = encryptor.hash_value(value)
        qs = UserPII.objects.filter(email_hash=email_hash)
        if self.instance is not None:
            qs = qs.exclude(user_id=self.instance.id)
        if qs.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_role(self, value):
        if value and value.code == "SUPER_ADMIN":
            raise serializers.ValidationError(
                "SUPER_ADMIN role cannot be assigned from the tenant portal."
            )
        return value

    def validate_permissions(self, value):
        if not value:
            return value
        tenant_id = self.context.get("tenant_id")
        valid_ids = set(
            SubmodulePermission.objects.filter(
                id__in=value,
                submodule__module__tenant_assignments__tenant_id=tenant_id,
            ).values_list("id", flat=True)
        )
        if set(value) - valid_ids:
            raise serializers.ValidationError(
                "One or more permissions are not available for this tenant."
            )
        return value

    @transaction.atomic
    def create(self, validated_data):
        full_name = validated_data.pop("full_name")
        email = validated_data.pop("email")
        phone = validated_data.pop("phone", "")
        password = validated_data.pop("password", None)
        permission_ids = validated_data.pop("permissions", None) or []

        user = User.objects.create_user(password=password, **validated_data)

        pii = UserPII(user=user)
        pii.set_full_name(full_name)
        pii.set_email(email)
        if phone:
            pii.set_phone(phone)
        pii.save()

        if permission_ids:
            sync_user_submodule_permissions(user, permission_ids)

        return user

    @transaction.atomic
    def update(self, instance, validated_data):
        full_name = validated_data.pop("full_name", None)
        email = validated_data.pop("email", None)
        phone = validated_data.pop("phone", None)
        password = validated_data.pop("password", None)
        permission_ids = validated_data.pop("permissions", None)
        # tenant is set once at creation and never reassigned via update.
        validated_data.pop("tenant_id", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        if hasattr(instance, "pii"):
            pii = instance.pii
            if full_name:
                pii.set_full_name(full_name)
            if email:
                pii.set_email(email)
            if phone is not None:
                pii.set_phone(phone)
            pii.save()

        if permission_ids is not None:
            sync_user_submodule_permissions(instance, permission_ids)

        return instance
