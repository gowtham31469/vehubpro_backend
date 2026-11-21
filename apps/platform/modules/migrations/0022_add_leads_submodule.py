from django.db import migrations

# New "Leads" submodule under the existing "portfolio" module — captures
# prospective-buyer enquiries (who's asking about a car, what they want,
# follow-up tracking) ahead of the dealer_sales Quotation->Sale pipeline,
# which requires a formal Customer to already exist. display_order=25 sits
# it between inventory_vehicles(20) and visit_requests(30), since a lead
# chronologically happens before/alongside a visit request.
# Access is NOT granted to any tenant/user here — same convention as every
# other submodule addition. See 0023's ADMIN-only backfill.
PORTFOLIO_MODULE_ID = "d0000000-0000-0000-0000-000000000004"

NEW_SUBMODULES = [
    ("e0000000-0000-0000-0000-000000000022", "leads", "Leads", 25, [
        ("f0000000-0000-0000-0000-000000000084", "create"),
        ("f0000000-0000-0000-0000-000000000085", "view"),
        ("f0000000-0000-0000-0000-000000000086", "update"),
        ("f0000000-0000-0000-0000-000000000087", "delete"),
    ]),
]


def add_leads_submodule(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")
    Permission = apps.get_model("modules", "Permission")
    SubmodulePermission = apps.get_model("modules", "SubmodulePermission")

    if not Module.objects.filter(id=PORTFOLIO_MODULE_ID).exists():
        return

    for submodule_id, key, name, display_order, links in NEW_SUBMODULES:
        submodule, _ = Submodule.objects.get_or_create(
            module_id=PORTFOLIO_MODULE_ID,
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
        ("modules", "0021_backfill_purchases_permissions"),
    ]

    operations = [
        migrations.RunPython(add_leads_submodule, noop_reverse),
    ]
