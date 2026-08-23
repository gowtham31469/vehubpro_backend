from django.db import migrations

BODY_TYPES = [
    ("hatchback", "Hatchback"),
    ("sedan", "Sedan"),
    ("suv", "SUV"),
    ("muv", "MUV"),
    ("luxury_sedan", "Luxury Sedan"),
    ("luxury_suv", "Luxury SUV"),
]


def seed_body_types(apps, schema_editor):
    VehicleType = apps.get_model("vehicles", "VehicleType")
    for code, name in BODY_TYPES:
        VehicleType.objects.get_or_create(code=code, defaults={"name": name, "is_active": True})


def remove_body_types(apps, schema_editor):
    VehicleType = apps.get_model("vehicles", "VehicleType")
    VehicleType.objects.filter(code__in=[code for code, _ in BODY_TYPES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0010_servicevehicle_engine_number"),
    ]

    operations = [
        migrations.RunPython(seed_body_types, remove_body_types),
    ]
