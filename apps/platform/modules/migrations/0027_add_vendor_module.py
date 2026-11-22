from django.db import migrations

# New top-level "Vendor" module — accounts payable: Vendor List (master-data
# CRUD, mirrors vendor_management/customer_management), Vendor Bills (mirrors
# the invoices/purchase_invoice permission set minus download — there's no
# PDF generated for a vendor bill, it just records a document the vendor
# already issued), Vendor Payments (create/view/delete — recording and
# voiding a payment; no update, payments are immutable except for voiding).
# Access is NOT granted to any tenant/user here — see 0028's backfill.
VENDOR_MODULE_ID = "d0000000-0000-0000-0000-000000000008"

NEW_SUBMODULES = [
    # (submodule_id, key, name, display_order, [(submodule_permission_id, permission_key), ...])
    ("e0000000-0000-0000-0000-000000000024", "vendor_list", "Vendor List", 10, [
        ("f0000000-0000-0000-0000-000000000091", "create"),
        ("f0000000-0000-0000-0000-000000000092", "update"),
        ("f0000000-0000-0000-0000-000000000093", "delete"),
        ("f0000000-0000-0000-0000-000000000094", "view"),
    ]),
    ("e0000000-0000-0000-0000-000000000025", "vendor_bills", "Vendor Bills", 20, [
        ("f0000000-0000-0000-0000-000000000095", "create"),
        ("f0000000-0000-0000-0000-000000000096", "view"),
        ("f0000000-0000-0000-0000-000000000097", "update"),
        ("f0000000-0000-0000-0000-000000000098", "delete"),
    ]),
    ("e0000000-0000-0000-0000-000000000026", "vendor_payments", "Vendor Payments", 30, [
        ("f0000000-0000-0000-0000-000000000099", "create"),
        ("f0000000-0000-0000-0000-000000000100", "view"),
        ("f0000000-0000-0000-0000-000000000101", "delete"),
    ]),
]


def add_vendor_module(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")
    Permission = apps.get_model("modules", "Permission")
    SubmodulePermission = apps.get_model("modules", "SubmodulePermission")

    module, _ = Module.objects.get_or_create(
        id=VENDOR_MODULE_ID,
        defaults={
            "key": "vendor",
            "name": "Vendor",
            "description": "Vendor",
            "is_active": True,
            "is_service": False,
            "display_order": 80,
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
        ("modules", "0026_retire_purchases_module"),
    ]

    operations = [
        migrations.RunPython(add_vendor_module, noop_reverse),
    ]
