from django.apps import AppConfig


class PlatformVendorsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform.vendors"
    label = "vendors"
    verbose_name = "Platform Vendors"
