from __future__ import annotations

from typing import Protocol

from work_assistant.attachments import AttachmentNotAvailable
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

    def fetch_attachment_bytes(self, message_id: str, attachment_id: str) -> bytes:
        """Return raw attachment bytes held by the provider.

        Adapters that cannot supply bytes keep this default, which reports the
        capability gap instead of failing silently. Callers must never persist
        or forward these bytes: only derived, pseudonymized text may cross the
        broker boundary.
        """
        raise AttachmentNotAvailable(
            "this adapter does not supply attachment bytes; only attachment metadata is available"
        )
