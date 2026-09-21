from django.db import migrations


def migrate_to_body_type(apps, schema_editor):
    """Point every InventoryVehicle at the BodyType row with the same code as
    its current (VehicleType-backed) vehicle_type."""
    InventoryVehicle = apps.get_model("portfolio", "InventoryVehicle")
    BodyType = apps.get_model("vehicles", "BodyType")

    body_types = list(BodyType.objects.all())
    body_type_by_code = {bt.code: bt for bt in body_types}
    # Fallback only hit if some InventoryVehicle row was somehow saved with a
    # VehicleType code outside the 6 body-type codes (the admin form only
    # ever offers those 6) — picks a real row rather than leaving the new FK
    # null, since it must become NOT NULL in the next migration.
    fallback = body_types[0] if body_types else None

    for vehicle in InventoryVehicle.objects.select_related("vehicle_type").all():
        body_type = body_type_by_code.get(vehicle.vehicle_type.code, fallback)
        if body_type is not None:
            vehicle.vehicle_type_new_id = body_type.id
            vehicle.save(update_fields=["vehicle_type_new"])


def migrate_back_to_vehicle_type(apps, schema_editor):
    # No-op: the old `vehicle_type` FK (to VehicleType) is untouched by this
    # migration, so reversing just means the temp field stops being read —
    # nothing to undo on the data itself.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("portfolio", "0010_inventoryvehicle_vehicle_type_new"),
    ]

    operations = [migrations.RunPython(migrate_to_body_type, migrate_back_to_vehicle_type)]
