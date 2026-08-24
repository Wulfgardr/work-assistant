from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Attachment:
    id: str
    filename: str
    content_type: str = "application/octet-stream"
    size: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class Message:
    id: str
    thread_id: str
    account: str
    subject: str
    sender: str
    recipients: tuple[str, ...]
    sent_at: str
    body_text: str
    folder: str = "inbox"
    attachments: tuple[Attachment, ...] = field(default_factory=tuple)
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
