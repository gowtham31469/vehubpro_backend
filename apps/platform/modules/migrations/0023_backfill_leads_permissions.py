from django.db import migrations

# Mirrors 0008/0010/0013/0021's backfills exactly. Scoped to role=ADMIN only.


def backfill(apps, schema_editor):
    from apps.platform.modules.services import grant_all_tenant_module_permissions
    from apps.platform.users.models import User

    for user in User.objects.filter(tenant_id__isnull=False, is_archived=False, role__code="ADMIN"):
        grant_all_tenant_module_permissions(user)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0022_add_leads_submodule"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
