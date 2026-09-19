from django.db import migrations


def remap_generic_to_comfort(apps, schema_editor):
    InventoryFeature = apps.get_model("portfolio", "InventoryFeature")
    # The old two-category model ('safety' / 'feature') is being replaced by
    # five more specific categories — 'feature' has no direct equivalent, so
    # existing rows land in 'comfort_convenience' as the closest generic bucket.
    # 'safety' rows are untouched (still a valid choice).
    InventoryFeature.objects.filter(category="feature").update(category="comfort_convenience")


def remap_comfort_to_generic(apps, schema_editor):
    # Not reversible in a lossless way (we can't tell which comfort_convenience
    # rows used to be plain 'feature' rows) — left as a no-op on reverse.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("portfolio", "0005_alter_inventoryfeature_category"),
    ]

    operations = [
        migrations.RunPython(remap_generic_to_comfort, remap_comfort_to_generic),
    ]
