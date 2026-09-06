import imaplib
import os
from email.message import EmailMessage
from pathlib import Path

import pytest

from work_assistant.config import AccountConfig, load_config
from work_assistant.onboarding import onboarding_plan
from work_assistant.providers.imap import ImapError, ImapProvider
from work_assistant.service import available_providers, provider_for


def _rfc822(*, message_id: str | None = "<syn-1@example.test>", attach: bool = True) -> bytes:
    outgoing = EmailMessage()
    if message_id is not None:
        outgoing["Message-ID"] = message_id
    outgoing["From"] = "sam@example.test"
    outgoing["To"] = "alex@example.test"
    outgoing["Cc"] = "team@example.test"
    outgoing["Subject"] = "Synthetic imap note"
    outgoing["Date"] = "Thu, 04 Sep 2026 10:00:00 +0000"
    outgoing.set_content("See the attached synthetic note.")
    if attach:
        outgoing.add_attachment(
            b"Synthetic imap attachment body.",
            maintype="text",
            subtype="plain",
            filename="note.txt",
        )
    return outgoing.as_bytes()


class FakeImap:
    def __init__(self, mailbox: dict[bytes, bytes], *, login_error: bool = False):
        self.mailbox = mailbox
        self.login_error = login_error
        self.searches: list[tuple] = []
        self.logins: list[tuple[str, str]] = []
        self.selected: list[tuple] = []
        self.appends: list[tuple] = []

    def login(self, username: str, password: str) -> None:
        self.logins.append((username, password))
        if self.login_error:
            raise imaplib.IMAP4.error("bad credentials")

    def select(self, folder: str, readonly: bool = False):
        self.selected.append((folder, readonly))
        return ("OK", [b"2"])

    def uid(self, command: str, *args):
        if command == "SEARCH":
            self.searches.append(args)
            if "HEADER" in args:
                wanted = args[-1]
                found = [
                    uid
                    for uid, raw in self.mailbox.items()
                    if wanted.encode() in raw
                ]
                return ("OK", [b" ".join(found)])
            return ("OK", [b" ".join(self.mailbox)])
        if command == "FETCH":
            uid = args[0] if isinstance(args[0], bytes) else str(args[0]).encode()
            return ("OK", [(b"fetch", self.mailbox[uid])])
        raise AssertionError(f"unexpected imap command {command}")

    def append(self, mailbox: str, flags: str, date_time, message: bytes):
        self.appends.append((mailbox, flags, message))
        if mailbox == "Missing":
            return ("NO", [b"no such mailbox"])
        return ("OK", [b"[APPENDUID 7 42]"])

    def close(self) -> None:
        return None

    def logout(self) -> None:
        return None


def _secret(tmp_path: Path, mode: int = 0o600) -> Path:
    path = tmp_path / "imap.secret"
    path.write_text("synthetic-app-password\n")
    path.chmod(mode)
    return path


def _provider(tmp_path: Path, mailbox: dict[bytes, bytes], **overrides) -> ImapProvider:
    options = {"login_error": False}
    mailbox_arg = dict(mailbox)
    fake = FakeImap(mailbox_arg, login_error=options["login_error"])
    provider = ImapProvider(
        "office",
        "imap.example.test",
        _secret(tmp_path),
        username="alex@example.test",
        client_factory=lambda: fake,  # type: ignore[return-value]
        **overrides,
    )
    provider.fake = fake  # type: ignore[attr-defined]
    return provider


def test_list_maps_mime_and_uses_tls_only_selection(tmp_path: Path) -> None:
    provider = _provider(tmp_path, {b"1": _rfc822(), b"2": _rfc822(message_id=None, attach=False)})
    messages = provider.list_messages()
    assert [message.id for message in messages] == ["syn-1@example.test", "imap-2"]
    first = messages[0]
    assert first.sender == "sam@example.test"
    assert first.recipients == ("alex@example.test",)
    assert first.body_text == "See the attached synthetic note."
    assert [(item.id, item.filename) for item in first.attachments] == [("part-1", "note.txt")]
    assert provider.fake.logins == [("alex@example.test", "synthetic-app-password")]  # type: ignore[attr-defined]
    assert provider.fake.selected == [("INBOX", True)]  # type: ignore[attr-defined]
    assert provider.fake.searches == [(None, "ALL")]  # type: ignore[attr-defined]


def test_since_becomes_server_side_since_and_caps_messages(tmp_path: Path) -> None:
    box = {b"1": _rfc822(), b"2": _rfc822(message_id=None, attach=False), b"3": _rfc822()}
    provider = _provider(tmp_path, box, max_messages=2)
    messages = provider.list_messages(since="2026-09-02T00:00:00Z")
    assert provider.fake.searches == [(None, "(SINCE 02-Sep-2026)")]  # type: ignore[attr-defined]
    assert [message.id for message in messages] == ["imap-2", "syn-1@example.test"]


def test_fetch_attachment_bytes_and_errors(tmp_path: Path) -> None:
    provider = _provider(tmp_path, {b"1": _rfc822()})
    assert provider.fetch_attachment_bytes("syn-1@example.test", "part-1") == (
        b"Synthetic imap attachment body."
    )
    with pytest.raises(Exception, match="part not found"):
        provider.fetch_attachment_bytes("syn-1@example.test", "part-9")
    with pytest.raises(Exception, match="not found"):
        provider.fetch_attachment_bytes("absent@example.test", "part-1")
    with pytest.raises(Exception, match="invalid imap"):
        provider.fetch_attachment_bytes("syn-1@example.test", "../x")


def test_save_draft_appends_without_sending(tmp_path: Path) -> None:
    provider = _provider(tmp_path, {b"1": _rfc822()})
    draft_id = provider.save_draft(
        to=["sam@example.test"], subject="Re: Synthetic", body="Synthetic reply.", in_reply_to="syn-1@example.test"
    )
    assert "APPENDUID" in draft_id
    mailbox, flags, raw = provider.fake.appends[0]  # type: ignore[attr-defined]
    assert mailbox == "Drafts" and flags == "(\\Draft)"
    assert b"Subject: Re: Synthetic" in raw and b"In-Reply-To: <syn-1@example.test>" in raw
    with pytest.raises(ImapError, match="recipients"):
        provider.save_draft(to=[], subject="s", body="b")


def test_save_draft_reports_missing_folder(tmp_path: Path) -> None:
    secret = tmp_path / "office.secret"
    secret.write_text("synthetic-app-password\n")
    secret.chmod(0o600)
    fake = FakeImap({b"1": _rfc822()})
    provider = ImapProvider(
        "office",
        "imap.example.test",
        secret,
        drafts_folder="Missing",
        client_factory=lambda: fake,  # type: ignore[return-value]
    )
    with pytest.raises(ImapError, match="Missing"):
        provider.save_draft(to=["a@example.test"], subject="s", body="b")


def test_authentication_failure_is_explicit(tmp_path: Path) -> None:
    secret = _secret(tmp_path)
    fake = FakeImap({b"1": _rfc822()}, login_error=True)
    provider = ImapProvider(
        "office", "imap.example.test", secret, client_factory=lambda: fake  # type: ignore[return-value]
    )
    with pytest.raises(ImapError, match="authentication failed"):
        provider.list_messages()


def test_secret_file_must_exist_and_be_private(tmp_path: Path) -> None:
    with pytest.raises(ImapError, match="secret_file"):
        ImapProvider("office", "imap.example.test", tmp_path / "missing.secret")
    if os.name == "nt":
        return
    with pytest.raises(ImapError, match="owner-only"):
        ImapProvider("office", "imap.example.test", _secret(tmp_path, 0o640))


def test_registry_validates_imap_options(tmp_path: Path) -> None:
    assert "imap" in available_providers()
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        '[accounts.office]\nprovider = "imap"\naddress = "a@example.test"\n'
        'host = "imap.example.test"\nsecret_file = "imap.secret"\n'
    )
    account = load_config(config_path).accounts["office"]
    assert account.options["host"] == "imap.example.test"
    bare = AccountConfig("office", "imap", "a@example.test", {})
    with pytest.raises(ValueError, match="host and secret_file"):
        provider_for(bare)


def test_onboarding_covers_imap_and_graph() -> None:
    assert onboarding_plan("imap")["adapter_status"] == "available"
    graph = onboarding_plan("graph")
    assert graph["adapter_status"] == "onboarding_ready_adapter_not_bundled"
    assert any("Mail.Read" in step["action"] for step in graph["steps"])
