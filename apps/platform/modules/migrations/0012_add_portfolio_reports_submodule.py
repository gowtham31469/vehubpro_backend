from django.db import migrations

# Adds the Reports submodule under the Portfolio module, plus its
# SubmodulePermission links — covers the new Vehicle Sales Report
# (apps.platform.dealer_sales reports/sales/* endpoints). Mirrors
# 0004_add_quotations_reports_submodules.py's "service_reports" entry
# (view + download only, matching a read-only report surface) and
# 0007/0009's pattern of adding a submodule under an already-enabled module.
# Access is NOT granted to any user here — see 0013's ADMIN-only backfill.
PORTFOLIO_MODULE_ID = "d0000000-0000-0000-0000-000000000004"

NEW_SUBMODULES = [
    # (submodule_id, key, name, [(submodule_permission_id, permission_key), ...])
    ("e0000000-0000-0000-0000-000000000017", "portfolio_reports", "Reports", [
        ("f0000000-0000-0000-0000-000000000069", "view"),
        ("f0000000-0000-0000-0000-000000000070", "download"),
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
        ("modules", "0011_promote_customer_management_to_top_level"),
    ]

    operations = [
        migrations.RunPython(add_submodules, noop_reverse),
    ]
