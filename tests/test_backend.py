import base64
import email.message
import json
from email.mime.text import MIMEText

import httpx
import pytest
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailMessage, EmailMultiAlternatives, InvalidMailer
from django.utils.deprecation import RemovedInDjango70Warning
from lettermint import LettermintConfigError, ValidationError

from django_lettermint.backend import LettermintEmailBackend, build_payload

SEND_URL = "https://api.lettermint.co/v1/send"
TOKEN = "lm_testtoken123"
BACKEND = "django_lettermint.backend.LettermintEmailBackend"


@pytest.fixture
def lettermint_mailer(settings):
    settings.MAILERS = {
        "default": {"BACKEND": BACKEND, "OPTIONS": {"sending_token": TOKEN}},
    }


@pytest.fixture
def send_route(respx_mock):
    return respx_mock.post(SEND_URL).mock(
        return_value=httpx.Response(
            202, json={"message_id": "msg_123", "status": "pending"}
        )
    )


def sent_body(route, call=-1):
    return json.loads(route.calls[call].request.content)


def make_message(**kwargs):
    defaults = {
        "subject": "Hello",
        "body": "Plain body",
        "from_email": "Acme <hello@acme.test>",
        "to": ["jane@example.test"],
    }
    return EmailMessage(**(defaults | kwargs))


def html_message(body="<p>Hi</p>", alternatives=()):
    message = EmailMultiAlternatives("Hello", body, to=["jane@example.test"])
    message.content_subtype = "html"
    for content, mimetype in alternatives:
        message.attach_alternative(content, mimetype)
    return message


def with_attachment(part):
    message = make_message()
    message.attach(part)
    return message


def mime_part(content, **kwargs):
    part = email.message.MIMEPart()
    part.set_content(content, **kwargs)
    return part


def multipart():
    part = email.message.MIMEPart()
    part.make_mixed()
    return part


def test_payload_plain_text():
    assert build_payload(make_message()) == {
        "from": "Acme <hello@acme.test>",
        "to": ["jane@example.test"],
        "subject": "Hello",
        "text": "Plain body",
    }


def test_payload_omits_empty_optional_fields():
    payload = build_payload(make_message(body=""))

    for field in ("text", "cc", "bcc", "reply_to", "headers", "attachments", "route"):
        assert field not in payload


def test_payload_html_only():
    payload = build_payload(html_message())

    assert payload["html"] == "<p>Hi</p>"
    assert "text" not in payload


def test_payload_text_with_html_alternative():
    message = EmailMultiAlternatives("Hello", "Plain body", to=["jane@example.test"])
    message.attach_alternative("<p>Hi</p>", "text/html")

    payload = build_payload(message)

    assert payload["text"] == "Plain body"
    assert payload["html"] == "<p>Hi</p>"


def test_payload_addresses_and_headers_are_passed_through():
    message = make_message(
        to=["", '"Doe, Jane" <jane@example.test>'],
        cc=["cc@example.test"],
        bcc=["", "Hidden <hidden@example.test>"],
        reply_to=["support@acme.test"],
        headers={
            "X-Campaign": "welcome",
            "Content-Language": "nl",
            "Message-ID": "<thread-1@acme.test>",
        },
    )

    payload = build_payload(message)

    assert payload["to"] == ['"Doe, Jane" <jane@example.test>']
    assert payload["cc"] == ["cc@example.test"]
    assert payload["bcc"] == ["Hidden <hidden@example.test>"]
    assert payload["reply_to"] == ["support@acme.test"]
    assert payload["headers"] == {
        "X-Campaign": "welcome",
        "Content-Language": "nl",
        "Message-ID": "<thread-1@acme.test>",
    }


def test_payload_from_and_reply_to_headers_override_like_django():
    message = make_message(
        reply_to=["ignored@acme.test"],
        headers={
            "From": "Shown <shown@acme.test>",
            "Reply-To": "a@acme.test, b@acme.test",
        },
    )

    payload = build_payload(message)

    assert payload["from"] == "Shown <shown@acme.test>"
    assert payload["reply_to"] == ["a@acme.test", "b@acme.test"]
    assert "headers" not in payload


@pytest.mark.parametrize(
    ("message", "error"),
    [
        (lambda: make_message(headers={"To": "x@example.test"}), "override the to"),
        (lambda: make_message(headers={"cc": "x@example.test"}), "override the cc"),
        (lambda: make_message(headers={"Bcc": "x@example.test"}), "Bcc is not a valid"),
        (lambda: make_message(subject="Hi\nBcc: x@example.test"), "linefeed"),
        (lambda: make_message(headers={"X-A": "a\r\nBcc: x@example.test"}), "linefeed"),
        (lambda: make_message(bcc=["x@example.test\nX-Evil: 1"]), "line breaks"),
        (lambda: make_message(to=[], bcc=["x@example.test"]), "at least one 'to'"),
        (lambda: html_message(alternatives=[("# Hi", "text/markdown")]), "markdown"),
        (lambda: html_message(alternatives=[("<p>2</p>", "text/html")]), "one HTML"),
        (lambda: with_attachment(multipart()), "multipart"),
    ],
)
def test_payload_rejects(message, error):
    with pytest.raises(ValueError, match=error):
        build_payload(message())


def test_payload_attachments_from_tuples():
    message = make_message()
    message.attach("invoice.pdf", b"%PDF-1.4", "application/pdf")
    message.attach("notes.txt", "Some notes", "text/plain")

    assert build_payload(message)["attachments"] == [
        {
            "filename": "invoice.pdf",
            "content": b"%PDF-1.4",
            "content_type": "application/pdf",
        },
        {
            "filename": "notes.txt",
            "content": b"Some notes",
            "content_type": "text/plain",
        },
    ]


def test_payload_forwarded_message_attachment():
    message = make_message()
    message.attach("original.eml", make_message(subject="Original"), "message/rfc822")

    [attachment] = build_payload(message)["attachments"]

    assert attachment["content_type"] == "message/rfc822"
    assert b"Subject: Original" in attachment["content"]


def test_payload_inline_mime_part_attachment():
    part = mime_part(b"\x89PNG", maintype="image", subtype="png", filename="logo.png")
    part["Content-ID"] = "<logo>"

    assert build_payload(with_attachment(part))["attachments"] == [
        {
            "filename": "logo.png",
            "content": b"\x89PNG",
            "content_type": "image/png",
            "content_id": "logo",
        }
    ]


def test_payload_mime_attachment_keeps_content_type_parameters():
    part = mime_part(
        "BEGIN:VCALENDAR",
        subtype="calendar",
        params={"method": "REQUEST"},
        filename="invite.ics",
    )

    [attachment] = build_payload(with_attachment(part))["attachments"]

    assert 'method="REQUEST"' in attachment["content_type"]


@pytest.mark.filterwarnings("ignore:MIMEBase attachments are deprecated")
def test_payload_mimebase_attachment_without_filename():
    [attachment] = build_payload(with_attachment(MIMEText("Hello", "plain")))[
        "attachments"
    ]

    assert attachment["filename"] == "attachment"
    assert attachment["content"] == b"Hello"


def test_payload_lettermint_options():
    message = make_message()
    message.lettermint_tags = {"campaign": "welcome"}
    message.lettermint_metadata = {"user_id": "42"}

    payload = build_payload(message, route="transactional")

    assert payload["route"] == "transactional"
    assert payload["tags"] == [{"name": "campaign", "value": "welcome"}]
    assert payload["metadata"] == {"user_id": "42"}


def test_payload_message_route_overrides_default_route():
    message = make_message()
    message.lettermint_route = "broadcast"

    assert build_payload(message, route="transactional")["route"] == "broadcast"


def test_send_mail_through_mailers(lettermint_mailer, send_route):
    sent = mail.send_mail(
        "Hello", "Plain body", "hello@acme.test", ["jane@example.test"]
    )

    assert sent == 1
    request = send_route.calls.last.request
    assert request.headers["x-lettermint-token"] == TOKEN
    assert "idempotency-key" not in request.headers
    assert sent_body(send_route) == {
        "from": "hello@acme.test",
        "to": ["jane@example.test"],
        "subject": "Hello",
        "text": "Plain body",
    }


def test_send_encodes_attachments_and_uses_route(send_route):
    message = make_message()
    message.attach("invoice.pdf", b"%PDF-1.4", "application/pdf")

    LettermintEmailBackend(sending_token=TOKEN, route="transactional").send_messages(
        [message]
    )

    body = sent_body(send_route)
    assert body["route"] == "transactional"
    assert body["attachments"][0]["content"] == base64.b64encode(b"%PDF-1.4").decode()


def test_send_stores_result_and_passes_idempotency_key(send_route):
    message = make_message()
    message.lettermint_idempotency_key = "welcome-42"

    LettermintEmailBackend(sending_token=TOKEN).send_messages([message])

    assert send_route.calls.last.request.headers["idempotency-key"] == "welcome-42"
    assert message.lettermint_message_id == "msg_123"
    assert message.lettermint_status == "pending"


def test_send_messages_reuses_one_client(send_route):
    backend = LettermintEmailBackend(sending_token=TOKEN)

    sent = backend.send_messages([make_message(), make_message()])

    assert sent == 2
    assert send_route.call_count == 2
    assert backend.client is None


def test_open_connection_is_kept_open(send_route):
    backend = LettermintEmailBackend(sending_token=TOKEN)

    assert backend.open() is True
    client = backend.client
    assert backend.open() is False
    backend.send_messages([make_message()])
    assert backend.client is client

    backend.close()
    assert backend.client is None


def test_context_manager_opens_and_closes(send_route):
    with LettermintEmailBackend(sending_token=TOKEN) as backend:
        assert backend.client is not None
    assert backend.client is None


def test_send_messages_without_messages(respx_mock):
    assert LettermintEmailBackend(sending_token=TOKEN).send_messages([]) == 0


def test_message_without_recipients_is_skipped(respx_mock):
    sent = LettermintEmailBackend(sending_token=TOKEN).send_messages(
        [make_message(to=[])]
    )

    assert sent == 0


def test_api_error_is_raised(respx_mock):
    respx_mock.post(SEND_URL).mock(
        return_value=httpx.Response(
            422,
            json={"message": "Invalid.", "errors": {"from": ["Unverified domain."]}},
        )
    )

    with pytest.raises(ValidationError):
        LettermintEmailBackend(sending_token=TOKEN).send_messages([make_message()])


def test_unsupported_message_raises_through_backend(respx_mock):
    message = EmailMultiAlternatives("Hello", "Body", to=["jane@example.test"])
    message.attach_alternative("# Hi", "text/markdown")

    with pytest.raises(ValueError, match="text/markdown"):
        LettermintEmailBackend(sending_token=TOKEN).send_messages([message])


def test_fail_silently_option_is_rejected():
    with pytest.raises(InvalidMailer, match="fail_silently"):
        LettermintEmailBackend(alias="default", fail_silently=True)


def test_deprecated_fail_silently_does_not_swallow_errors(
    lettermint_mailer, respx_mock
):
    respx_mock.post(SEND_URL).mock(return_value=httpx.Response(422, json={}))

    with (
        pytest.warns(RemovedInDjango70Warning),
        pytest.raises(ValidationError),
    ):
        mail.send_mail(
            "Hello",
            "Plain body",
            "hello@acme.test",
            ["jane@example.test"],
            fail_silently=True,
        )


def test_missing_sending_token():
    with pytest.raises(ImproperlyConfigured, match="sending_token"):
        LettermintEmailBackend().send_messages([make_message()])


def test_sending_token_with_trailing_newline():
    with pytest.raises(LettermintConfigError):
        LettermintEmailBackend(sending_token=f"{TOKEN}\n").open()


def test_timeout_defaults_to_the_sdk_default():
    with LettermintEmailBackend(sending_token=TOKEN) as backend:
        assert "timeout=30.0" in repr(backend.client)


def test_timeout_option_is_passed_to_the_client():
    with LettermintEmailBackend(sending_token=TOKEN, timeout=5) as backend:
        assert "timeout=5" in repr(backend.client)


def test_close_without_open():
    LettermintEmailBackend(sending_token=TOKEN).close()
