# Generated manually: tenant-scoped brands and models

import django.db.models.deletion
from django.db import migrations, models


def assign_tenant_to_brands_and_models(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    VehicleBrand = apps.get_model("vehicles", "VehicleBrand")
    VehicleModel = apps.get_model("vehicles", "VehicleModel")
    first = Tenant.objects.order_by("pk").first()
    if not first:
        return
    for brand in VehicleBrand.objects.all():
        if getattr(brand, "tenant_id", None) is None:
            brand.tenant_id = first.pk
            brand.save(update_fields=["tenant_id"])
    for m in VehicleModel.objects.all():
        if getattr(m, "tenant_id", None) is None:
            b = VehicleBrand.objects.get(pk=m.brand_id)
            m.tenant_id = b.tenant_id
            m.save(update_fields=["tenant_id"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0004_tenant_branding_storage_charfields"),
        ("vehicles", "0003_vehiclebrand_vehiclemodel"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vehiclebrand",
            name="code",
            field=models.CharField(db_index=True, max_length=50),
        ),
        migrations.AlterField(
            model_name="vehiclebrand",
            name="name",
            field=models.CharField(max_length=100),
        ),
        migrations.AddField(
            model_name="vehiclebrand",
            name="tenant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="vehicle_brands",
                to="tenants.tenant",
            ),
        ),
        migrations.AddField(
            model_name="vehiclemodel",
            name="tenant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="vehicle_models",
                to="tenants.tenant",
            ),
        ),
        migrations.RunPython(assign_tenant_to_brands_and_models, noop),
        migrations.AlterField(
            model_name="vehiclebrand",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="vehicle_brands",
                to="tenants.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="vehiclemodel",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="vehicle_models",
                to="tenants.tenant",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="vehiclemodel",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="vehiclebrand",
            constraint=models.UniqueConstraint(
                fields=("tenant", "code"),
                name="uniq_vehicle_brand_code_per_tenant",
            ),
        ),
        migrations.AddConstraint(
            model_name="vehiclebrand",
            constraint=models.UniqueConstraint(
                fields=("tenant", "name"),
                name="uniq_vehicle_brand_name_per_tenant",
            ),
        ),
        migrations.AddConstraint(
            model_name="vehiclemodel",
            constraint=models.UniqueConstraint(
                fields=("tenant", "brand", "code"),
                name="uniq_vehicle_model_code_per_brand_tenant",
            ),
        ),
        migrations.AddIndex(
            model_name="vehiclebrand",
            index=models.Index(fields=["tenant", "name"], name="vehicle_bra_tenant__e09f3f_idx"),
        ),
        migrations.AddIndex(
            model_name="vehiclemodel",
            index=models.Index(fields=["tenant", "brand"], name="vehicle_mod_tenant__143d6f_idx"),
        ),
    ]
