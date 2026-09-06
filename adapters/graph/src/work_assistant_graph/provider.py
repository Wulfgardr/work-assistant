from __future__ import annotations

import base64
from datetime import datetime, timezone

from work_assistant.attachments import AttachmentNotAvailable, HtmlExtractor
from work_assistant.models import Attachment, Message

from work_assistant_graph.auth import DeviceFlow, GraphAuthError
from work_assistant_graph.client import GraphClient, GraphError, JsonTransport

MESSAGE_SELECT = (
    "id,conversationId,subject,from,toRecipients,ccRecipients,"
    "receivedDateTime,body,hasAttachments"
)
ATTACHMENT_SELECT = "id,name,contentType,size"
PAGE_TOP = 50


def _normalize_datetime(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recipient_list(entries: object) -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                address = entry.get("emailAddress", {}).get("address", "")
                if isinstance(address, str) and address.strip():
                    found.append(address.strip())
    return tuple(found)


def _body_text(body: object) -> str:
    if not isinstance(body, dict):
        return ""
    content = body.get("content") or ""
    if not isinstance(content, str) or not content.strip():
        return ""
    if str(body.get("contentType") or "").lower() == "html":
        try:
            return HtmlExtractor().extract(content.encode(), content_type="text/html", filename="body.html").strip()
        except Exception:
            return content.strip()
    return content.strip()


class GraphProvider:
    """Read-only Microsoft Graph adapter (delegated Mail.Read only).

    Experimental: verify against the target tenant before trusting any sync.
    Only `fileAttachment` parts expose bytes; nested or reference attachments
    stay metadata-only and report `provider_unsupported` on fetch.
    """

    def __init__(
        self,
        account: str,
        client_id: str,
        token_file: str,
        *,
        tenant: str = "common",
        auth: DeviceFlow | None = None,
        transport: JsonTransport | None = None,
        max_pages: int = 10,
    ):
        self.account = account
        flow = auth or DeviceFlow(client_id, token_file, tenant=tenant)
        self.client = GraphClient(flow, transport, max_pages=max_pages)

    def _attachments(self, message_id: str) -> tuple[Attachment, ...]:
        try:
            body = self.client.get(
                f"/v1.0/me/messages/{message_id}/attachments", {"$select": ATTACHMENT_SELECT}
            )
        except GraphError:
            return ()
        found: list[Attachment] = []
        for index, item in enumerate(body.get("value", [])):
            if not isinstance(item, dict):
                continue
            size = item.get("size")
            found.append(
                Attachment(
                    id=str(item.get("id") or f"att-{index}"),
                    filename=str(item.get("name") or f"attachment-{index}.bin"),
                    content_type=str(item.get("contentType") or "application/octet-stream"),
                    size=size if isinstance(size, int) else None,
                )
            )
        return tuple(found)

    def _to_message(self, item: dict) -> Message:
        identifier = str(item.get("id") or "")
        sender = ""
        sender_box = item.get("from", {})
        if isinstance(sender_box, dict):
            sender = str(sender_box.get("emailAddress", {}).get("address") or "")
        recipients = _recipient_list(item.get("toRecipients")) + _recipient_list(
            item.get("ccRecipients")
        )
        attachments = self._attachments(identifier) if item.get("hasAttachments") else ()
        return Message(
            id=identifier,
            thread_id=str(item.get("conversationId") or identifier),
            account=self.account,
            subject=str(item.get("subject") or ""),
            sender=sender,
            recipients=recipients,
            sent_at=_normalize_datetime(str(item.get("receivedDateTime") or "")),
            body_text=_body_text(item.get("body")),
            folder="inbox",
            attachments=attachments,
            provider_metadata={"adapter": "graph"},
        )

    def list_messages(self, *, since: str | None = None) -> list[Message]:
        params = {
            "$select": MESSAGE_SELECT,
            "$orderby": "receivedDateTime desc",
            "$top": str(PAGE_TOP),
        }
        if since:
            params["$filter"] = f"receivedDateTime gt {since}"
        try:
            items = self.client.list_paged("/v1.0/me/messages", params)
        except (GraphError, GraphAuthError) as exc:
            raise RuntimeError(f"graph sync failed: {exc}") from exc
        messages = [self._to_message(item) for item in items if item.get("id")]
        if since:
            messages = [message for message in messages if message.sent_at > since]
        return messages

    def save_draft(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str:
        """Create a draft on the provider. Never sends."""
        if not to or not subject.strip():
            raise GraphError("provider draft requires recipients and a subject")
        recipients = [{"emailAddress": {"address": address}} for address in to]
        try:
            if in_reply_to:
                if ".." in in_reply_to or "/" in in_reply_to:
                    raise GraphError("invalid graph message reference")
                created = self.client.post(f"/v1.0/me/messages/{in_reply_to}/createReply", {})
                draft_id = str(created.get("id") or "")
                if not draft_id:
                    raise GraphError("graph did not return a draft id")
                self.client.patch(
                    f"/v1.0/me/messages/{draft_id}",
                    {
                        "subject": subject,
                        "body": {"contentType": "Text", "content": body},
                        "toRecipients": recipients,
                    },
                )
            else:
                created = self.client.post(
                    "/v1.0/me/messages",
                    {
                        "subject": subject,
                        "body": {"contentType": "Text", "content": body},
                        "toRecipients": recipients,
                    },
                )
                draft_id = str(created.get("id") or "")
                if not draft_id:
                    raise GraphError("graph did not return a draft id")
            stored = self.client.get(f"/v1.0/me/messages/{draft_id}", {"$select": "id,isDraft"})
            if stored.get("id") != draft_id or stored.get("isDraft") is False:
                raise GraphError("graph draft verification failed")
            return draft_id
        except GraphError:
            raise
        except (GraphAuthError, KeyError, TypeError) as exc:
            raise GraphError(f"graph draft failed: {exc}") from exc

    def fetch_attachment_bytes(self, message_id: str, attachment_id: str) -> bytes:
        if not message_id or not attachment_id or ".." in attachment_id or "/" in attachment_id:
            raise AttachmentNotAvailable("invalid graph attachment reference")
        try:
            item = self.client.get(f"/v1.0/me/messages/{message_id}/attachments/{attachment_id}")
        except GraphError as exc:
            raise AttachmentNotAvailable(f"graph attachment is unavailable: {exc}") from exc
        kind = str(item.get("@odata.type") or "")
        if "fileAttachment" not in kind:
            raise AttachmentNotAvailable(
                "only file attachments expose bytes; nested or reference attachments stay metadata-only"
            )
        try:
            return base64.b64decode(str(item.get("contentBytes") or ""), validate=True)
        except (ValueError, TypeError) as exc:
            raise AttachmentNotAvailable("graph attachment content is not valid base64") from exc


def graph_provider(account) -> GraphProvider:
    """Entry-point factory: receives an AccountConfig, returns a MailProvider."""
    client_id = str(account.options.get("client_id") or "").strip()
    token_file = str(account.options.get("token_file") or "").strip()
    tenant = str(account.options.get("tenant") or "common").strip()
    if not client_id:
        raise ValueError(f"account {account.name!r} requires client_id")
    if not token_file:
        raise ValueError(
            f"account {account.name!r} requires token_file; run work-assistant-graph-login first"
        )
    try:
        max_pages = int(account.options.get("max_pages", 10))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_pages must be an integer") from exc
    return GraphProvider(account.name, client_id, token_file, tenant=tenant, max_pages=max_pages)
