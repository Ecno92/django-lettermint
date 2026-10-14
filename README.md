# django-lettermint

A Django email backend that sends mail through [Lettermint](https://lettermint.co) using the official [`lettermint`](https://pypi.org/project/lettermint/) Python SDK.

Configured as the `default` mailer, everything Django sends goes through Lettermint: `send_mail()`, `EmailMessage.send()`, `mail_admins()`, and so on. Under another alias, it is used only when you pass `using="<alias>"`.

It lives in `src/django_lettermint`, outside the `app` project package, and imports only `django` and `lettermint`. That keeps it ready to become the `django-lettermint` package, the same way `django-extensions` is imported as `django_extensions`.

## Configuration

Add `"django_lettermint"` to `INSTALLED_APPS` to get the system checks. Then configure it as a mailer in `MAILERS`. That setting is new in Django 6.1 and replaces `EMAIL_BACKEND`.

```python
MAILERS = {
    "default": {
        "BACKEND": "django_lettermint.backend.LettermintEmailBackend",
        "OPTIONS": {
            "sending_token": env.str("LETTERMINT_SENDING_TOKEN", ""),
            "route": env.str("LETTERMINT_ROUTE", ""),
        },
    },
}
```

| Option | Default | Description |
| --- | --- | --- |
| `sending_token` | `""` | Project sending token (`lm_…`). Sending without it raises `ImproperlyConfigured`. |
| `route` | `""` | Route slug to send through. When it is blank, the project's default route is used. |
| `timeout` | SDK default (30) | Optional. Request timeout in seconds, covering the whole request including the response body. |

In this project only `ENVIRONMENT=production` uses Lettermint (see `src/app/settings.py`). Other environments use different backends:

| Environment | Backend |
| --- | --- |
| Development | debug toolbar's mail panel |
| Tests | locmem |
| Anything else | console |

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

Django's own `message.message()` validates the subject and headers, so the backend keeps Django's behaviour:

- `headers={"From": ..., "Reply-To": ...}` overrides `from_email` and `reply_to`.
- A `Bcc` header, or a newline in the subject or a header value, raises `ValueError`.
- Addresses are sent as given, with empty ones dropped. Lettermint validates them and rejects invalid ones with a `ValidationError`. A line break in a Bcc address raises `ValueError`.
- The `Date` and `Message-ID` Django generates are not sent; Lettermint sets its own. A `Message-ID` you set in `headers` is sent.

Lettermint has a few extra rules:

- `To` and `Cc` header overrides raise `ValueError`, because Lettermint can't show other recipients than it delivers to.
- A message needs at least one `to` recipient; Bcc-only messages raise `ValueError`.
- Messages without any recipients are skipped, like Django's SMTP backend skips them.

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

- One API request per message, sent synchronously. There is no batch sending (`/send/batch`) or background queue.
- Only one HTML body and no other alternatives; a `text/plain` alternative next to an HTML body is rejected too.
- No per-message scheduling, tracking settings or sandbox results.
- No webhooks yet, so delivery events are visible only in the Lettermint dashboard.

## Notes for a future package

- Per-message `lettermint_scheduled_at`, `lettermint_settings` (open and click tracking) and `lettermint_sandbox_result`.
- Use `send_batch` when one `send_messages()` call gets many messages.
- Map a `text/plain` alternative to `text` when the body is HTML.
- Add `X-LM-Preserve-Message-ID` when a caller sets `Message-ID`, so mail threading keeps working.
- Give the tests their own minimal settings instead of this project's `tests/app/settings.py`.
