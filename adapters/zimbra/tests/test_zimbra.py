import json
import io
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
    normalize_query_dates,
    UrllibTransport,
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

SAVE_DRAFT = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://www.w3.org/schemas/soap/envelope/">
<soap:Body><SaveDraftResponse xmlns="urn:zimbraMail"><m id="301"/></SaveDraftResponse></soap:Body></soap:Envelope>"""


class FakeTransport:
    def __init__(self) -> None:
        self.posts: list[tuple[str, bytes]] = []
        self.gets: list[str] = []
        self.draft: ET.Element | None = None

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        self.posts.append((url, body))
        text = body.decode()
        if "GetFolderRequest" in text:
            return 200, b'<GetFolderResponse xmlns="urn:zimbraMail"><folder id="6" name="Drafts"/></GetFolderResponse>'
        if "GetMsgRequest" in text:
            if 'id="301"' in text and self.draft is not None:
                response = ET.Element("GetMsgResponse", {"xmlns": "urn:zimbraMail"})
                response.append(self.draft)
                return 200, ET.tostring(response)
            return 200, GET_MSG.encode()
        if "SaveDraftRequest" in text:
            self.draft = next(e for e in ET.fromstring(body).iter() if e.tag == "{urn:zimbraMail}m")
            self.draft.attrib.update(id="301", l="6", f="d")
            return 200, SAVE_DRAFT.encode()
        return 200, SEARCH_PAGE.encode()

    def get(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        self.gets.append(url)
        return 200, b"synthetic-attachment-bytes"


def _provider(tmp_path: Path, **options: object) -> ZimbraProvider:
    import os

    session = tmp_path / "work.session.json"
    session.write_text(json.dumps({"cookies": {"ZM_AUTH_TOKEN": "synthetic-zm-token"}}))
    if os.name != "nt":
        os.chmod(session, 0o600)
    transport = FakeTransport()
    provider = ZimbraProvider(
        "work", "mail.example.test", str(session), transport, **options  # type: ignore[arg-type]
    )
    provider.transport_fake = transport  # type: ignore[attr-defined]
    return provider


@pytest.mark.parametrize("more", ["0", "false"])
def test_search_lists_messages_with_bodies_and_attachments(tmp_path: Path, more: str) -> None:
    provider = _provider(tmp_path)
    original = provider.client.transport.post
    def post(*args):
        status, payload = original(*args)
        return status, payload.replace(b'more="0"', f'more="{more}"'.encode())
    provider.client.transport.post = post
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


def test_provider_is_read_only_for_sending(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    with pytest.raises(ZimbraError, match="reply drafts are not supported"):
        provider.save_draft(to=["a@example.test"], subject="s", body="b", in_reply_to="101")


def test_save_draft_returns_server_receipt(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    assert provider.save_draft(to=["sam@example.test"], subject="Synthetic", body="Hi.") == "301"
    posted = provider.transport_fake.posts[-2][1].decode()  # type: ignore[attr-defined]
    assert "SaveDraftRequest" in posted and "sam@example.test" in posted
    with pytest.raises(ZimbraError, match="recipients"):
        provider.save_draft(to=[], subject="s", body="b")


def test_soap_fault_maps_to_code(tmp_path: Path) -> None:
    with pytest.raises(ZimbraSoapError) as caught:
        parse_response(FAULT.encode(), "GetMsgResponse")
    assert caught.value.code == "mail.NO_SUCH_ITEM"


def test_expired_session_points_to_har_import(tmp_path: Path) -> None:
    from work_assistant_zimbra.soap import ZimbraAuthError

    expired = FAULT.replace("mail.NO_SUCH_ITEM", "service.AUTH_EXPIRED")
    with pytest.raises(ZimbraAuthError, match="import-zimbra-har"):
        parse_response(expired.encode(), "GetMsgResponse")


def test_transport_refuses_plain_http_and_bad_hosts(tmp_path: Path) -> None:
    from work_assistant_zimbra.soap import UrllibTransport

    transport = UrllibTransport()
    with pytest.raises(ZimbraTransportError, match="non-HTTPS"):
        transport.post("http://mail.example.test/service/soap", b"<x/>", {})
    with pytest.raises(ZimbraError):
        SoapClient("mail.example.test/path", {"ZM_AUTH_TOKEN": "x"}, transport)


def test_session_without_token_is_rejected(tmp_path: Path) -> None:
    import os

    session = tmp_path / "empty.session.json"
    session.write_text(json.dumps({"cookies": {}}))
    if os.name != "nt":
        os.chmod(session, 0o600)
    with pytest.raises(ZimbraError, match="import-zimbra-har"):
        load_session_cookies(session)


def test_session_with_broad_permissions_is_rejected(tmp_path: Path) -> None:
    import os

    if os.name == "nt":
        pytest.skip("POSIX-only permission check")
    session = tmp_path / "broad.session.json"
    session.write_text(json.dumps({"cookies": {"ZM_AUTH_TOKEN": "synthetic-zm-token"}}))
    os.chmod(session, 0o644)
    with pytest.raises(ZimbraError, match="owner-only"):
        load_session_cookies(session)


def test_factory_reads_account_options(tmp_path: Path) -> None:
    import os

    session = tmp_path / "work.session.json"
    session.write_text(json.dumps({"cookies": {"ZM_AUTH_TOKEN": "synthetic-zm-token"}}))
    if os.name != "nt":
        os.chmod(session, 0o600)
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


@pytest.mark.parametrize("query,expected", [
    ("after:2026-10-12 before:2026/11/01", "after:10/12/2026 before:11/01/2026"),
    ('(after:"2026-10-12")', '(after:"10/12/2026")'),
    ('"after:2026-10-12" after:-1day', '"after:2026-10-12" after:-1day'),
])
def test_search_dates_use_explicit_locale(query, expected):
    request = search_request(query, limit=100, offset=0)
    assert request.findtext("query") == expected
    assert request.findtext("locale") == "en_US"


@pytest.mark.parametrize("query", ["after:2026-02-30", "before:2026/13/1", "after:2026"])
def test_invalid_absolute_dates_fail_before_transport(query):
    with pytest.raises(ZimbraError, match="absolute search date"):
        normalize_query_dates(query)


def test_since_compares_instants_and_includes_date_only(tmp_path):
    provider = _provider(tmp_path)
    assert [m.id for m in provider.list_messages(since="2026-09-03T14:00:00+02:00")] == []
    assert [m.id for m in provider.list_messages(since="2026-09-03")] == ["101"]
    with pytest.raises(ZimbraError, match="timezone"):
        provider.list_messages(since="2026-09-03T12:00:00")


def test_since_finishes_at_cutoff_even_when_older_pages_remain(tmp_path):
    provider = _provider(tmp_path, search_pages=1)
    provider.client.transport.post = lambda *args: (200, SEARCH_PAGE.replace('more="0"', 'more="1"').encode())
    assert [m.id for m in provider.list_messages(since="2026-09-03")] == ["101"]


@pytest.mark.parametrize("duplicate", [False, True])
def test_incomplete_pagination_never_returns_partial_mailbox(tmp_path, duplicate):
    provider = _provider(tmp_path, search_pages=2)
    payload = SEARCH_PAGE.replace('more="0"', 'more="1"').encode()
    calls = 0
    def post(url, body, headers):
        nonlocal calls
        if b"GetMsgRequest" in body:
            identifier = next(e for e in ET.fromstring(body).iter() if e.tag == "{urn:zimbraMail}m").get("id")
            return 200, GET_MSG.replace('id="102"', f'id="{identifier}"').encode()
        calls += 1
        if calls == 2 and not duplicate:
            return 200, payload.replace(b'id="101"', b'id="201"').replace(b'id="102"', b'id="202"')
        return 200, payload
    provider.client.transport.post = post
    with pytest.raises(ZimbraError, match="duplicated" if duplicate else "page limit"):
        provider.list_messages()
    assert calls == 2


def test_expired_session_on_full_message_stops_sync(tmp_path):
    from work_assistant_zimbra.soap import ZimbraAuthError
    provider = _provider(tmp_path)
    original = provider.client.transport.post
    def post(url, body, headers):
        if b"GetMsgRequest" in body:
            return 200, FAULT.replace("mail.NO_SUCH_ITEM", "service.AUTH_EXPIRED").encode()
        return original(url, body, headers)
    provider.client.transport.post = post
    with pytest.raises(ZimbraAuthError):
        provider.list_messages()


@pytest.mark.parametrize("field,value", [("id", "999"), ("l", "7"), ("f", "")])
def test_draft_readback_failure_does_not_repeat_save(tmp_path, field, value):
    provider = _provider(tmp_path)
    original = provider.client.transport.post
    def post(url, body, headers):
        if b"GetMsgRequest" in body:
            provider.client.transport.draft.set(field, value)
        return original(url, body, headers)
    provider.client.transport.post = post
    with pytest.raises(ZimbraError, match="do not repeat"):
        provider.save_draft(to=["sam@example.test"], subject="Synthetic", body="Hi.")
    assert sum(b"SaveDraftRequest" in body for _, body in provider.transport_fake.posts) == 1
    assert b'read="0"' in provider.transport_fake.posts[-1][1]


def test_transport_caps_response_before_parsing_and_closes_it(monkeypatch):
    from contextlib import contextmanager
    response = io.BytesIO(b"x" * 20)
    response.status = 200
    @contextmanager
    def opened(*args, **kwargs):
        with response:
            yield response
    monkeypatch.setattr("urllib.request.urlopen", opened)
    with pytest.raises(ZimbraTransportError, match="byte limit"):
        UrllibTransport(max_response_bytes=10).post("https://mail.example.test", b"<x/>", {})
    assert response.closed


def test_injected_transport_cannot_bypass_soap_limit(monkeypatch):
    import work_assistant_zimbra.soap as soap
    monkeypatch.setattr(soap, "MAX_RESPONSE_BYTES", 10)
    with pytest.raises(ZimbraTransportError, match="SOAP response"):
        SoapClient("mail.example.test", {}, FakeTransport()).call(search_request(QUERY, limit=1, offset=0), "SearchResponse")
