from django.db import models
from django.core.exceptions import ValidationError
from django.conf import settings
from apps.common.utils.models import BaseModel, SoftArchiveModel
from apps.platform.tenants.models import Tenant


class Permission(BaseModel):
    """
    Global permission registry.
    """
    key = models.CharField(max_length=100, unique=True, help_text="e.g., view, create, update, delete, approve")
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "permissions"

    def __str__(self):
        return self.name


class Module(BaseModel, SoftArchiveModel):
    """
    Application Module registry.
    Compliance: ISO 27001 (Access Control), GDPR (Auditability).
    """
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_service = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_modules",
    )

    class Meta:
        db_table = "modules"

    def __str__(self):
        return f"{self.name} ({self.key})"


class ModuleDependency(BaseModel):
    """
    Self-referential dependencies between modules.
    Non-personal system metadata (DPDP/GDPR safe).
    """
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="dependencies")
    depends_on = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="dependents")

    class Meta:
        db_table = "module_dependencies"
        verbose_name = "Module Dependency"
        verbose_name_plural = "Module Dependencies"
        unique_together = ("module", "depends_on")
        indexes = [
            models.Index(fields=["module"]),
            models.Index(fields=["depends_on"]),
        ]

    def clean(self):
        if self.module_id == self.depends_on_id:
            raise ValidationError("A module cannot depend on itself.")

    def __str__(self):
        return f"{self.module} depends on {self.depends_on}"


class Submodule(BaseModel, SoftArchiveModel):
    """
    Granular features within a module.
    """
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="submodules")
    key = models.CharField(max_length=100)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_submodules",
    )

    class Meta:
        db_table = "submodules"
        unique_together = ("module", "key")

    def __str__(self):
        return f"{self.module.name} - {self.name}"


class SubmodulePermission(BaseModel):
    """
    Links submodules to specific permissions.
    """
    submodule = models.ForeignKey(Submodule, on_delete=models.CASCADE, related_name="permissions")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="submodules")

    class Meta:
        db_table = "submodule_permissions"
        unique_together = ("submodule", "permission")

    def __str__(self):
        return f"{self.submodule} — {self.permission}"


class TenantModule(BaseModel):
    """
    Assigns modules to specific tenants with priority.
    """
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="tenant_modules")
    module = models.ForeignKey(Module, on_delete=models.CASCADE, related_name="tenant_assignments")
    priority = models.IntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_tenant_modules",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_tenant_modules",
    )

    class Meta:
        db_table = "tenant_modules"
        unique_together = ("tenant", "module")
        ordering = ["priority", "created_at"]

    def __str__(self):
        return f"{self.tenant} — {self.module}"


class UserSubmodulePermission(BaseModel):
    """
    Assigns specific submodule permissions to users within a tenant.
    Compliance: DPDP, GDPR (Data Minimization, Access Control), ISO 27001 (Access Control, Auditability).
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submodule_permissions")
    submodule_permission = models.ForeignKey(SubmodulePermission, on_delete=models.CASCADE, related_name="user_assignments")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="user_module_permissions")
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="granted_permissions",
    )

    class Meta:
        db_table = "user_submodule_permissions"
        unique_together = ("user", "submodule_permission", "tenant")

    def __str__(self):
        return f"{self.user} — {self.submodule_permission}"
