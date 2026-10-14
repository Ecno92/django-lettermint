import pytest

from django_lettermint.backend import LettermintEmailBackend
from django_lettermint.checks import check_options, check_sending_token

BACKEND = "django_lettermint.backend.LettermintEmailBackend"


class CustomLettermintBackend(LettermintEmailBackend):
    pass


class NotABackend:
    pass


def test_valid_mailer_passes_checks(settings):
    settings.MAILERS = {
        "default": {"BACKEND": BACKEND, "OPTIONS": {"sending_token": "lm_abc"}},
    }

    assert check_options(None) == []
    assert check_sending_token(None) == []


def test_other_backends_are_ignored(settings):
    settings.MAILERS = {
        "default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"},
    }

    assert check_options(None) == []
    assert check_sending_token(None) == []


def test_unknown_option_is_an_error(settings):
    settings.MAILERS = {
        "default": {"BACKEND": BACKEND, "OPTIONS": {"sending_tokne": "lm_abc"}},
    }

    [error] = check_options(None)

    assert error.id == "lettermint.E001"
    assert "sending_tokne" in error.msg


def test_missing_sending_token_is_a_warning(settings):
    settings.MAILERS = {
        "default": {"BACKEND": BACKEND},
        "bulk": {"BACKEND": BACKEND, "OPTIONS": {"sending_token": ""}},
    }

    warnings = check_sending_token(None)

    assert check_options(None) == []
    assert [warning.id for warning in warnings] == ["lettermint.W001"] * 2
    assert "'bulk'" in warnings[1].msg


def test_fail_silently_option_is_an_error(settings):
    settings.MAILERS = {
        "default": {
            "BACKEND": BACKEND,
            "OPTIONS": {"sending_token": "lm_abc", "fail_silently": True},
        },
    }

    [error] = check_options(None)

    assert error.id == "lettermint.E001"
    assert "fail_silently" in error.msg


def test_subclass_of_the_backend_is_checked(settings):
    settings.MAILERS = {
        "default": {
            "BACKEND": "tests.django_lettermint.test_checks.CustomLettermintBackend"
        },
    }

    assert [warning.id for warning in check_sending_token(None)] == ["lettermint.W001"]


@pytest.mark.parametrize(
    "backend",
    [
        "does.not.exist.EmailBackend",
        "tests.django_lettermint.test_checks.NotABackend",
    ],
)
def test_unknown_backends_are_ignored(settings, backend):
    settings.MAILERS = {"default": {"BACKEND": backend}}

    assert check_options(None) == []
    assert check_sending_token(None) == []


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"sending_token": "lm_abc\n"}, "sending_token contains whitespace"),
        ({"sending_token": "lm_abc", "timeout": 0}, "timeout"),
    ],
)
def test_options_the_sdk_rejects_are_an_error(settings, options, message):
    settings.MAILERS = {"default": {"BACKEND": BACKEND, "OPTIONS": options}}

    [error] = check_options(None)

    assert error.id == "lettermint.E001"
    assert message in error.msg
    assert "lm_abc" not in error.msg
