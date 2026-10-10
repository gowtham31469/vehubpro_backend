from django.db import migrations

# Adds the Quotations and Reports submodules under the Services module, plus
# their SubmodulePermission links, for databases seeded before these existed
# in the fixtures. IDs match fixtures/submodules.json and
# fixtures/submodule_permissions.json so loaddata and this migration agree.
# Access is NOT granted to any user here — assign it per user/tenant.
SERVICES_MODULE_ID = "d0000000-0000-0000-0000-000000000003"

NEW_SUBMODULES = [
    # (submodule_id, key, name, [(submodule_permission_id, permission_key), ...])
    ("e0000000-0000-0000-0000-000000000012", "quotations", "Quotations", [
        ("f0000000-0000-0000-0000-000000000049", "create"),
        ("f0000000-0000-0000-0000-000000000050", "update"),
        ("f0000000-0000-0000-0000-000000000051", "delete"),
        ("f0000000-0000-0000-0000-000000000052", "view"),
        ("f0000000-0000-0000-0000-000000000053", "approve"),
        ("f0000000-0000-0000-0000-000000000054", "download"),
    ]),
    ("e0000000-0000-0000-0000-000000000013", "reports", "Reports", [
        ("f0000000-0000-0000-0000-000000000055", "view"),
        ("f0000000-0000-0000-0000-000000000056", "download"),
    ]),
]


def add_submodules(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")
    Permission = apps.get_model("modules", "Permission")
    SubmodulePermission = apps.get_model("modules", "SubmodulePermission")

    if not Module.objects.filter(id=SERVICES_MODULE_ID).exists():
        return

    for submodule_id, key, name, links in NEW_SUBMODULES:
        submodule, _ = Submodule.objects.get_or_create(
            module_id=SERVICES_MODULE_ID,
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
        ("modules", "0003_backfill_missing_submodule_permissions"),
    ]

    operations = [
        migrations.RunPython(add_submodules, noop_reverse),
    ]
