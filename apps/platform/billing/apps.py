from django.apps import AppConfig


class PlatformBillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform.billing"
    label = "billing"
    verbose_name = "Platform Billing"
