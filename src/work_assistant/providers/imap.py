from __future__ import annotations

import email
from email.message import EmailMessage
from email.utils import formatdate
import imaplib
import os
import time
from collections.abc import Callable
from pathlib import Path
from collections.abc import Callable

from work_assistant.attachments import AttachmentNotAvailable
from work_assistant.models import Message
from work_assistant.providers._mime import candidate_parts, stable_id, to_message


class ImapError(RuntimeError):
    pass


def read_secret(secret_file: str | Path, account: str) -> str:
    """Read an app password from a local file without logging its value."""
    path = Path(secret_file).expanduser()
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0].strip() if path.is_file() else ""
    except OSError as exc:
        raise ImapError(f"account {account!r} cannot read secret_file: {exc}") from exc
    if not path.is_file() or not first:
        raise ImapError(
            f"account {account!r} needs a secret_file holding the app password on its first line"
        )
    if os.name != "nt":
        stat = path.stat()
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise ImapError("imap secret_file must be owner-only (0600)")
    return first


def since_to_imap_date(since: str) -> str:
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    try:
        year, month, day = since[:10].split("-")
        return f"{int(day):02d}-{months[int(month) - 1]}-{year}"
    except (ValueError, IndexError) as exc:
        raise ImapError(f"invalid since date {since!r}") from exc


def _uids(client: imaplib.IMAP4_SSL, criterion: str) -> list[bytes]:
    status, data = client.uid("SEARCH", None, criterion)
    if status != "OK":
        raise ImapError("imap search failed")
    return data[0].split() if data and data[0] else []


def _fetch_raw(client: imaplib.IMAP4_SSL, uid: bytes) -> bytes:
    status, data = client.uid("FETCH", uid, "(RFC822)")
    if status != "OK" or not data:
        raise ImapError("imap fetch failed")
    first = data[0]
    if isinstance(first, tuple):
        return bytes(first[1])
    return bytes(first)


class ImapProvider:
    """Read-only generic IMAP adapter. TLS-only by construction.

    Only `imaplib.IMAP4_SSL` is ever used: there is no plaintext path.
    Credentials come from a `secret_file` holding an app password on its
    first line (owner-only on POSIX). Only synthetic content belongs in
    tests and fixtures.
    """

    def __init__(
        self,
        account: str,
        host: str,
        secret_file: str | Path,
        *,
        username: str | None = None,
        port: int = 993,
        folder: str = "INBOX",
        drafts_folder: str = "Drafts",
        max_messages: int = 500,
        timeout: float = 30,
        client_factory: Callable[[], imaplib.IMAP4_SSL] | None = None,
    ):
        host = host.strip().lower()
        if not host or "/" in host or " " in host:
            raise ImapError("host must be a bare hostname")
        self.account = account
        self.host = host
        self.secret = read_secret(secret_file, account)
        self.username = username or account
        self.port = port
        self.folder = folder
        self.drafts_folder = drafts_folder
        self.max_messages = max(1, max_messages)
        self.timeout = timeout
        self._factory = client_factory or (lambda: imaplib.IMAP4_SSL(host, port, timeout=timeout))

    def _login(self) -> imaplib.IMAP4_SSL:
        try:
            client = self._factory()
            client.login(self.username, self.secret)
            return client
        except imaplib.IMAP4.error as exc:
            raise ImapError("imap authentication failed; check username and secret_file") from exc

    def _connect(self) -> imaplib.IMAP4_SSL:
        client = self._login()
        try:
            status, _ = client.select(self.folder, readonly=True)
        except imaplib.IMAP4.error as exc:
            self._close(client)
            raise ImapError(f"imap folder {self.folder!r} is not selectable") from exc
        if status != "OK":
            self._close(client)
            raise ImapError(f"imap folder {self.folder!r} is not selectable")
        return client

    @staticmethod
    def _close(client: imaplib.IMAP4_SSL) -> None:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.logout()
        except Exception:
            pass

    def _parsed(self, client: imaplib.IMAP4_SSL, limit_uids: list[bytes]) -> list[tuple[str, EmailMessage]]:
        return [
            (uid.decode(), email.message_from_bytes(_fetch_raw(client, uid)))
            for uid in limit_uids[-self.max_messages :]
        ]

    def list_messages(self, *, since: str | None = None) -> list[Message]:
        client = self._connect()
        try:
            criterion = f"(SINCE {since_to_imap_date(since)})" if since else "ALL"
            folder = "inbox" if self.folder.upper() == "INBOX" else self.folder
            return [
                to_message(
                    self.account, stable_id(uid, parsed, prefix="imap"), parsed, "imap", folder=folder
                )
                for uid, parsed in self._parsed(client, _uids(client, criterion))
            ]
        finally:
            self._close(client)

    def save_draft(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str:
        """Store a draft on the provider via APPEND. Never sends."""
        if not to or not subject.strip():
            raise ImapError("provider draft requires recipients and a subject")
        draft = EmailMessage()
        draft["From"] = self.username
        draft["To"] = ", ".join(to)
        draft["Subject"] = subject
        draft["Date"] = formatdate(localtime=True)
        if in_reply_to:
            reference = in_reply_to if in_reply_to.startswith("<") else f"<{in_reply_to}>"
            draft["In-Reply-To"] = reference
        draft.set_content(body)
        client = self._login()
        try:
            try:
                status, data = client.append(
                    self.drafts_folder, "(\\Draft)", imaplib.Time2Internaldate(time.time()), draft.as_bytes()
                )
            except imaplib.IMAP4.error as exc:
                raise ImapError(
                    f"cannot store draft in {self.drafts_folder!r}; check the folder exists"
                ) from exc
            if status != "OK":
                raise ImapError(f"cannot store draft in {self.drafts_folder!r}")
            receipt = ""
            if data and data[0]:
                text = data[0].decode(errors="replace") if isinstance(data[0], bytes) else str(data[0])
                if "APPENDUID" in text:
                    receipt = text.strip("[]() ")
            return receipt or f"draft-in-{self.drafts_folder}"
        finally:
            self._close(client)

    def _find_uid(self, client: imaplib.IMAP4_SSL, message_id: str) -> bytes | None:
        if message_id.startswith("imap-"):
            candidate = message_id[len("imap-") :].encode()
            return candidate if candidate.isdigit() else None
        status, data = client.uid("SEARCH", None, "HEADER", "Message-ID", message_id)
        if status != "OK" or not data or not data[0]:
            return None
        found = data[0].split()
        return found[0] if found else None

    def fetch_attachment_bytes(self, message_id: str, attachment_id: str) -> bytes:
        if not attachment_id.startswith("part-"):
            raise AttachmentNotAvailable("invalid imap attachment reference")
        client = self._connect()
        try:
            uid = self._find_uid(client, message_id)
            if uid is None:
                raise AttachmentNotAvailable("imap message not found")
            parsed = email.message_from_bytes(_fetch_raw(client, uid))
            for index, part in enumerate(candidate_parts(parsed)):
                if f"part-{index}" != attachment_id:
                    continue
                payload = part.get_payload(decode=True)
                if payload is None:
                    raise AttachmentNotAvailable("empty imap attachment part")
                return bytes(payload)
            raise AttachmentNotAvailable("imap attachment part not found")
        finally:
            self._close(client)
