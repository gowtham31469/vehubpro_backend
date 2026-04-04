# ServiceVehicle: brand/model CharFields -> FKs to VehicleBrand / VehicleModel

import re
import uuid

import django.db.models.deletion
from django.db import migrations, models


def _slug_code(text: str, max_len: int = 50) -> str:
    raw = re.sub(r"[^A-Z0-9]+", "_", (text or "").strip().upper()).strip("_")
    return (raw or "UNKNOWN")[:max_len]


def _unique_brand_code(VehicleBrand, tenant_id, base: str) -> str:
    code = _slug_code(base)[:50]
    while VehicleBrand.objects.filter(tenant_id=tenant_id, code=code).exists():
        code = _slug_code(f"{base}_{uuid.uuid4().hex[:8]}")[:50]
    return code


def _unique_model_code(VehicleModel, tenant_id, brand_id, base: str) -> str:
    code = _slug_code(base)[:50]
    while VehicleModel.objects.filter(tenant_id=tenant_id, brand_id=brand_id, code=code).exists():
        code = _slug_code(f"{base}_{uuid.uuid4().hex[:8]}")[:50]
    return code


def forwards_fill_brand_model_fks(apps, schema_editor):
    ServiceVehicle = apps.get_model("vehicles", "ServiceVehicle")
    VehicleBrand = apps.get_model("vehicles", "VehicleBrand")
    VehicleModel = apps.get_model("vehicles", "VehicleModel")

    for sv in ServiceVehicle.objects.all().iterator():
        legacy_brand = (sv.brand_legacy or "").strip()
        legacy_model = (sv.model_legacy or "").strip()
        if not legacy_brand or not legacy_model:
            continue

        brand = (
            VehicleBrand.objects.filter(tenant_id=sv.tenant_id, name__iexact=legacy_brand[:100]).first()
            or VehicleBrand.objects.filter(tenant_id=sv.tenant_id, code=_slug_code(legacy_brand)[:50]).first()
        )
        if not brand:
            code = _unique_brand_code(VehicleBrand, sv.tenant_id, legacy_brand)
            brand = VehicleBrand.objects.create(
                tenant_id=sv.tenant_id,
                code=code,
                name=legacy_brand[:100],
                is_active=True,
            )

        vm = (
            VehicleModel.objects.filter(
                tenant_id=sv.tenant_id,
                brand_id=brand.id,
                name__iexact=legacy_model[:100],
            ).first()
            or VehicleModel.objects.filter(
                tenant_id=sv.tenant_id,
                brand_id=brand.id,
                code=_slug_code(legacy_model)[:50],
            ).first()
        )
        if not vm:
            mcode = _unique_model_code(VehicleModel, sv.tenant_id, brand.id, legacy_model)
            vm = VehicleModel.objects.create(
                tenant_id=sv.tenant_id,
                brand_id=brand.id,
                code=mcode,
                name=legacy_model[:100],
                is_active=True,
            )

        ServiceVehicle.objects.filter(pk=sv.pk).update(brand_id=brand.id, vehicle_model_id=vm.id)

    UNKNOWN = "_LEGACY_UNKNOWN_"
    for sv in ServiceVehicle.objects.filter(brand__isnull=True).iterator():
        brand = VehicleBrand.objects.filter(tenant_id=sv.tenant_id, code=UNKNOWN).first()
        if not brand:
            brand = VehicleBrand.objects.create(
                tenant_id=sv.tenant_id,
                code=UNKNOWN,
                name="Unknown (legacy)",
                is_active=True,
            )
        vm = VehicleModel.objects.filter(tenant_id=sv.tenant_id, brand_id=brand.id, code=UNKNOWN).first()
        if not vm:
            vm = VehicleModel.objects.create(
                tenant_id=sv.tenant_id,
                brand_id=brand.id,
                code=UNKNOWN,
                name="Unknown (legacy)",
                is_active=True,
            )
        ServiceVehicle.objects.filter(pk=sv.pk).update(brand_id=brand.id, vehicle_model_id=vm.id)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0004_tenant_brand_model"),
    ]

    operations = [
        migrations.RenameField(
            model_name="servicevehicle",
            old_name="brand",
            new_name="brand_legacy",
        ),
        migrations.RenameField(
            model_name="servicevehicle",
            old_name="model",
            new_name="model_legacy",
        ),
        migrations.AddField(
            model_name="servicevehicle",
            name="brand",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="service_vehicles",
                to="vehicles.vehiclebrand",
            ),
        ),
        migrations.AddField(
            model_name="servicevehicle",
            name="vehicle_model",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="service_vehicles",
                to="vehicles.vehiclemodel",
            ),
        ),
        migrations.RunPython(forwards_fill_brand_model_fks, noop),
        migrations.RemoveField(model_name="servicevehicle", name="brand_legacy"),
        migrations.RemoveField(model_name="servicevehicle", name="model_legacy"),
        migrations.AlterField(
            model_name="servicevehicle",
            name="brand",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="service_vehicles",
                to="vehicles.vehiclebrand",
            ),
        ),
        migrations.AlterField(
            model_name="servicevehicle",
            name="vehicle_model",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="service_vehicles",
                to="vehicles.vehiclemodel",
            ),
        ),
        migrations.AddIndex(
            model_name="servicevehicle",
            index=models.Index(fields=["tenant", "brand"], name="service_veh_tenant__brand_idx"),
        ),
        migrations.AddIndex(
            model_name="servicevehicle",
            index=models.Index(fields=["tenant", "vehicle_model"], name="service_veh_tenant__vmodel_idx"),
        ),
    ]
