import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Step 3 of 3: drop the old VehicleType-backed `vehicle_type` FK, then
    rename `vehicle_type_new` (populated by 0011) into its place."""

    dependencies = [
        ("portfolio", "0011_migrate_vehicle_type_to_body_type"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="inventoryvehicle",
            name="vehicle_type",
        ),
        migrations.RenameField(
            model_name="inventoryvehicle",
            old_name="vehicle_type_new",
            new_name="vehicle_type",
        ),
        migrations.AlterField(
            model_name="inventoryvehicle",
            name="vehicle_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="inventory_vehicles",
                to="vehicles.bodytype",
            ),
        ),
    ]
