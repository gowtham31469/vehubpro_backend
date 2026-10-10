from django.db import migrations

# Adds the Vehicle Work & Expenses submodule under the Portfolio module, plus
# its SubmodulePermission links — the mandatory independently-grantable
# permission for apps.platform.dealer_sales.VehicleWorkExpense, deliberately
# separate from anything under the Services (Garage) module so a portfolio
# user can be granted this without any Garage access. Mirrors
# 0005_add_visit_requests_submodule.py's pattern exactly.
# Access is NOT granted to any user here — see 0008's ADMIN-only backfill.
PORTFOLIO_MODULE_ID = "d0000000-0000-0000-0000-000000000004"

NEW_SUBMODULES = [
    # (submodule_id, key, name, [(submodule_permission_id, permission_key), ...])
    ("e0000000-0000-0000-0000-000000000015", "vehicle_work_expenses", "Vehicle Work & Expenses", [
        ("f0000000-0000-0000-0000-000000000060", "view"),
        ("f0000000-0000-0000-0000-000000000061", "create"),
        ("f0000000-0000-0000-0000-000000000062", "update"),
        ("f0000000-0000-0000-0000-000000000063", "delete"),
    ]),
]


def add_submodules(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")
    Permission = apps.get_model("modules", "Permission")
    SubmodulePermission = apps.get_model("modules", "SubmodulePermission")

    if not Module.objects.filter(id=PORTFOLIO_MODULE_ID).exists():
        return

    for submodule_id, key, name, links in NEW_SUBMODULES:
        submodule, _ = Submodule.objects.get_or_create(
            module_id=PORTFOLIO_MODULE_ID,
            key=key,
            defaults={"id": submodule_id, "name": name, "description": name, "is_active": True},
        )
        for link_id, permission_key in links:
            permission = Permission.objects.filter(key=permission_key).first()
            if not permission:
                continue
            if SubmodulePermission.objects.filter(submodule=submodule, permission=permission).exists():
                continue
            SubmodulePermission.objects.create(id=link_id, submodule=submodule, permission=permission)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0006_backfill_visit_requests_permissions"),
    ]

    operations = [
        migrations.RunPython(add_submodules, noop_reverse),
    ]
