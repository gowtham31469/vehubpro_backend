from django.apps import AppConfig


class PlatformPortfolioConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform.portfolio"
    label = "portfolio"
    verbose_name = "Platform Portfolio"
