from django.conf import settings
from django.core import checks
from django.core.mail import InvalidMailer
from django.utils.module_loading import import_string
from lettermint import LettermintConfigError

from .backend import LettermintEmailBackend


def _lettermint_backend(backend_path: str) -> type[LettermintEmailBackend] | None:
    try:
        backend = import_string(backend_path)
    except ImportError:
        return None
    if isinstance(backend, type) and issubclass(backend, LettermintEmailBackend):
        return backend
    return None


def _lettermint_mailers() -> dict[str, tuple[type[LettermintEmailBackend], dict]]:
    mailers = {}
    for alias, config in getattr(settings, "MAILERS", {}).items():
        if backend := _lettermint_backend(config.get("BACKEND", "")):
            mailers[alias] = (backend, config.get("OPTIONS", {}))
    return mailers


@checks.register(checks.Tags.mail)
def check_options(app_configs, **kwargs) -> list[checks.CheckMessage]:
    errors: list[checks.CheckMessage] = []
    for alias, (backend_class, options) in _lettermint_mailers().items():
        try:
            backend = backend_class(alias=alias, **options)
            if backend.sending_token:
                with backend:
                    pass
        except (InvalidMailer, TypeError, LettermintConfigError) as error:
            errors.append(
                checks.Error(
                    f"MAILERS[{alias!r}] has invalid Lettermint OPTIONS: {error}",
                    id="lettermint.E001",
                )
            )
    return errors


@checks.register(checks.Tags.mail, deploy=True)
def check_sending_token(app_configs, **kwargs) -> list[checks.CheckMessage]:
    return [
        checks.Warning(
            f"MAILERS[{alias!r}] uses Lettermint without a 'sending_token'.",
            hint="Add the project's sending token to the mailer's OPTIONS.",
            id="lettermint.W001",
        )
        for alias, (_, options) in _lettermint_mailers().items()
        if not options.get("sending_token")
    ]
