from django.db import migrations

# Adding the portfolio_reports submodule (0012) didn't retroactively grant it
# to any already-existing ADMIN accounts — permission grants are snapshots
# taken at user-creation time, not a live "ADMIN = everything." Scoped to
# role=ADMIN only, not STAFF/MANAGER (whose permission sets are curated, not
# blanket). Mirrors 0008/0010's backfills exactly.


def backfill(apps, schema_editor):
    from apps.platform.modules.services import grant_all_tenant_module_permissions
    from apps.platform.users.models import User

    for user in User.objects.filter(tenant_id__isnull=False, is_archived=False, role__code="ADMIN"):
        grant_all_tenant_module_permissions(user)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0012_add_portfolio_reports_submodule"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
