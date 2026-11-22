from django.db import migrations

# 4th Vendor submodule — a view-only analytics dashboard, same shape as the
# dormant "purchases_insights" (0020) it supersedes: a single "view"
# permission, no create/update/delete.
VENDOR_MODULE_ID = "d0000000-0000-0000-0000-000000000008"

NEW_SUBMODULES = [
    ("e0000000-0000-0000-0000-000000000027", "vendor_insights", "Insights", 40, [
        ("f0000000-0000-0000-0000-000000000102", "view"),
    ]),
]


def add_vendor_insights_submodule(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")
    Permission = apps.get_model("modules", "Permission")
    SubmodulePermission = apps.get_model("modules", "SubmodulePermission")

    if not Module.objects.filter(id=VENDOR_MODULE_ID).exists():
        return

    for submodule_id, key, name, display_order, links in NEW_SUBMODULES:
        submodule, _ = Submodule.objects.get_or_create(
            module_id=VENDOR_MODULE_ID,
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
        ("modules", "0028_backfill_vendor_permissions"),
    ]

    operations = [
        migrations.RunPython(add_vendor_insights_submodule, noop_reverse),
    ]
