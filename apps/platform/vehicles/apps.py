from django.apps import AppConfig


class PlatformVehiclesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform.vehicles"
    label = "vehicles"
    verbose_name = "Platform Vehicles"
