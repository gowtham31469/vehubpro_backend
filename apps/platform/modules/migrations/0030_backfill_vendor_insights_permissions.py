from django.db import migrations

# grant_all_tenant_module_permissions() recomputes "every submodule permission
# under modules this tenant has" each time it's called — it's not a one-shot
# snapshot — so re-running it for the same tenant/users as 0028 picks up the
# newly added vendor_insights "view" permission automatically.
CHEZIYAN_CARS_TENANT_ID = "1c57fdc9-42d0-4c7c-810e-3902fe23976e"


def backfill(apps, schema_editor):
    from apps.platform.modules.services import grant_all_tenant_module_permissions
    from apps.platform.tenants.models import Tenant
    from apps.platform.users.models import User

    if not Tenant.objects.filter(id=CHEZIYAN_CARS_TENANT_ID).exists():
        return

    for user in User.objects.filter(
        tenant_id=CHEZIYAN_CARS_TENANT_ID, is_archived=False, role__code="ADMIN"
    ):
        grant_all_tenant_module_permissions(user)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0029_add_vendor_insights_submodule"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
