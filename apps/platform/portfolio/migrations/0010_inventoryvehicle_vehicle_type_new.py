import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Step 1 of 3 (see 0011, 0012): add a new, temporary FK to the incoming
    vehicles.BodyType table alongside the existing `vehicle_type` FK to
    vehicles.VehicleType. Kept nullable and separately named so existing
    rows aren't touched here — 0011 populates it, 0012 removes the old
    field and renames this one into its place.
    """

    dependencies = [
        ("vehicles", "0015_seed_body_types"),
        ("portfolio", "0009_inventoryvehicle_cover_thumbnail"),
    ]

    operations = [
        migrations.AddField(
            model_name="inventoryvehicle",
            name="vehicle_type_new",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="inventory_vehicles_pending",
                to="vehicles.bodytype",
            ),
        ),
    ]
