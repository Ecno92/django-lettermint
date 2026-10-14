from django.apps import AppConfig


class LettermintConfig(AppConfig):
    name = "django_lettermint"

    def ready(self):
        from . import checks  # noqa: F401
