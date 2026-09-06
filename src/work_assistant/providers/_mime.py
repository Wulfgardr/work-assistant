from __future__ import annotations

from email.message import Message as EmailMessage
from email.utils import getaddresses, parsedate_to_datetime

from work_assistant.models import Attachment, Message


def addresses(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(address for _name, address in getaddresses([value]) if address)


def sent_at(message: EmailMessage) -> str:
    raw = message.get("Date")
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(str(raw)).isoformat()
    except (TypeError, ValueError):
        return str(raw)


def stable_id(fallback_key: str, message: EmailMessage, *, prefix: str) -> str:
    raw = (message.get("Message-ID") or "").strip().strip("<>")
    return raw or f"{prefix}-{fallback_key}"


def candidate_parts(message: EmailMessage) -> list[EmailMessage]:
    return [part for part in message.walk() if not part.is_multipart()]


def mime_attachments(message: EmailMessage) -> tuple[Attachment, ...]:
    found: list[Attachment] = []
    for index, part in enumerate(candidate_parts(message)):
        filename = part.get_filename() or ""
        disposition = (part.get_content_disposition() or "").lower()
        if disposition != "attachment" and not filename:
            continue
        payload = part.get_payload(decode=True) or b""
        found.append(
            Attachment(
                id=f"part-{index}",
                filename=filename or f"part-{index}.bin",
                content_type=part.get_content_type(),
                size=len(payload),
            )
        )
    return tuple(found)


def body_text(message: EmailMessage) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and part.get_content_disposition() is None:
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace").strip()
        return ""
    payload = message.get_payload(decode=True)
    if isinstance(payload, bytes):
        return payload.decode(message.get_content_charset() or "utf-8", errors="replace").strip()
    return payload.strip() if isinstance(payload, str) else ""


def to_message(
    account: str,
    identifier: str,
    parsed: EmailMessage,
    adapter: str,
    *,
    folder: str = "inbox",
) -> Message:
    references = (parsed.get("In-Reply-To") or "").strip().strip("<>")
    return Message(
        id=identifier,
        thread_id=references or identifier,
        account=account,
        subject=str(parsed.get("Subject") or ""),
        sender=(parsed.get("From") or ""),
        recipients=addresses(parsed.get("To")),
        sent_at=sent_at(parsed),
        body_text=body_text(parsed),
        folder=folder,
        attachments=mime_attachments(parsed),
        provider_metadata={"adapter": adapter},
    )
