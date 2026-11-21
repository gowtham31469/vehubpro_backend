from django.apps import AppConfig


class PlatformLeadsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform.leads"
    label = "leads"
    verbose_name = "Platform Leads"
