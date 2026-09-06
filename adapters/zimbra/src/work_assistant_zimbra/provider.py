from __future__ import annotations

from datetime import datetime, timezone
import xml.etree.ElementTree as ET

from work_assistant.attachments import AttachmentNotAvailable
from work_assistant.models import Attachment, Message

from work_assistant_zimbra.soap import (
    SoapClient,
    UrllibTransport,
    ZimbraError,
    ZimbraTransportError,
    get_msg_request,
    load_session_cookies,
    save_draft_request,
    search_request,
)

QUERY = "in:inbox"
PAGE_LIMIT = 100
MAX_PAGES = 10


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, tag: str) -> list[ET.Element]:
    return [child for child in element if _local(child.tag) == tag]


def _child_text(element: ET.Element, tag: str) -> str:
    for child in element:
        if _local(child.tag) == tag:
            return (child.text or "").strip()
    return ""


def _epoch_ms_to_iso(value: str) -> str:
    try:
        moment = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return ""
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _addresses(message: ET.Element) -> tuple[str, tuple[str, ...]]:
    sender = ""
    recipients: list[str] = []
    for entry in _children(message, "e"):
        kind = (entry.get("t") or "").lower()
        address = (entry.get("a") or "").strip()
        if not address:
            continue
        if kind == "f" and not sender:
            sender = address
        elif kind in {"t", "c", "b"}:
            recipients.append(address)
    return sender, tuple(recipients)


def _walk_parts(message: ET.Element) -> tuple[ET.Element, ...]:
    found: list[ET.Element] = []

    def visit(element: ET.Element) -> None:
        for child in _children(element, "mp"):
            found.append(child)
            visit(child)

    visit(message)
    return tuple(found)


def _body_text(message: ET.Element) -> tuple[str, bool]:
    parts = _walk_parts(message)
    for part in parts:
        if part.get("body") == "1" and (part.get("ct") or "").split(";")[0].strip().lower() == "text/plain":
            return _child_text(part, "content"), part.get("truncated") == "1"
    for part in parts:
        if (part.get("ct") or "").split(";")[0].strip().lower() == "text/plain":
            content = _child_text(part, "content")
            if content:
                return content, part.get("truncated") == "1"
    return "", False


def _attachments(message: ET.Element) -> tuple[Attachment, ...]:
    found: list[Attachment] = []
    for part in _walk_parts(message):
        filename = part.get("filename") or ""
        disposition = (part.get("cd") or "").lower()
        if disposition != "attachment" and not filename:
            continue
        try:
            size = int(part.get("s") or 0)
        except ValueError:
            size = 0
        found.append(
            Attachment(
                id=str(part.get("part") or f"part-{len(found)}"),
                filename=filename or f"part-{len(found)}.bin",
                content_type=(part.get("ct") or "application/octet-stream").split(";")[0].strip(),
                size=size,
            )
        )
    return tuple(found)


def _to_message(account: str, element: ET.Element, *, full: ET.Element | None = None) -> Message:
    source = full if full is not None else element
    identifier = str(element.get("id") or source.get("id") or "")
    sender, recipients = _addresses(source)
    body, truncated = _body_text(source)
    return Message(
        id=identifier,
        thread_id=str(source.get("cid") or identifier),
        account=account,
        subject=str(source.get("su") or ""),
        sender=sender,
        recipients=recipients,
        sent_at=_epoch_ms_to_iso(str(source.get("d") or "")),
        body_text=body,
        folder="inbox",
        attachments=_attachments(source),
        provider_metadata={"adapter": "zimbra", "body_truncated": truncated},
    )


class ZimbraProvider:
    """Read-only Zimbra/Carbonio adapter over SOAP + content servlet.

    Experimental: request shapes follow the published SOAP reference, but
    server versions differ. Verify against the target host before trusting
    any sync, and never paste session material into prompts or issues.
    """

    def __init__(
        self,
        account: str,
        host: str,
        session_file: str,
        transport: UrllibTransport | None = None,
        *,
        timeout: float = 30,
        search_pages: int = MAX_PAGES,
    ):
        self.account = account
        self.client = SoapClient(
            host, load_session_cookies(session_file), transport, timeout=timeout
        )
        self.search_pages = max(1, search_pages)

    def _full_message(self, identifier: str) -> ET.Element | None:
        try:
            response = self.client.call(get_msg_request(identifier), "GetMsgResponse")
        except ZimbraError:
            return None
        children = _children(response, "m")
        return children[0] if children else None

    def list_messages(self, *, since: str | None = None) -> list[Message]:
        messages: list[Message] = []
        for page in range(self.search_pages):
            response = self.client.call(
                search_request(QUERY, limit=PAGE_LIMIT, offset=page * PAGE_LIMIT),
                "SearchResponse",
            )
            hits = _children(response, "m")
            if not hits:
                break
            for hit in hits:
                sent_at = _epoch_ms_to_iso(str(hit.get("d") or ""))
                if since and sent_at and sent_at <= since:
                    return messages
                full = None
                if not _walk_parts(hit):
                    full = self._full_message(str(hit.get("id") or ""))
                messages.append(_to_message(self.account, hit, full=full))
            if response.get("more") == "0":
                break
        return messages

    def save_draft(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str:
        """Store a draft on the provider. Standalone only; never sends."""
        if in_reply_to:
            raise ZimbraError("zimbra reply drafts are not supported; create a standalone draft")
        if not to or not subject.strip():
            raise ZimbraError("provider draft requires recipients and a subject")
        response = self.client.call(save_draft_request(to, subject, body), "SaveDraftResponse")
        stored = _children(response, "m")
        draft_id = str(stored[0].get("id") or "") if stored else ""
        if not draft_id:
            raise ZimbraError("zimbra did not return a draft id")
        return draft_id

    def fetch_attachment_bytes(self, message_id: str, attachment_id: str) -> bytes:
        if not message_id or not attachment_id or ".." in attachment_id or "/" in attachment_id:
            raise AttachmentNotAvailable("invalid zimbra attachment reference")
        try:
            return self.client.download(
                f"/service/home/~/?id={message_id}&part={attachment_id}"
            )
        except ZimbraTransportError as exc:
            raise AttachmentNotAvailable(str(exc)) from exc


def zimbra_provider(account) -> ZimbraProvider:
    """Entry-point factory: receives an AccountConfig, returns a MailProvider."""
    host = str(account.options.get("host") or "").strip()
    session_file = str(account.options.get("session_file") or "").strip()
    if not host:
        raise ValueError(f"account {account.name!r} requires host")
    if not session_file:
        raise ValueError(
            f"account {account.name!r} requires session_file; "
            "run `work-assistant import-zimbra-har` to create it"
        )
    try:
        search_pages = int(account.options.get("search_pages", MAX_PAGES))
    except (TypeError, ValueError) as exc:
        raise ValueError("search_pages must be an integer") from exc
    return ZimbraProvider(account.name, host, session_file, search_pages=search_pages)
