from django.db import migrations

# Generic vehicle categories (as opposed to the body-type rows seeded in
# 0011_seed_body_type_vehicle_types.py) — used by the Service Vehicle form's
# "Vehicle Type" field, not the Inventory listing's "Body Type" field.
GENERIC_TYPES = [
    ("bus", "Bus"),
    ("van", "Van"),
]


def seed_generic_types(apps, schema_editor):
    VehicleType = apps.get_model("vehicles", "VehicleType")
    for code, name in GENERIC_TYPES:
        VehicleType.objects.get_or_create(code=code, defaults={"name": name, "is_active": True})


def remove_generic_types(apps, schema_editor):
    VehicleType = apps.get_model("vehicles", "VehicleType")
    VehicleType.objects.filter(code__in=[code for code, _ in GENERIC_TYPES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0012_add_logo_to_vehicle_brand"),
    ]

    operations = [
        migrations.RunPython(seed_generic_types, remove_generic_types),
    ]
