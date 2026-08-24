from __future__ import annotations

from typing import Protocol

from work_assistant.models import Message


class MailProvider(Protocol):
    """Stable boundary implemented by every provider adapter."""

    def list_messages(self, *, since: str | None = None) -> list[Message]: ...

    def save_draft(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str: ...
