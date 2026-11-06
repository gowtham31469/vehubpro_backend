from django.db import migrations

# Requested sidebar order for the "services" module's submenu:
# Insights, Service Vehicles, Services Master, Quotations, Job Cards,
# Proforma Invoices, Invoices, Reports.
SERVICES_MODULE_ID = "d0000000-0000-0000-0000-000000000003"
SERVICES_SUBMODULE_ORDER = [
    "e0000000-0000-0000-0000-000000000001",  # Insights
    "e0000000-0000-0000-0000-000000000003",  # Service Vehicles
    "e0000000-0000-0000-0000-000000000004",  # Services Master
    "e0000000-0000-0000-0000-000000000012",  # Quotations
    "e0000000-0000-0000-0000-000000000005",  # Job Cards
    "e0000000-0000-0000-0000-000000000018",  # Proforma Invoices
    "e0000000-0000-0000-0000-000000000006",  # Invoices
    "e0000000-0000-0000-0000-000000000013",  # Reports
]


def backfill_display_order(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")

    for position, submodule_id in enumerate(SERVICES_SUBMODULE_ORDER, start=1):
        Submodule.objects.filter(pk=submodule_id).update(display_order=position * 10)

    # Every other module's submodules had no explicit order before this field
    # existed — preserve their current (id-ordered) relative order exactly, so
    # only "services" actually changes on screen from this migration.
    for module in Module.objects.exclude(pk=SERVICES_MODULE_ID):
        subs = list(Submodule.objects.filter(module=module).order_by("id"))
        for position, sub in enumerate(subs, start=1):
            sub.display_order = position * 10
            sub.save(update_fields=["display_order"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0016_alter_submodule_options_submodule_display_order"),
    ]

    operations = [
        migrations.RunPython(backfill_display_order, noop_reverse),
    ]
