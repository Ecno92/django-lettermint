# Changelog

## 0.1.0

First release, extracted from the project where it sends production email.

- `LettermintEmailBackend` for Django 6.1's `MAILERS`.
- Per-message `lettermint_tags`, `lettermint_metadata`, `lettermint_route` and `lettermint_idempotency_key`; `lettermint_message_id` and `lettermint_status` after sending.
- System checks `lettermint.E001` (invalid options) and `lettermint.W001` (no sending token, deploy only).
