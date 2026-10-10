from django.db import migrations

# Customer Management was nested under the "Services" (Garage) module purely
# as a registry-setup convenience from before Portfolio/dealer_sales existed.
# Customers are used identically by both sides (7 FK references on the
# dealer_sales side vs 2-3 on the Garage side — Portfolio actually leans on
# it MORE), and the Customer model itself has no Garage-specific fields, so
# nesting it under either module misrepresents it. Promoting it to its own
# top-level module instead of duplicating the Customer table/list — a split
# customer list would mean a buyer who later becomes a service customer (a
# very real case) ends up as two disconnected records with no merge path.
#
# This moves the EXISTING customer_management Submodule row (same PK) to a
# new top-level Module, so every SubmodulePermission/UserSubmodulePermission
# grant anyone already has for it keeps working untouched — only its parent
# module changes. Every tenant that currently has Services enabled gets the
# new Customers module enabled too, preserving their existing implicit
# access. The frontend (AdminShell.jsx) already has MODULE_META/
# SUBMODULE_ROUTE_MAP entries for both "customers" and "customer_management"
# keys from when this was first built, so no frontend change is needed.
CUSTOMERS_MODULE_ID = "d0000000-0000-0000-0000-000000000006"
SERVICES_MODULE_ID = "d0000000-0000-0000-0000-000000000003"
CUSTOMER_MANAGEMENT_SUBMODULE_ID = "e0000000-0000-0000-0000-000000000002"


def promote(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")
    TenantModule = apps.get_model("modules", "TenantModule")

    if not Module.objects.filter(id=SERVICES_MODULE_ID).exists():
        return

    customers_module, _ = Module.objects.get_or_create(
        id=CUSTOMERS_MODULE_ID,
        defaults={"key": "customers", "name": "Customers", "description": "Customers", "is_active": True},
    )

    Submodule.objects.filter(id=CUSTOMER_MANAGEMENT_SUBMODULE_ID).update(module_id=customers_module.id)

    services_tenant_ids = list(
        TenantModule.objects.filter(module_id=SERVICES_MODULE_ID).values_list("tenant_id", flat=True)
    )
    for tenant_id in services_tenant_ids:
        TenantModule.objects.get_or_create(tenant_id=tenant_id, module_id=customers_module.id)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0010_backfill_vehicle_sales_permissions"),
    ]

    operations = [
        migrations.RunPython(promote, noop_reverse),
    ]
