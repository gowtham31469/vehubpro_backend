from django.db import migrations

# Adding the visit_requests submodule (0005) didn't retroactively grant it to
# any already-existing ADMIN accounts — permission grants are snapshots taken
# at user-creation time (TenantAdminSerializer calls
# grant_all_tenant_module_permissions once, at creation), not a live
# "ADMIN = everything." Without this, visit_requests silently vanishes from
# the nav for every admin who existed before 0005 ran.
#
# Deliberately scoped to role=ADMIN only, unlike
# 0003_backfill_missing_submodule_permissions.py's blanket re-run for every
# tenant user: STAFF/MANAGER accounts get an explicit, curated permission set
# via StaffUserSerializer (sync_user_submodule_permissions), and re-running
# grant_all_tenant_module_permissions on them would silently hand out every
# other submodule's permissions too, well beyond what a tenant admin chose to
# give them.


def backfill(apps, schema_editor):
    from apps.platform.modules.services import grant_all_tenant_module_permissions
    from apps.platform.users.models import User

    for user in User.objects.filter(tenant_id__isnull=False, is_archived=False, role__code="ADMIN"):
        grant_all_tenant_module_permissions(user)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0005_add_visit_requests_submodule"),
    ]

    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
