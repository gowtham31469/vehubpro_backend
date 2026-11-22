from django.db import migrations

# Moves "Vendor" up in the sidebar so it sits directly below "Customer
# Management" and above "Services" — i.e. Dashboard, User Management,
# Customer Management, Vendor, Services, Portfolio, Configuration.
NEW_ORDER = {
    "customer_management": 30,
    "vendor": 40,
    "services": 50,
    "portfolio": 60,
    "configuration": 70,
}
OLD_ORDER = {
    "services": 30,
    "portfolio": 40,
    "configuration": 50,
    "customer_management": 60,
    "vendor": 80,
}


def apply_order(apps, schema_editor, order_map):
    Module = apps.get_model("modules", "Module")
    for key, display_order in order_map.items():
        Module.objects.filter(key=key).update(display_order=display_order)


def reorder_new(apps, schema_editor):
    apply_order(apps, schema_editor, NEW_ORDER)


def reorder_old(apps, schema_editor):
    apply_order(apps, schema_editor, OLD_ORDER)


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0032_delete_purchases_module"),
    ]

    operations = [
        migrations.RunPython(reorder_new, reorder_old),
    ]
