from django.db import migrations

# Adds the Sales, Booking & Delivery submodule under the Portfolio module,
# plus its SubmodulePermission links — covers the dealer_sales Phase 2
# workflow (quotation/negotiation/reservation/booking/sale/delivery/
# settlement/invoice) as one continuous sales-staff permission, deliberately
# separate from vehicle_work_expenses (0007) since a different staff member
# often owns reconditioning vs. sales. Mirrors 0007's pattern exactly.
# Access is NOT granted to any user here — see 0010's ADMIN-only backfill.
PORTFOLIO_MODULE_ID = "d0000000-0000-0000-0000-000000000004"

NEW_SUBMODULES = [
    # (submodule_id, key, name, [(submodule_permission_id, permission_key), ...])
    ("e0000000-0000-0000-0000-000000000016", "vehicle_sales", "Sales, Booking & Delivery", [
        ("f0000000-0000-0000-0000-000000000064", "view"),
        ("f0000000-0000-0000-0000-000000000065", "create"),
        ("f0000000-0000-0000-0000-000000000066", "update"),
        ("f0000000-0000-0000-0000-000000000067", "delete"),
        ("f0000000-0000-0000-0000-000000000068", "record_payment"),
    ]),
]


def add_submodules(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")
    Permission = apps.get_model("modules", "Permission")
    SubmodulePermission = apps.get_model("modules", "SubmodulePermission")

    if not Module.objects.filter(id=PORTFOLIO_MODULE_ID).exists():
        return

    for submodule_id, key, name, links in NEW_SUBMODULES:
        submodule, _ = Submodule.objects.get_or_create(
            module_id=PORTFOLIO_MODULE_ID,
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
        ("modules", "0008_backfill_vehicle_work_expenses_permissions"),
    ]

    operations = [
        migrations.RunPython(add_submodules, noop_reverse),
    ]
