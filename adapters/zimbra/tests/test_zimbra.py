import json
from pathlib import Path
import tomllib
import xml.etree.ElementTree as ET

import pytest

from work_assistant.attachments import AttachmentNotAvailable
from work_assistant.config import AccountConfig
from work_assistant_zimbra.provider import QUERY, ZimbraProvider, zimbra_provider
from work_assistant_zimbra.soap import (
    SoapClient,
    ZimbraError,
    ZimbraSoapError,
    ZimbraTransportError,
    build_envelope,
    load_session_cookies,
    parse_response,
    search_request,
)


SEARCH_PAGE = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/schemas/soap/envelope/">
<soap:Body><SearchResponse xmlns="urn:zimbraMail" more="0">
<m id="101" cid="11" d="1788436800000" su="Synthetic review" fr="Please review">
<e t="f" a="sam@example.test"/><e t="t" a="alex@example.test"/><e t="c" a="team@example.test"/>
<mp part="1" ct="text/plain" body="1"><content>Please review the synthetic note.</content></mp>
<mp part="2" ct="application/pdf" s="42" filename="note.pdf" cd="attachment"/>
</m>
<m id="102" cid="12" d="1788350400000" su="Synthetic hello" fr="Just saying hi">
<e t="f" a="morgan@example.test"/><e t="t" a="alex@example.test"/>
</m>
</SearchResponse></soap:Body></soap:Envelope>"""

GET_MSG = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/schemas/soap/envelope/">
<soap:Body><GetMsgResponse xmlns="urn:zimbraMail">
<m id="102" cid="12" d="1788350400000" su="Synthetic hello">
<e t="f" a="morgan@example.test"/><e t="t" a="alex@example.test"/>
<mp part="1" ct="multipart/alternative">
<mp part="1.1" ct="text/plain" body="1"><content>Full synthetic body.</content></mp>
</mp>
</m>
</GetMsgResponse></soap:Body></soap:Envelope>"""

FAULT = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/schemas/soap/envelope/">
<soap:Body><soap:Fault><faultstring>no such item</faultstring>
<detail><Error xmlns="urn:zimbra"><Code>mail.NO_SUCH_ITEM</Code></Error></detail>
</soap:Fault></soap:Body></soap:Envelope>"""


class FakeTransport:
    def __init__(self) -> None:
        self.posts: list[tuple[str, bytes]] = []
        self.gets: list[str] = []

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        self.posts.append((url, body))
        text = body.decode()
        if "GetMsgRequest" in text:
            return 200, GET_MSG.encode()
        return 200, SEARCH_PAGE.encode()

    def get(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.gets.append(url)
        return 200, b"synthetic-attachment-bytes"


def _provider(tmp_path: Path, **options: object) -> ZimbraProvider:
    session = tmp_path / "work.session.json"
    session.write_text(json.dumps({"cookies": {"ZM_AUTH_TOKEN": "synthetic-zm-token"}}))
    transport = FakeTransport()
    provider = ZimbraProvider(
        "work", "mail.example.test", str(session), transport, **options  # type: ignore[arg-type]
    )
    provider.transport_fake = transport  # type: ignore[attr-defined]
    return provider


def test_search_lists_messages_with_bodies_and_attachments(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    messages = provider.list_messages()
    assert [message.id for message in messages] == ["101", "102"]
    first = messages[0]
    assert first.thread_id == "11"
    assert first.sender == "sam@example.test"
    assert first.recipients == ("alex@example.test", "team@example.test")
    assert first.sent_at == "2026-09-03T12:00:00Z"
    assert first.body_text == "Please review the synthetic note."
    assert [(item.id, item.filename) for item in first.attachments] == [("2", "note.pdf")]
    inline = messages[1]
    assert inline.body_text == "Full synthetic body."
    assert inline.attachments == ()


def test_search_does_not_mark_read_and_filters_since(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    provider.list_messages()
    posted = provider.transport_fake.posts[0][1].decode()  # type: ignore[attr-defined]
    assert 'fetch="hits"' in posted
    assert "read=" not in posted
    assert f"<query>{QUERY}</query>" in posted
    filtered = provider.list_messages(since="2026-09-03T12:00:00Z")
    assert [message.id for message in filtered] == []


def test_attachment_download_uses_content_servlet(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    data = provider.fetch_attachment_bytes("101", "2")
    assert data == b"synthetic-attachment-bytes"
    assert provider.transport_fake.gets == [  # type: ignore[attr-defined]
        "https://mail.example.test/service/home/~/?id=101&part=2"
    ]
    with pytest.raises(AttachmentNotAvailable):
        provider.fetch_attachment_bytes("101", "../escape")


def test_provider_is_read_only(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    with pytest.raises(RuntimeError, match="read-only"):
        provider.save_draft(to=["a@example.test"], subject="s", body="b")


def test_soap_fault_maps_to_code(tmp_path: Path) -> None:
    with pytest.raises(ZimbraSoapError) as caught:
        parse_response(FAULT.encode(), "GetMsgResponse")
    assert caught.value.code == "mail.NO_SUCH_ITEM"


def test_transport_refuses_plain_http_and_bad_hosts(tmp_path: Path) -> None:
    from work_assistant_zimbra.soap import UrllibTransport

    transport = UrllibTransport()
    with pytest.raises(ZimbraTransportError, match="non-HTTPS"):
        transport.post("http://mail.example.test/service/soap", b"<x/>", {})
    with pytest.raises(ZimbraError):
        SoapClient("mail.example.test/path", {"ZM_AUTH_TOKEN": "x"}, transport)


def test_session_without_token_is_rejected(tmp_path: Path) -> None:
    session = tmp_path / "empty.session.json"
    session.write_text(json.dumps({"cookies": {}}))
    with pytest.raises(ZimbraError, match="import-zimbra-har"):
        load_session_cookies(session)


def test_factory_reads_account_options(tmp_path: Path) -> None:
    session = tmp_path / "work.session.json"
    session.write_text(json.dumps({"cookies": {"ZM_AUTH_TOKEN": "synthetic-zm-token"}}))
    account = AccountConfig(
        "work",
        "zimbra",
        "alex@example.test",
        {"host": "mail.example.test", "session_file": str(session)},
    )
    assert isinstance(zimbra_provider(account), ZimbraProvider)
    missing = AccountConfig("work", "zimbra", "alex@example.test", {})
    with pytest.raises(ValueError, match="requires host"):
        zimbra_provider(missing)


def test_package_declares_provider_entry_points() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    group = tomllib.loads(pyproject.read_text())["project"]["entry-points"][
        "work_assistant.providers"
    ]
    assert set(group) == {"zimbra", "carbonio"}


def test_envelope_carries_soap_body() -> None:
    payload = build_envelope(search_request(QUERY, limit=100, offset=0))
    root = ET.fromstring(payload)
    body = root.find("{http://www.w3.org/schemas/soap/envelope/}Body")
    assert body is not None
    assert body.find("{urn:zimbraMail}SearchRequest") is not None
