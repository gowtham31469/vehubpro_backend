from django.db import migrations

# New top-level "Purchases" module with three submodules: Insights (view-only
# dashboard, mirrors services_insights/portfolio_insights), Vendor Management
# (master-data CRUD, mirrors customer_management/services_master), and
# Purchase Invoice (mirrors the "invoices" permission set: create/view/
# download/record_payment — no update/delete, same as sales invoices).
# Access is NOT granted to any tenant/user here — a module is invisible until
# a super admin explicitly assigns it via TenantModule, same as every other
# module. See 0021's ADMIN-only backfill for what happens once it is assigned.
PURCHASES_MODULE_ID = "d0000000-0000-0000-0000-000000000007"

NEW_SUBMODULES = [
    # (submodule_id, key, name, display_order, [(submodule_permission_id, permission_key), ...])
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


def add_purchases_module(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")
    Permission = apps.get_model("modules", "Permission")
    SubmodulePermission = apps.get_model("modules", "SubmodulePermission")

    module, _ = Module.objects.get_or_create(
        id=PURCHASES_MODULE_ID,
        defaults={
            "key": "purchases",
            "name": "Purchases",
            "description": "Purchases",
            "is_active": True,
            "is_service": False,
            "display_order": 70,
        },
    )

    for submodule_id, key, name, display_order, links in NEW_SUBMODULES:
        submodule, _ = Submodule.objects.get_or_create(
            module_id=module.id,
            key=key,
            defaults={
                "id": submodule_id, "name": name, "description": name,
                "is_active": True, "display_order": display_order,
            },
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
        ("modules", "0019_backfill_module_display_order"),
    ]

    operations = [
        migrations.RunPython(add_purchases_module, noop_reverse),
    ]
