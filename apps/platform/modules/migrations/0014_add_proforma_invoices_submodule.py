from django.db import migrations

# Adds the Proforma Invoices submodule under the Services module, plus its
# SubmodulePermission links — covers the new apps.platform.proforma_invoices
# feature (POST /job-cards/{id}/generate-proforma-invoice/,
# /proforma-invoices/*, /advance-payments/*). Mirrors
# 0004_add_quotations_reports_submodules.py's "quotations" entry exactly —
# quotations lives as a submodule under Services (d0000000-...-000003), not
# its own top-level module, and Proforma Invoices follows the same
# placement since it's the same kind of pre-invoice, job-card-adjacent
# document.
# Access is NOT granted to any user here — see 0015's ADMIN-only backfill.
SERVICES_MODULE_ID = "d0000000-0000-0000-0000-000000000003"

NEW_SUBMODULES = [
    # (submodule_id, key, name, [(submodule_permission_id, permission_key), ...])
    ("e0000000-0000-0000-0000-000000000018", "proforma_invoices", "Proforma Invoices", [
        ("f0000000-0000-0000-0000-000000000071", "view"),
        ("f0000000-0000-0000-0000-000000000072", "create"),
        ("f0000000-0000-0000-0000-000000000073", "update"),
        ("f0000000-0000-0000-0000-000000000074", "download"),
    ]),
]


def add_submodules(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")
    Permission = apps.get_model("modules", "Permission")
    SubmodulePermission = apps.get_model("modules", "SubmodulePermission")

    if not Module.objects.filter(id=SERVICES_MODULE_ID).exists():
        return

    for submodule_id, key, name, links in NEW_SUBMODULES:
        submodule, _ = Submodule.objects.get_or_create(
            module_id=SERVICES_MODULE_ID,
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
        ("modules", "0013_backfill_portfolio_reports_permissions"),
    ]

    operations = [
        migrations.RunPython(add_submodules, noop_reverse),
    ]
