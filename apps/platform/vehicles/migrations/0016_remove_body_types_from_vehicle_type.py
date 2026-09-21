from django.db import migrations

# Same 6 codes seeded into VehicleType by 0011_seed_body_type_vehicle_types.py
# and now living in BodyType instead (see 0015_seed_body_types). Safe to
# delete here because portfolio.0012 has already repointed every
# InventoryVehicle.vehicle_type away from these VehicleType rows — nothing
# should still reference them (VehicleType has on_delete=PROTECT relations
# elsewhere, so this would fail loudly rather than silently orphan data).
BODY_TYPE_CODES = ["hatchback", "sedan", "suv", "muv", "luxury_sedan", "luxury_suv"]


def remove_body_types(apps, schema_editor):
    VehicleType = apps.get_model("vehicles", "VehicleType")
    VehicleType.objects.filter(code__in=BODY_TYPE_CODES).delete()


def restore_body_types(apps, schema_editor):
    VehicleType = apps.get_model("vehicles", "VehicleType")
    BodyType = apps.get_model("vehicles", "BodyType")
    for bt in BodyType.objects.filter(code__in=BODY_TYPE_CODES):
        VehicleType.objects.get_or_create(code=bt.code, defaults={"name": bt.name, "is_active": bt.is_active})


class Migration(migrations.Migration):
    dependencies = [
        ("vehicles", "0015_seed_body_types"),
        ("portfolio", "0012_finalize_inventoryvehicle_body_type"),
    ]

    operations = [migrations.RunPython(remove_body_types, restore_body_types)]
