from django.db import migrations

# Fills a pre-existing gap in the seed fixtures: portfolio_insights,
# inventory_vehicles, and user_management_staff had zero SubmodulePermission
# rows, so no one could ever be granted access to them under strict per-user
# permission filtering — they'd vanish from the nav for everyone, including
# full-access admins. Mirrors the CRUD/view-only pattern already used for
# analogous submodules (service_vehicles, customer_management, etc.).
NEW_LINKS = [
    ("e0000000-0000-0000-0000-000000000007", ["view"]),                              # portfolio_insights
    ("e0000000-0000-0000-0000-000000000008", ["create", "update", "delete", "view"]),  # inventory_vehicles
    ("e0000000-0000-0000-0000-000000000010", ["create", "update", "delete", "view"]),  # user_management_staff
]


def backfill(apps, schema_editor):
    Submodule = apps.get_model("modules", "Submodule")
    Permission = apps.get_model("modules", "Permission")
    SubmodulePermission = apps.get_model("modules", "SubmodulePermission")

    for submodule_id, permission_keys in NEW_LINKS:
        if not Submodule.objects.filter(id=submodule_id).exists():
            continue
        for key in permission_keys:
            permission = Permission.objects.filter(key=key).first()
            if not permission:
                continue
            SubmodulePermission.objects.get_or_create(
                submodule_id=submodule_id, permission=permission,
            )

    # Existing users' permission rows were backfilled by 0002 before these
    # submodule/permission links existed — re-run it so they pick these up too.
    from apps.platform.modules.services import grant_all_tenant_module_permissions
    from apps.platform.users.models import User

    for user in User.objects.filter(tenant_id__isnull=False, is_archived=False):
        grant_all_tenant_module_permissions(user)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0002_backfill_user_submodule_permissions"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
