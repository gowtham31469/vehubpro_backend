from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.common.utils.models import BaseModel, SoftArchiveModel


class VehicleType(BaseModel):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "vehicle_types"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class FuelType(BaseModel):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "fuel_types"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class VehicleBrand(BaseModel, SoftArchiveModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_brands")
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "vehicle_brands"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "tenant",
                condition=Q(is_archived=False),
                name="uniq_vehicle_brand_name_per_tenant_active",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "name"]),
        ]

    def __str__(self) -> str:
        return self.name


class VehicleModel(BaseModel, SoftArchiveModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="vehicle_models")
    brand = models.ForeignKey("vehicles.VehicleBrand", on_delete=models.CASCADE, related_name="models")
    vehicle_type = models.ForeignKey(
        "vehicles.VehicleType", on_delete=models.PROTECT, related_name="vehicle_models", null=True, blank=True
    )
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "vehicle_models"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                "brand",
                Lower("name"),
                condition=Q(is_archived=False),
                name="uniq_vehicle_model_name_per_brand_active",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "brand"]),
        ]

    def __str__(self) -> str:
        return f"{self.brand.name} {self.name}"


class ServiceVehicle(BaseModel, SoftArchiveModel):
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, related_name="service_vehicles")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="service_vehicles")
    registration_no = models.CharField(max_length=20)
    vehicle_type = models.ForeignKey("vehicles.VehicleType", on_delete=models.PROTECT, related_name="service_vehicles")
    brand = models.ForeignKey("vehicles.VehicleBrand", on_delete=models.PROTECT, related_name="service_vehicles")
    vehicle_model = models.ForeignKey("vehicles.VehicleModel", on_delete=models.PROTECT, related_name="service_vehicles")
    year = models.SmallIntegerField()
    fuel_type = models.ForeignKey("vehicles.FuelType", on_delete=models.PROTECT, related_name="service_vehicles")
    engine_cc = models.SmallIntegerField(null=True, blank=True)
    battery_capacity_kwh = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    vin_number = models.CharField(max_length=17, null=True, blank=True)
    engine_number = models.CharField(max_length=50, null=True, blank=True)
    color = models.CharField(max_length=30, null=True, blank=True)
    insurance_expiry = models.DateField(null=True, blank=True)
    puc_expiry = models.DateField(null=True, blank=True)
    permit_expiry = models.DateField(null=True, blank=True)
    fitness_cert_expiry = models.DateField(null=True, blank=True)
    no_of_wheels = models.SmallIntegerField(null=True, blank=True)
    load_capacity_kg = models.IntegerField(null=True, blank=True)
    photo = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = "service_vehicles"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "registration_no"], name="uniq_vehicle_reg_per_tenant"),
        ]
        indexes = [
            models.Index(fields=["tenant", "customer"]),
            models.Index(fields=["tenant", "brand"]),
            models.Index(fields=["tenant", "vehicle_model"]),
            models.Index(fields=["registration_no"]),
            models.Index(fields=["vehicle_type"]),
            models.Index(fields=["fuel_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.registration_no} ({self.brand.name} {self.vehicle_model.name})"
