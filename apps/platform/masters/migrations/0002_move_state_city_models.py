import django.db.models.deletion
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0001_initial"),
        ("customers", "0002_state_city_fk"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="State",
                    fields=[
                        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        ("name", models.CharField(max_length=120, unique=True)),
                        ("code", models.CharField(blank=True, max_length=12, null=True, unique=True)),
                        ("is_active", models.BooleanField(default=True)),
                    ],
                    options={
                        "db_table": "states",
                        "ordering": ["name"],
                    },
                ),
                migrations.CreateModel(
                    name="City",
                    fields=[
                        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        ("name", models.CharField(max_length=120)),
                        ("is_active", models.BooleanField(default=True)),
                        (
                            "state",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="cities",
                                to="masters.state",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "cities",
                        "ordering": ["name"],
                        "unique_together": {("state", "name")},
                    },
                ),
                migrations.AddIndex(
                    model_name="state",
                    index=models.Index(fields=["name"], name="states_name_9db832_idx"),
                ),
                migrations.AddIndex(
                    model_name="state",
                    index=models.Index(fields=["is_active"], name="states_is_acti_acbfdd_idx"),
                ),
                migrations.AddIndex(
                    model_name="city",
                    index=models.Index(fields=["state", "name"], name="cities_state_i_cc0ebe_idx"),
                ),
                migrations.AddIndex(
                    model_name="city",
                    index=models.Index(fields=["is_active"], name="cities_is_acti_a959ab_idx"),
                ),
            ],
        ),
    ]
