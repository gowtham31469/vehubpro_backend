from django.db import migrations

# Mirrors 0008/0010/0013's backfills exactly. Scoped to role=ADMIN only.
# Note: this is a no-op today, since no tenant has the new Purchases module
# assigned yet (TenantModule rows are created explicitly by a super admin) —
# it only takes effect for ADMIN users of tenants that already had Purchases
# assigned by the time this migration runs.


def backfill(apps, schema_editor):
    from apps.platform.modules.services import grant_all_tenant_module_permissions
    from apps.platform.users.models import User

    for user in User.objects.filter(tenant_id__isnull=False, is_archived=False, role__code="ADMIN"):
        grant_all_tenant_module_permissions(user)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0020_add_purchases_module"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
