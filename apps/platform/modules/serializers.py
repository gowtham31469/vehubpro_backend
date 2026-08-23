from rest_framework import serializers
from apps.platform.modules.models import Module, Submodule, Permission, TenantModule, SubmodulePermission


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "key", "name", "description"]


class SubmodulePermissionSerializer(serializers.ModelSerializer):
    permission_id = serializers.UUIDField(source="permission.id", read_only=True)
    permission_key = serializers.CharField(source="permission.key", read_only=True)
    permission_name = serializers.CharField(source="permission.name", read_only=True)

    class Meta:
        model = SubmodulePermission
        fields = ["id", "permission_id", "permission_key", "permission_name"]


class SubmoduleSerializer(serializers.ModelSerializer):
    permissions = SubmodulePermissionSerializer(many=True, read_only=True)

    class Meta:
        model = Submodule
        fields = [
            "id", "module", "key", "name", "description",
            "is_active", "permissions", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ModuleSerializer(serializers.ModelSerializer):
    submodule_count = serializers.SerializerMethodField()

    class Meta:
        model = Module
        fields = [
            "id", "key", "name", "description",
            "is_active", "is_service", "submodule_count",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_submodule_count(self, obj):
        return obj.submodules.filter(is_archived=False).count()


class ModuleDetailSerializer(ModuleSerializer):
    submodules = serializers.SerializerMethodField()

    class Meta(ModuleSerializer.Meta):
        fields = ModuleSerializer.Meta.fields + ["submodules"]

    def get_submodules(self, obj):
        qs = obj.submodules.filter(is_archived=False).order_by("name")
        return SubmoduleSerializer(qs, many=True).data


class TenantModuleSerializer(serializers.ModelSerializer):
    module_name = serializers.CharField(source="module.name", read_only=True)
    module_key  = serializers.CharField(source="module.key",  read_only=True)

    class Meta:
        model = TenantModule
        fields = ["id", "tenant", "module", "module_name", "module_key", "priority", "created_at"]
        read_only_fields = ["id", "created_at"]


class NavSubmoduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Submodule
        fields = ["id", "key", "name"]


class NavModuleSerializer(serializers.ModelSerializer):
    submodules = serializers.SerializerMethodField()

    class Meta:
        model = Module
        fields = ["id", "key", "name", "submodules"]

    def get_submodules(self, obj):
        qs = obj.submodules.filter(is_archived=False, is_active=True)
        allowed_submodule_ids = self.context.get("allowed_submodule_ids")
        if allowed_submodule_ids is not None:
            qs = qs.filter(id__in=allowed_submodule_ids)
        qs = qs.order_by("id")
        return NavSubmoduleSerializer(qs, many=True).data
