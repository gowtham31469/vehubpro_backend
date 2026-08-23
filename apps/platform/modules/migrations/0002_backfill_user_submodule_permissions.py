from django.db import migrations


def backfill_permissions(apps, schema_editor):
    """
    One-time backfill: grant every existing tenant user full access to their
    tenant's assigned modules, matching the nav's current behavior (tenant-level
    gating only) before the nav switches to strict per-user permission checks.
    Without this, every user with zero UserSubmodulePermission rows today would
    lose their entire sidebar the moment strict filtering ships.
    """
    # Uses the real (non-historical) models rather than apps.get_model — the
    # shared helper does real-model ORM calls, and this is the tip migration
    # for both apps, so there's no schema drift risk in doing so.
    from apps.platform.modules.services import grant_all_tenant_module_permissions
    from apps.platform.users.models import User

    for user in User.objects.filter(tenant_id__isnull=False, is_archived=False):
        grant_all_tenant_module_permissions(user)


def noop_reverse(apps, schema_editor):
    # Intentionally irreversible — undoing this would strip real access grants
    # that may have been relied on (or further customized) after the backfill.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0001_initial"),
        ("users", "0006_user_role"),
    ]

    operations = [
        migrations.RunPython(backfill_permissions, noop_reverse),
    ]
