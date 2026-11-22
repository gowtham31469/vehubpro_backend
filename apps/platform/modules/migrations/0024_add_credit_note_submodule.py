from django.db import migrations

# New "Credit Note" submodule under the existing "services" module — sits
# right after Invoices (70) and before Reports (80), since a credit note is
# issued against an already-generated invoice to adjust/reverse billed
# amounts. Permission set mirrors "invoices" minus record_payment (a credit
# note is never paid against — it's an adjustment document, not a
# receivable): create/view/download only.
# Access is NOT granted to any tenant here — same convention as every other
# submodule addition. See 0025's ADMIN-only backfill.
SERVICES_MODULE_ID = "d0000000-0000-0000-0000-000000000003"

NEW_SUBMODULES = [
    ("e0000000-0000-0000-0000-000000000023", "credit_note", "Credit Note", 75, [
        ("f0000000-0000-0000-0000-000000000088", "create"),
        ("f0000000-0000-0000-0000-000000000089", "view"),
        ("f0000000-0000-0000-0000-000000000090", "download"),
    ]),
]


def add_credit_note_submodule(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")
    Permission = apps.get_model("modules", "Permission")
    SubmodulePermission = apps.get_model("modules", "SubmodulePermission")

    if not Module.objects.filter(id=SERVICES_MODULE_ID).exists():
        return

    for submodule_id, key, name, display_order, links in NEW_SUBMODULES:
        submodule, _ = Submodule.objects.get_or_create(
            module_id=SERVICES_MODULE_ID,
            key=key,
            defaults={
                "id": submodule_id, "name": name, "description": name,
                "is_active": True, "display_order": display_order,
            },
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
        ("modules", "0023_backfill_leads_permissions"),
    ]

    operations = [
        migrations.RunPython(add_credit_note_submodule, noop_reverse),
    ]
