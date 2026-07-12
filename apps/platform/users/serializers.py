from rest_framework import serializers
from django.db import transaction
from apps.platform.users.models import User, UserPII
from apps.platform.masters.models import Role
from apps.platform.modules.models import UserSubmodulePermission, SubmodulePermission
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
        permission_ids = validated_data.pop("permissions", [])
        
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

        # Assign submodule permissions
        if permission_ids:
            perms_to_create = [
                UserSubmodulePermission(
                    user=user,
                    tenant=user.tenant,
                    submodule_permission_id=pid,
                )
                for pid in permission_ids
            ]
            UserSubmodulePermission.objects.bulk_create(perms_to_create)
        
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
            # Sync permissions: remove existing and add new
            UserSubmodulePermission.objects.filter(user=instance).delete()
            perms_to_create = [
                UserSubmodulePermission(
                    user=instance,
                    tenant=instance.tenant,
                    submodule_permission_id=pid,
                )
                for pid in permission_ids
            ]
            UserSubmodulePermission.objects.bulk_create(perms_to_create)
            
        return instance
