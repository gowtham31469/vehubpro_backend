from django.apps import AppConfig


class PlatformTenantsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform.tenants"
    label = "tenants"
    verbose_name = "Platform Tenants"
