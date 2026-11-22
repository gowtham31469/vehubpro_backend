from django.db import migrations

# Unlike every other submodule-addition backfill (0008/0010/0013/0021/0023/
# 0025), the "Vendor" module is brand new, so no tenant has a TenantModule
# row for it yet — grant_all_tenant_module_permissions() is a no-op without
# one. The user explicitly asked for aravind@gmail.com (ADMIN, tenant
# "Cheziyan Cars") to get this module, so this migration grants the
# TenantModule to that one tenant specifically (not blanket-granted to
# everyone) and then runs the usual ADMIN-of-that-tenant permission backfill.
CHEZIYAN_CARS_TENANT_ID = "1c57fdc9-42d0-4c7c-810e-3902fe23976e"
VENDOR_MODULE_ID = "d0000000-0000-0000-0000-000000000008"


def backfill(apps, schema_editor):
    # Mirrors 0021/0023/0025's imports (real model classes, not historical
    # apps.get_model) — consistent with how grant_all_tenant_module_permissions
    # itself is used in every prior backfill of this shape.
    from apps.platform.modules.models import TenantModule
    from apps.platform.modules.services import grant_all_tenant_module_permissions
    from apps.platform.tenants.models import Tenant
    from apps.platform.users.models import User

    if not Tenant.objects.filter(id=CHEZIYAN_CARS_TENANT_ID).exists():
        return

    TenantModule.objects.get_or_create(tenant_id=CHEZIYAN_CARS_TENANT_ID, module_id=VENDOR_MODULE_ID)

    for user in User.objects.filter(
        tenant_id=CHEZIYAN_CARS_TENANT_ID, is_archived=False, role__code="ADMIN"
    ):
        grant_all_tenant_module_permissions(user)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0027_add_vendor_module"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
