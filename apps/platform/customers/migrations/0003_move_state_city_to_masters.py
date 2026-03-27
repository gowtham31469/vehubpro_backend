import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0002_move_state_city_models"),
        ("customers", "0002_state_city_fk"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="customer",
                    name="state",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="customers",
                        to="masters.state",
                    ),
                ),
                migrations.AlterField(
                    model_name="customer",
                    name="city",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="customers",
                        to="masters.city",
                    ),
                ),
                migrations.DeleteModel(name="City"),
                migrations.DeleteModel(name="State"),
            ],
        ),
    ]
