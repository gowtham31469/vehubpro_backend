from django.db import migrations

# Retires the dormant "Purchases" module (0020/0021) — it was never granted
# to any tenant, has no frontend MODULE_META entry, and no app behind it.
# Superseded by the fresh "Vendor" module (0027/0028), which covers the same
# intent (Vendor Management ~ Vendor List, Purchase Invoice ~ Vendor Bills)
# under the exact nav shape actually requested. is_active is flipped off
# rather than deleting/archiving the rows, so this is fully reversible.
PURCHASES_MODULE_ID = "d0000000-0000-0000-0000-000000000007"


def retire_purchases(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")

    Module.objects.filter(id=PURCHASES_MODULE_ID).update(is_active=False)
    Submodule.objects.filter(module_id=PURCHASES_MODULE_ID).update(is_active=False)


def restore_purchases(apps, schema_editor):
    Module = apps.get_model("modules", "Module")
    Submodule = apps.get_model("modules", "Submodule")

    Module.objects.filter(id=PURCHASES_MODULE_ID).update(is_active=True)
    Submodule.objects.filter(module_id=PURCHASES_MODULE_ID).update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("modules", "0025_backfill_credit_note_permissions"),
    ]

    operations = [
        migrations.RunPython(retire_purchases, restore_purchases),
    ]
