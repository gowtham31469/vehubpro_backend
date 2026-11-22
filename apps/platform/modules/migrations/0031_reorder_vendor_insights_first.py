from django.db import migrations

# Reorders the Vendor module's submodules so Insights appears first in the
# sidebar, ahead of List/Bills/Payments.
VENDOR_MODULE_ID = "d0000000-0000-0000-0000-000000000008"

NEW_ORDER = {
    "vendor_insights": 10,
    "vendor_list": 20,
    "vendor_bills": 30,
    "vendor_payments": 40,
}
OLD_ORDER = {
    "vendor_list": 10,
    "vendor_bills": 20,
    "vendor_payments": 30,
    "vendor_insights": 40,
}


def apply_order(apps, schema_editor, order_map):
    Submodule = apps.get_model("modules", "Submodule")
    for key, display_order in order_map.items():
        Submodule.objects.filter(module_id=VENDOR_MODULE_ID, key=key).update(display_order=display_order)


def reorder_insights_first(apps, schema_editor):
    apply_order(apps, schema_editor, NEW_ORDER)


def reorder_insights_last(apps, schema_editor):
    apply_order(apps, schema_editor, OLD_ORDER)


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0030_backfill_vendor_insights_permissions"),
    ]

    operations = [
        migrations.RunPython(reorder_insights_first, reorder_insights_last),
    ]
