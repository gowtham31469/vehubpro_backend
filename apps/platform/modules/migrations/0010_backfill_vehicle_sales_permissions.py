from django.db import migrations

# Adding the vehicle_sales submodule (0009) didn't retroactively grant it to
# any already-existing ADMIN accounts — permission grants are snapshots taken
# at user-creation time, not a live "ADMIN = everything." Scoped to
# role=ADMIN only, not STAFF/MANAGER (whose permission sets are curated, not
# blanket). Mirrors 0008_backfill_vehicle_work_expenses_permissions.py exactly.


def backfill(apps, schema_editor):
    from apps.platform.modules.services import grant_all_tenant_module_permissions
    from apps.platform.users.models import User

    for user in User.objects.filter(tenant_id__isnull=False, is_archived=False, role__code="ADMIN"):
        grant_all_tenant_module_permissions(user)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0009_add_vehicle_sales_submodule"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
