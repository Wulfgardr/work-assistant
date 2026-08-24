# Provider adapters

A provider adapter translates one mail service into the stable Work Assistant message model.

## Required contract

Implement `MailProvider`:

```python
class MailProvider(Protocol):
    def list_messages(self, *, since: str | None = None) -> list[Message]: ...
    def save_draft(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str: ...
```

An adapter may intentionally reject `save_draft`. The demo adapter does.

## Adapter responsibilities

- authentication and token refresh;
- provider pagination and throttling;
- conversion of provider IDs and timestamps;
- attachment acquisition and hash calculation;
- exact documentation of read and write capabilities;
- verification of any provider-side mutation.

## Core responsibilities

- multi-account routing;
- normalized message storage;
- payload integrity checks;
- derived knowledge views;
- local draft candidates;
- MCP and CLI contracts.

## Registration

Add the adapter package and register its provider name in `work_assistant.service.provider_for`. Keep adapter-specific configuration under the account table in `work-assistant.toml`.

Never use real messages as fixtures.
