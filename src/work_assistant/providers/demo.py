from __future__ import annotations

import json
from pathlib import Path

from work_assistant.attachments import AttachmentNotAvailable
from work_assistant.models import Attachment, Message


class DemoProvider:
    """Read-only JSONL adapter for evaluation, examples, and development."""

    def __init__(self, account: str, source: str | Path, attachments_dir: str | Path | None = None):
        self.account = account
        self.source = Path(source)
        if attachments_dir is not None:
            self.attachments_dir = Path(attachments_dir)
        else:
            self.attachments_dir = self.source.with_name(self.source.stem + ".attachments")

    def list_messages(self, *, since: str | None = None) -> list[Message]:
        messages: list[Message] = []
        with self.source.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                raw = json.loads(line)
                sent_at = str(raw["sent_at"])
                if since and sent_at <= since:
                    continue
                attachments = tuple(Attachment(**item) for item in raw.get("attachments", []))
                messages.append(
                    Message(
                        id=str(raw["id"]),
                        thread_id=str(raw.get("thread_id", raw["id"])),
                        account=self.account,
                        subject=str(raw.get("subject", "")),
                        sender=str(raw["sender"]),
                        recipients=tuple(str(value) for value in raw.get("recipients", [])),
                        sent_at=sent_at,
                        body_text=str(raw.get("body_text", "")),
                        folder=str(raw.get("folder", "inbox")),
                        attachments=attachments,
                        provider_metadata={"adapter": "demo"},
                    )
                )
        return messages

    def save_draft(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str:
        raise RuntimeError("the demo provider is read-only")

    def fetch_attachment_bytes(self, message_id: str, attachment_id: str) -> bytes:
        del message_id
        if (
            not attachment_id
            or attachment_id in {"", ".", ".."}
            or "/" in attachment_id
            or "\\" in attachment_id
            or attachment_id.startswith(".")
        ):
            raise AttachmentNotAvailable("invalid synthetic attachment reference")
        candidate = (self.attachments_dir / attachment_id).resolve()
        if candidate.parent != self.attachments_dir.resolve() or not candidate.is_file():
            raise AttachmentNotAvailable(
                "no synthetic attachment bytes are stored for this reference"
            )
        return candidate.read_bytes()
