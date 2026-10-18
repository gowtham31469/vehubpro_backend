from django.db import migrations

# Same 6 codes seeded into VehicleType by 0011_seed_body_type_vehicle_types.py
# and now living in BodyType instead (see 0015_seed_body_types). Originally
# assumed safe to delete because portfolio.0012 had already repointed every
# InventoryVehicle.vehicle_type away from these VehicleType rows — but that
# assumption didn't account for ServiceVehicle.vehicle_type / VehicleModel
# .vehicle_type (Garage-side, both PROTECT) also still pointing at them in
# real deployments: a dealership that both services and sells cars can have
# live ServiceVehicle records (actual customers' cars) categorized by these
# same body-type codes. Deleting those out from under them would be real
# data loss, so this only removes a code once nothing live references it —
# in a fresh/already-clean environment that's still every row (unchanged
# behavior); anywhere still using one, it's left alone instead of crashing
# the whole migration.
BODY_TYPE_CODES = ["hatchback", "sedan", "suv", "muv", "luxury_sedan", "luxury_suv"]


def remove_body_types(apps, schema_editor):
    VehicleType = apps.get_model("vehicles", "VehicleType")
    for vehicle_type in VehicleType.objects.filter(code__in=BODY_TYPE_CODES):
        if vehicle_type.service_vehicles.exists() or vehicle_type.vehicle_models.exists():
            continue
        vehicle_type.delete()


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
