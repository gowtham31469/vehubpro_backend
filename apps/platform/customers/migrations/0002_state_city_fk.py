from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0001_initial"),
    ]

    operations = [
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
                        to="customers.state",
                    ),
                ),
            ],
            options={
                "db_table": "cities",
                "ordering": ["name"],
                "unique_together": {("state", "name")},
            },
        ),
        migrations.RemoveField(
            model_name="customer",
            name="city",
        ),
        migrations.RemoveField(
            model_name="customer",
            name="state",
        ),
        migrations.AddField(
            model_name="customer",
            name="state",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="customers",
                to="customers.state",
            ),
        ),
        migrations.AddField(
            model_name="customer",
            name="city",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="customers",
                to="customers.city",
            ),
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
    ]
