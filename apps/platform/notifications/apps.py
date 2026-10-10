from django.apps import AppConfig


class PlatformNotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.platform.notifications"
    label = "notifications"
    verbose_name = "Platform Notifications"
