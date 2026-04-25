from django.apps import AppConfig


class PlatformModulesConfig(AppConfig):
    default_auto_field = "django.db.models.UUIDField"
    name = "apps.platform.modules"
    label = "modules"
    verbose_name = "Platform Modules"
