from django.db import migrations

# Adds the Visit Requests submodule under the Portfolio module, plus its
# SubmodulePermission links, for databases seeded before it existed in the
# fixtures. IDs match fixtures/submodules.json and
# fixtures/submodule_permissions.json so loaddata and this migration agree.
# Access is NOT granted to any user here — assign it per user/tenant.
# Mirrors 0004_add_quotations_reports_submodules.py's pattern.
PORTFOLIO_MODULE_ID = "d0000000-0000-0000-0000-000000000004"

NEW_SUBMODULES = [
    # (submodule_id, key, name, [(submodule_permission_id, permission_key), ...])
    ("e0000000-0000-0000-0000-000000000014", "visit_requests", "Visit Requests", [
        ("f0000000-0000-0000-0000-000000000057", "view"),
        ("f0000000-0000-0000-0000-000000000058", "update"),
        ("f0000000-0000-0000-0000-000000000059", "delete"),
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
        ("modules", "0004_add_quotations_reports_submodules"),
    ]

    operations = [
        migrations.RunPython(add_submodules, noop_reverse),
    ]
