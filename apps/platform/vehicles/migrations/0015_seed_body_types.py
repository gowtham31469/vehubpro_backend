from django.db import migrations

# Same 6 rows originally seeded into VehicleType by
# 0011_seed_body_type_vehicle_types.py — moving them to their own table now
# that InventoryVehicle.vehicle_type points at BodyType instead of VehicleType
# (see portfolio/migrations/0010-0012).
BODY_TYPES = [
    ("hatchback", "Hatchback"),
    ("sedan", "Sedan"),
    ("suv", "SUV"),
    ("muv", "MUV"),
    ("luxury_sedan", "Luxury Sedan"),
    ("luxury_suv", "Luxury SUV"),
]


def seed_body_types(apps, schema_editor):
    BodyType = apps.get_model("vehicles", "BodyType")
    for code, name in BODY_TYPES:
        BodyType.objects.get_or_create(code=code, defaults={"name": name, "is_active": True})


def remove_body_types(apps, schema_editor):
    BodyType = apps.get_model("vehicles", "BodyType")
    BodyType.objects.filter(code__in=[code for code, _ in BODY_TYPES]).delete()


class Migration(migrations.Migration):
    dependencies = [("vehicles", "0014_bodytype")]
    operations = [migrations.RunPython(seed_body_types, remove_body_types)]
