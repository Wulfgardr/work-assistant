from __future__ import annotations

import email
from email.message import Message as EmailMessage
import mailbox
from pathlib import Path

from work_assistant.attachments import AttachmentNotAvailable
from work_assistant.models import Message
from work_assistant.providers._mime import candidate_parts, stable_id, to_message


class MaildirProvider:
    """Read-only adapter for a local Maildir folder (no network access).

    Useful for public-release users who hold a local export: point the account
    `path` at the Maildir root containing `cur`, `new` (and `tmp`). Only
    synthetic content belongs in tests and fixtures.
    """

    def __init__(self, account: str, path: str | Path):
        self.account = account
        self.path = Path(path)

    def _maildir(self) -> mailbox.Maildir:
        if not self.path.is_dir():
            raise ValueError(f"maildir path {str(self.path)!r} is not a directory")
        return mailbox.Maildir(str(self.path), create=False)

    def _iter(self) -> tuple[str, EmailMessage]:
        box = self._maildir()
        try:
            for key in box.keys():
                raw = box.get_bytes(key)
                if raw is None:
                    continue
                yield key, email.message_from_bytes(raw)
        finally:
            box.close()

    def list_messages(self, *, since: str | None = None) -> list[Message]:
        messages: list[Message] = []
        for key, parsed in self._iter():
            message = to_message(
                self.account, stable_id(key, parsed, prefix="maildir"), parsed, "maildir"
            )
            if since and message.sent_at <= since:
                continue
            messages.append(message)
        return messages

    def save_draft(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str:
        raise RuntimeError("the maildir provider is read-only")

    def fetch_attachment_bytes(self, message_id: str, attachment_id: str) -> bytes:
        if not attachment_id.startswith("part-"):
            raise AttachmentNotAvailable("invalid maildir attachment reference")
        for key, parsed in self._iter():
            if stable_id(key, parsed, prefix="maildir") != message_id:
                continue
            for index, part in enumerate(candidate_parts(parsed)):
                if f"part-{index}" != attachment_id:
                    continue
                payload = part.get_payload(decode=True)
                if payload is None:
                    raise AttachmentNotAvailable("empty maildir attachment part")
                return bytes(payload)
        raise AttachmentNotAvailable("maildir message or attachment part not found")
