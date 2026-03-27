from django.apps import AppConfig


class PlatformCustomersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform.customers"
    label = "customers"
    verbose_name = "Platform Customers"
