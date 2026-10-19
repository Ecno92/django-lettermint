# django-lettermint

A Django email backend that sends mail through [Lettermint](https://lettermint.co) using the official [`lettermint`](https://pypi.org/project/lettermint/) Python SDK.

## Supported versions

- Django 6.1
- Python 3.12

Other versions may work, but are not tested.


## Configuration and Installation

```bash
pip install django-lettermint
```

Add `"django_lettermint"` to `INSTALLED_APPS`. Then configure it as a mailer in `MAILERS`.

```python
MAILERS = {
    "default": {
        "BACKEND": "django_lettermint.backend.LettermintEmailBackend",
        "OPTIONS": {
            "sending_token": os.environ["LETTERMINT_SENDING_TOKEN"],
            "route": os.environ.get("LETTERMINT_ROUTE", ""),
        },
    },
}
```

| Option | Default | Description |
| --- | --- | --- |
| `sending_token` | `""` | Project sending token (`lm_…`). Sending without it raises `ImproperlyConfigured`. |
| `route` | `""` | Route slug to send through. When it is blank, the project's default route is used. |
| `timeout` | SDK default (30) | Optional. Request timeout in seconds, covering the whole request including the response body. |

## Lettermint-specific options per message

You can set these optional attributes on any `EmailMessage`:

```python
message = EmailMultiAlternatives(subject, text, to=[user.email])
message.attach_alternative(html, "text/html")
message.lettermint_tags = {"campaign": "welcome"}  # name -> value
message.lettermint_metadata = {"user_id": str(user.pk)}
message.lettermint_route = "broadcast"  # overrides the route option
message.lettermint_idempotency_key = f"welcome-{user.pk}"
message.send()

message.lettermint_message_id  # "…", set after a successful send
message.lettermint_status  # "pending"
```

## How a Django message is mapped

| Django | Lettermint |
| --- | --- |
| `from_email`, `to`, `cc`, `bcc`, `reply_to`, `subject` | the same fields |
| `body` | `text`, or `html` when `content_subtype == "html"` |
| `text/html` alternative | `html` |
| `extra_headers` | `headers` |
| `attachments` (tuples, `MIMEPart`, `message/rfc822`) | `attachments`; the `Content-ID` becomes `content_id` |


## Handling failures

The backend doesn't support `fail_silently`, following Django's [Replacing `fail_silently`](https://docs.djangoproject.com/en/6.1/howto/mailers-migration/#migrating-to-mailers-fail-silently) advice. Every failure raises, so the caller decides what to ignore:

| Exception | When |
| --- | --- |
| `ImproperlyConfigured` | The mailer has no `sending_token`. |
| `lettermint.LettermintError` | The API rejected the message or the request failed, e.g. `ValidationError`, `RateLimitError`, `APITimeoutError`. |
| `ValueError` | Django rejects the message (e.g. a newline in a header), or it can't be mapped to Lettermint (e.g. a non-HTML alternative or no `to` recipient). |

```python
from lettermint import LettermintError

try:
    message.send()
except LettermintError:
    logger.warning("Lettermint could not send %r", message.subject)
```

When one call sends several messages and one fails, the messages before it were already sent and have `lettermint_message_id` set.

## Checking it works

- `manage.py check --deploy` warns (`lettermint.W001`) when a Lettermint mailer has no `sending_token`.
- `manage.py check` errors (`lettermint.E001`) on unknown `OPTIONS`, and on a `sending_token` or `timeout` the SDK rejects, such as a token with a trailing newline.
- Send a real test email with `manage.py sendtestemail you@example.com`.

## Limitations

- A message needs at least one `to` recipient; Bcc-only messages raise `ValueError`.
- One API request per message, sent synchronously. There is no batch sending (`/send/batch`) or background queue.
- Only one HTML body and no other alternatives; a `text/plain` alternative next to an HTML body is rejected too.
- No per-message scheduling, tracking settings or sandbox results.
- No webhooks yet, so delivery events are visible only in the Lettermint dashboard.
