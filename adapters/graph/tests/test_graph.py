import base64
import json
import os
from pathlib import Path
import tomllib

import pytest

from work_assistant.attachments import AttachmentNotAvailable
from work_assistant.config import AccountConfig
from work_assistant_graph.auth import DeviceFlow, GraphAuthError, TokenStore
from work_assistant_graph.client import GraphClient, GraphError
from work_assistant_graph.provider import GraphProvider, graph_provider


MESSAGE = {
    "id": "g-1",
    "conversationId": "c-1",
    "subject": "Synthetic review",
    "from": {"emailAddress": {"address": "sam@example.test"}},
    "toRecipients": [{"emailAddress": {"address": "alex@example.test"}}],
    "ccRecipients": [{"emailAddress": {"address": "team@example.test"}}],
    "receivedDateTime": "2026-09-04T10:00:00+00:00",
    "body": {"contentType": "html", "content": "<p>Please <b>review</b> this.</p>"},
    "hasAttachments": True,
}

ATTACHMENTS = {
    "value": [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "id": "f-1",
            "name": "note.txt",
            "contentType": "text/plain",
            "size": 12,
        }
    ]
}

FILE_BYTES = {
    "@odata.type": "#microsoft.graph.fileAttachment",
    "id": "f-1",
    "contentBytes": base64.b64encode(b"synthetic-bytes").decode(),
}


class FakeForms:
    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.calls: list[tuple[str, dict]] = []

    def post_form(self, url: str, fields: dict[str, str]) -> dict:
        self.calls.append((url, fields))
        return self.script.pop(0)


class FakeJson:
    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def request(self, method: str, url: str, headers: dict[str, str], body=None):
        self.calls.append((method, url, headers))
        entry = self.script.pop(0)
        if len(entry) == 3:
            status, response_headers, payload = entry
        else:
            status, payload = entry
            response_headers = {}
        return status, response_headers, json.dumps(payload).encode()


def _auth(tmp_path: Path, script: list[dict], **overrides) -> DeviceFlow:
    return DeviceFlow(
        "synthetic-client-id",
        tmp_path / "graph.token.json",
        tenant="common",
        transport=FakeForms(script),
        **overrides,
    )


def test_device_login_polls_then_stores_cache(tmp_path: Path, capsys) -> None:
    auth = _auth(
        tmp_path,
        [
            {
                "user_code": "SYN-CODE",
                "verification_uri": "https://example.test/device",
                "message": "Open https://example.test/device and enter SYN-CODE",
                "device_code": "synthetic-device-code",
                "interval": 0,
                "expires_in": 900,
            },
            {"error": "authorization_pending"},
            {"access_token": "a", "refresh_token": "r", "expires_in": 3600},
        ],
    )
    result = auth.login()
    assert result["stored"] is True and result["secret_values_exposed"] is False
    shown = capsys.readouterr().out
    assert "SYN-CODE" in shown and "synthetic-device-code" not in shown
    cached = json.loads((tmp_path / "graph.token.json").read_text())
    assert cached["refresh_token"] == "r" and cached["expires_at"] > 0
    if os.name != "nt":
        assert (tmp_path / "graph.token.json").stat().st_mode & 0o777 == 0o600


def test_access_token_refreshes_when_expired(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "graph.token.json")
    store.save({"access_token": "old", "refresh_token": "r", "expires_at": 1})
    auth = _auth(tmp_path, [{"access_token": "new", "expires_in": 3600}])
    assert auth.access_token() == "new"
    url, fields = auth.transport.calls[0]  # type: ignore[attr-defined]
    assert url.endswith("/token") and fields["grant_type"] == "refresh_token"


def test_client_retries_once_after_unauthorized(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "graph.token.json")
    store.save({"access_token": "old", "refresh_token": "r", "expires_at": 9**18})
    auth = _auth(tmp_path, [{"access_token": "new", "expires_in": 3600}])
    client = GraphClient(auth, FakeJson([(401, {}), (200, {"value": []})]))
    assert client.get("/v1.0/me/messages") == {"value": []}


def test_list_maps_graph_message_and_expands_attachments(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "graph.token.json")
    store.save({"access_token": "a", "refresh_token": "r", "expires_at": 9**18})
    auth = _auth(tmp_path, [])
    transport = FakeJson(
        [
            (200, {"value": [MESSAGE], "@odata.nextLink": "https://graph.example.test/next"}),
            (200, {"value": []}),
            (200, ATTACHMENTS),
        ]
    )
    provider = GraphProvider("office", "cid", str(tmp_path / "graph.token.json"), auth=auth, transport=transport)
    messages = provider.list_messages(since="2026-09-01T00:00:00Z")
    assert len(messages) == 1
    message = messages[0]
    assert message.id == "g-1" and message.thread_id == "c-1"
    assert message.sender == "sam@example.test"
    assert message.recipients == ("alex@example.test", "team@example.test")
    assert message.sent_at == "2026-09-04T10:00:00Z"
    assert message.body_text == "Please review this."
    assert [(item.id, item.filename) for item in message.attachments] == [("f-1", "note.txt")]
    first_url = transport.calls[0][1]
    assert "receivedDateTime" in first_url and "2026-09-01" in first_url


def test_fetch_decodes_file_attachments_only(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "graph.token.json")
    store.save({"access_token": "a", "refresh_token": "r", "expires_at": 9**18})
    auth = _auth(tmp_path, [])
    provider = GraphProvider(
        "office", "cid", str(tmp_path / "t.json"), auth=auth, transport=FakeJson([(200, FILE_BYTES)])
    )
    assert provider.fetch_attachment_bytes("g-1", "f-1") == b"synthetic-bytes"
    nested = GraphProvider(
        "office",
        "cid",
        str(tmp_path / "t.json"),
        auth=auth,
        transport=FakeJson([(200, {"@odata.type": "#microsoft.graph.itemAttachment", "id": "n-1"})]),
    )
    with pytest.raises(AttachmentNotAvailable, match="metadata-only"):
        nested.fetch_attachment_bytes("g-1", "n-1")
    with pytest.raises(AttachmentNotAvailable, match="invalid graph"):
        nested.fetch_attachment_bytes("g-1", "../x")


def test_graph_rejects_bad_options_and_hosts() -> None:
    with pytest.raises(GraphAuthError, match="tenant"):
        DeviceFlow("cid", "t.json", tenant="evil/host")
    bare = AccountConfig("office", "graph", "a@example.test", {})
    with pytest.raises(ValueError, match="client_id"):
        graph_provider(bare)
    no_token = AccountConfig("office", "graph", "a@example.test", {"client_id": "cid"})
    with pytest.raises(ValueError, match="token_file"):
        graph_provider(no_token)


def test_package_declares_entry_points_and_login_script() -> None:
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    assert set(pyproject["project"]["entry-points"]["work_assistant.providers"]) == {"graph", "m365"}
    assert "work-assistant-graph-login" in pyproject["project"]["scripts"]


def test_graph_errors_stay_explicit(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "graph.token.json")
    store.save({"access_token": "a", "refresh_token": "r", "expires_at": 9**18})
    auth = _auth(tmp_path, [])
    client = GraphClient(auth, FakeJson([(429, {}, {}), (429, {}, {}), (429, {}, {})]), sleeper=lambda seconds: None)
    with pytest.raises(GraphError, match="throttled"):
        client.get("/v1.0/me/messages")


def test_client_honors_retry_after_then_succeeds(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "graph.token.json")
    store.save({"access_token": "a", "refresh_token": "r", "expires_at": 9**18})
    auth = _auth(tmp_path, [])
    waits: list[float] = []
    client = GraphClient(
        auth, FakeJson([(429, {"Retry-After": "2"}, {}), (200, {}, {"value": []})]), sleeper=waits.append
    )
    assert client.get("/v1.0/me/messages") == {"value": []}
    assert waits == [2.0]


def _draft_auth(tmp_path: Path) -> DeviceFlow:
    store = TokenStore(tmp_path / "graph.token.json")
    store.save({"access_token": "a", "refresh_token": "r", "expires_at": 9**18})
    return _auth(tmp_path, [])


def test_save_draft_creates_and_verifies(tmp_path: Path) -> None:
    auth = _draft_auth(tmp_path)
    transport = FakeJson(
        [
            (201, {"id": "d-1"}),
            (200, {"id": "d-1", "isDraft": True}),
        ]
    )
    provider = GraphProvider("office", "cid", str(tmp_path / "t.json"), auth=auth, transport=transport)
    assert provider.save_draft(to=["sam@example.test"], subject="Re: Synthetic", body="Hi.") == "d-1"
    methods = [call[0] for call in transport.calls]
    assert methods == ["POST", "GET"]
    assert transport.calls[0][1].endswith("/v1.0/me/messages")


def test_save_draft_reply_uses_create_reply(tmp_path: Path) -> None:
    auth = _draft_auth(tmp_path)
    transport = FakeJson(
        [
            (200, {"id": "d-2"}),
            (200, {}),
            (200, {"id": "d-2", "isDraft": True}),
        ]
    )
    provider = GraphProvider("office", "cid", str(tmp_path / "t.json"), auth=auth, transport=transport)
    assert provider.save_draft(to=["s@example.test"], subject="s", body="b", in_reply_to="g-1") == "d-2"
    assert transport.calls[0][1].endswith("/v1.0/me/messages/g-1/createReply")
    assert transport.calls[1][0] == "PATCH"


def test_save_draft_rejects_missing_receipt(tmp_path: Path) -> None:
    auth = _draft_auth(tmp_path)
    provider = GraphProvider(
        "office", "cid", str(tmp_path / "t.json"), auth=auth, transport=FakeJson([(201, {})])
    )
    with pytest.raises(GraphError, match="draft id"):
        provider.save_draft(to=["s@example.test"], subject="s", body="b")
