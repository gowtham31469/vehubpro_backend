from django.apps import AppConfig


class PlatformUsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform.users"
    label = "users"
    verbose_name = "Platform Users"
