from django.apps import AppConfig


class SeminarsConfig(AppConfig):
    name = "apps.seminars"
    verbose_name = "Заседания"

    def ready(self):
        from . import signals  # noqa: F401
