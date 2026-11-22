from django.db import migrations

# Hard-deletes the "Purchases" module (retired in 0026, never granted to any
# tenant, zero app code behind it, fully superseded by the real "Vendor"
# module). Verified zero dependents before writing this migration: no
# TenantModule grants, no UserSubmodulePermission rows, no ModuleDependency
# rows reference it — safe to delete outright rather than leave it inactive.
PURCHASES_MODULE_ID = "d0000000-0000-0000-0000-000000000007"

NEW_SUBMODULES = [
    ("e0000000-0000-0000-0000-000000000019", "purchases_insights", "Insights", 10, [
        ("f0000000-0000-0000-0000-000000000075", "view"),
    ]),
    ("e0000000-0000-0000-0000-000000000020", "vendor_management", "Vendor Management", 20, [
        ("f0000000-0000-0000-0000-000000000076", "create"),
        ("f0000000-0000-0000-0000-000000000077", "update"),
        ("f0000000-0000-0000-0000-000000000078", "delete"),
        ("f0000000-0000-0000-0000-000000000079", "view"),
    ]),
    ("e0000000-0000-0000-0000-000000000021", "purchase_invoice", "Purchase Invoice", 30, [
        ("f0000000-0000-0000-0000-000000000080", "create"),
        ("f0000000-0000-0000-0000-000000000081", "view"),
        ("f0000000-0000-0000-0000-000000000082", "download"),
        ("f0000000-0000-0000-0000-000000000083", "record_payment"),
    ]),
]


def delete_purchases_module(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    # CASCADE on Submodule.module and SubmodulePermission.submodule takes
    # care of the 3 submodules + 9 submodule_permissions in one delete.
    Module.objects.filter(id=PURCHASES_MODULE_ID).delete()


def recreate_purchases_module(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")
    Permission = apps.get_model("modules", "Permission")
    SubmodulePermission = apps.get_model("modules", "SubmodulePermission")

    module, _ = Module.objects.get_or_create(
        id=PURCHASES_MODULE_ID,
        defaults={
            "key": "purchases", "name": "Purchases", "description": "Purchases",
            "is_active": False, "is_service": False, "display_order": 70,
        },
    )
    for submodule_id, key, name, display_order, links in NEW_SUBMODULES:
        submodule, _ = Submodule.objects.get_or_create(
            module_id=module.id, key=key,
            defaults={
                "id": submodule_id, "name": name, "description": name,
                "is_active": False, "display_order": display_order,
            },
        )
        for link_id, permission_key in links:
            permission = Permission.objects.filter(key=permission_key).first()
            if not permission:
                continue
            if SubmodulePermission.objects.filter(submodule=submodule, permission=permission).exists():
                continue
            SubmodulePermission.objects.create(id=link_id, submodule=submodule, permission=permission)


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0031_reorder_vendor_insights_first"),
    ]

    operations = [
        migrations.RunPython(delete_purchases_module, recreate_purchases_module),
    ]
