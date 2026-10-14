"""Django email backend that sends through the Lettermint API."""

import email.message
import threading
from collections.abc import Sequence
from typing import cast

from django.core.exceptions import ImproperlyConfigured
from django.core.mail import EmailAttachment, EmailMessage, EmailMultiAlternatives
from django.core.mail.backends.base import BaseEmailBackend
from lettermint import EmailAttachment as LettermintAttachment
from lettermint import EmailMessage as LettermintMessage
from lettermint import Lettermint


class LettermintEmailBackend(BaseEmailBackend):
    """Sends each Django email message with one Lettermint API call.

    Configure it in ``MAILERS``; ``OPTIONS`` are passed to ``__init__``.
    """

    def __init__(
        self,
        *,
        sending_token: str = "",
        route: str = "",
        timeout: float | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.sending_token = sending_token
        self.route = route
        self.timeout = timeout
        self.client: Lettermint | None = None
        self._lock = threading.RLock()

    def open(self) -> bool:
        return self._connect()[1]

    def _connect(self) -> tuple[Lettermint, bool]:
        if self.client is not None:
            return self.client, False
        if not self.sending_token:
            raise ImproperlyConfigured(
                "LettermintEmailBackend needs the 'sending_token' option."
            )
        if self.timeout is None:
            self.client = Lettermint(sending_token=self.sending_token)
        else:
            self.client = Lettermint(
                sending_token=self.sending_token, timeout=self.timeout
            )
        return self.client, True

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None

    def send_messages(self, email_messages: Sequence[EmailMessage]) -> int:
        if not email_messages:
            return 0
        with self._lock:
            client, new_connection = self._connect()
            try:
                return sum(self._send(client, message) for message in email_messages)
            finally:
                if new_connection:
                    self.close()

    def _send(self, client: Lettermint, message: EmailMessage) -> bool:
        if not message.recipients():
            return False
        result = client.emails.send(
            build_payload(message, route=self.route),
            idempotency_key=getattr(message, "lettermint_idempotency_key", None),
        )
        message.lettermint_message_id = result["message_id"]  # type: ignore[attr-defined]
        message.lettermint_status = result["status"]  # type: ignore[attr-defined]
        return True


def build_payload(message: EmailMessage, *, route: str = "") -> LettermintMessage:
    """Map a Django email message onto Lettermint's send request.

    ``message.message()`` validates the headers the way Django does.
    """
    overridden = {name.lower() for name in message.extra_headers} & {"to", "cc"}
    if overridden:
        raise ValueError(
            f"Lettermint can't override the {', '.join(sorted(overridden))} header."
        )
    mime = message.message()
    to = _strings(message.to)
    if not to:
        raise ValueError("Lettermint needs at least one 'to' recipient.")

    payload: LettermintMessage = {
        "from": str(message.extra_headers.get("From", message.from_email)),
        "to": to,
        "subject": str(mime["Subject"]),
    }
    if cc := _strings(message.cc):
        payload["cc"] = cc
    if bcc := _strings(message.bcc):
        # Bcc never becomes a header, so message.message() doesn't check it.
        if any("\r" in address or "\n" in address for address in bcc):
            raise ValueError("Bcc addresses may not contain line breaks.")
        payload["bcc"] = bcc
    if "Reply-To" in message.extra_headers:
        payload["reply_to"] = [str(a) for a in mime["Reply-To"].addresses]
    elif reply_to := _strings(message.reply_to):
        payload["reply_to"] = reply_to
    if headers := _custom_headers(mime, message.extra_headers):
        payload["headers"] = headers

    if message.content_subtype == "html":
        payload["html"] = str(message.body)
    elif message.body:
        payload["text"] = str(message.body)

    if isinstance(message, EmailMultiAlternatives):
        for content, mimetype in message.alternatives:
            if mimetype != "text/html":
                raise ValueError(f"Lettermint can't send a {mimetype!r} alternative.")
            if "html" in payload:
                raise ValueError("Lettermint can send only one HTML body.")
            payload["html"] = str(content)

    if message.attachments:
        payload["attachments"] = [
            _build_attachment(attachment) for attachment in message.attachments
        ]

    if route := getattr(message, "lettermint_route", "") or route:
        payload["route"] = route
    if tags := getattr(message, "lettermint_tags", None):
        payload["tags"] = [
            {"name": name, "value": value} for name, value in tags.items()
        ]
    if metadata := getattr(message, "lettermint_metadata", None):
        payload["metadata"] = dict(metadata)
    return payload


def _strings(values: Sequence[object]) -> list[str]:
    return [str(value) for value in values if value]


def _custom_headers(
    mime: email.message.EmailMessage, extra_headers: dict[str, str]
) -> dict[str, str]:
    # Only headers the caller set; From and Reply-To are mapped to their own fields.
    custom = {name.lower() for name in extra_headers} - {"from", "reply-to"}
    return {name: str(value) for name, value in mime.items() if name.lower() in custom}


def _build_attachment(
    attachment: EmailAttachment | email.message.Message,
) -> LettermintAttachment:
    if isinstance(attachment, email.message.Message):
        if attachment.is_multipart():
            raise ValueError("Lettermint can't send multipart attachments.")
        result: LettermintAttachment = {
            "filename": attachment.get_filename() or "attachment",
            "content": cast(bytes, attachment.get_payload(decode=True)),
            "content_type": str(attachment["Content-Type"]),
        }
        if content_id := attachment.get("Content-ID"):
            result["content_id"] = str(content_id).strip("<>")
        return result

    filename, content, mimetype = attachment
    if isinstance(content, EmailMessage):
        content = content.message()
    if isinstance(content, email.message.Message):
        content = content.as_bytes()
    elif isinstance(content, str):
        content = content.encode()
    return {
        "filename": filename or "attachment",
        "content": content,
        "content_type": mimetype,
    }
