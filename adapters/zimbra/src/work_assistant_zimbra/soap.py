from __future__ import annotations

import json
from pathlib import Path
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET


SOAP_NS = "http://www.w3.org/schemas/soap/envelope/"
ZIMBRA_NS = "urn:zimbra"
MAIL_NS = "urn:zimbraMail"
USER_AGENT = "work-assistant-zimbra/0.1.0"


class ZimbraError(RuntimeError):
    pass


class ZimbraTransportError(ZimbraError):
    pass


class ZimbraSoapError(ZimbraError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.detail = message


class ZimbraAuthError(ZimbraError):
    pass


AUTH_FAULTS = {"AUTH_EXPIRED", "AUTH_REQUIRED", "NO_SUCH_AUTH_TOKEN"}


def load_session_cookies(session_file: str | Path) -> dict[str, str]:
    """Read the local session file written by `import-zimbra-har`.

    Only cookie names and values are read; the HAR itself is never required.
    """
    import os

    path = Path(session_file).expanduser()
    if path.is_symlink():
        raise ZimbraError("session file must be a regular file")
    if os.name != "nt" and path.is_file():
        try:
            stat = path.stat()
            if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
                raise ZimbraError("session file must be owner-only (0600)")
        except OSError as exc:
            raise ZimbraError(f"session file is unreadable: {exc}") from exc
    raw = json.loads(path.read_text(encoding="utf-8"))
    cookies = raw.get("cookies", {}) if isinstance(raw, dict) else {}
    selected = {
        name: str(value)
        for name, value in cookies.items()
        if name in {"ZM_AUTH_TOKEN", "ZX_AUTH_TOKEN"} and str(value)
    }
    if not selected.get("ZM_AUTH_TOKEN"):
        raise ZimbraError(
            "session file has no ZM_AUTH_TOKEN; run `work-assistant import-zimbra-har` first"
        )
    return selected


def _qualified(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


def build_envelope(request: ET.Element) -> bytes:
    envelope = ET.Element(_qualified(SOAP_NS, "Envelope"), {"xmlns:soap": SOAP_NS})
    header = ET.SubElement(envelope, _qualified(SOAP_NS, "Header"))
    context = ET.SubElement(header, "context", {"xmlns": ZIMBRA_NS})
    ET.SubElement(context, "userAgent", {"name": USER_AGENT})
    body = ET.SubElement(envelope, _qualified(SOAP_NS, "Body"))
    body.append(request)
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)


def search_request(query: str, *, limit: int, offset: int) -> ET.Element:
    element = ET.Element(
        "SearchRequest",
        {
            "xmlns": MAIL_NS,
            "types": "message",
            "sortBy": "dateDesc",
            "limit": str(limit),
            "offset": str(offset),
            "fetch": "hits",
        },
    )
    query_element = ET.SubElement(element, "query")
    query_element.text = query
    return element


def get_msg_request(message_id: str) -> ET.Element:
    element = ET.Element("GetMsgRequest", {"xmlns": MAIL_NS})
    ET.SubElement(element, "m", {"id": message_id})
    return element


def save_draft_request(to: list[str], subject: str, body: str) -> ET.Element:
    element = ET.Element("SaveDraftRequest", {"xmlns": MAIL_NS})
    message = ET.SubElement(element, "m")
    for address in to:
        ET.SubElement(message, "e", {"t": "t", "a": address})
    subject_element = ET.SubElement(message, "su")
    subject_element.text = subject
    part = ET.SubElement(message, "mp", {"ct": "text/plain"})
    content = ET.SubElement(part, "content")
    content.text = body
    return element


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_response(payload: bytes, response_tag: str) -> ET.Element:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ZimbraTransportError(f"invalid XML response: {exc}") from exc
    fault = root.find(f".//{_qualified(SOAP_NS, 'Fault')}")
    if fault is not None:
        code = "unknown"
        for element in fault.iter():
            if _local(element.tag) == "Code" and element.text:
                code = element.text.strip()
                break
        reason = fault.findtext("faultstring") or "SOAP fault"
        if code.split(".")[-1] in AUTH_FAULTS:
            raise ZimbraAuthError(
                "session expired or missing; re-run `work-assistant import-zimbra-har` "
                f"to refresh it ({code})"
            )
        raise ZimbraSoapError(code, reason.strip())
    for element in root.iter():
        if _local(element.tag) == response_tag:
            return element
    raise ZimbraTransportError(f"missing {response_tag} in response")


class UrllibTransport:
    """Default HTTPS transport. Plain HTTP hosts are refused."""

    def __init__(self, *, cafile: str | None = None, timeout: float = 30):
        context = ssl.create_default_context(cafile=cafile)
        self._context = context
        self._timeout = timeout

    def _open(self, url: str, data: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
        if not url.startswith("https://"):
            raise ZimbraTransportError("refusing non-HTTPS endpoint")
        request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout, context=self._context) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:
            raise ZimbraTransportError(f"HTTP {exc.code} from provider") from exc
        except OSError as exc:
            raise ZimbraTransportError(f"provider is unreachable: {exc}") from exc

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
        return self._open(url, body, headers)

    def get(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return self._open(url, None, headers)


class SoapClient:
    """Minimal Zimbra/Carbonio SOAP client over an injectable transport."""

    def __init__(
        self,
        host: str,
        cookies: dict[str, str],
        transport: UrllibTransport | None = None,
        *,
        timeout: float = 30,
    ):
        host = host.strip().lower()
        if not host or "/" in host or " " in host:
            raise ZimbraError("host must be a bare hostname")
        self.base = f"https://{host}"
        self.cookies = cookies
        self.transport = transport or UrllibTransport(timeout=timeout)

    @property
    def _headers(self) -> dict[str, str]:
        cookie = "; ".join(f"{name}={value}" for name, value in sorted(self.cookies.items()))
        return {"Content-Type": "text/xml; charset=utf-8", "Cookie": cookie}

    def call(self, request: ET.Element, response_tag: str) -> ET.Element:
        status, payload = self.transport.post(
            f"{self.base}/service/soap", build_envelope(request), self._headers
        )
        if status != 200:
            raise ZimbraTransportError(f"HTTP {status} from provider")
        return parse_response(payload, response_tag)

    def download(self, path: str) -> bytes:
        status, payload = self.transport.get(f"{self.base}{path}", self._headers)
        if status == 404:
            raise ZimbraTransportError("provider reports no such item")
        if status != 200:
            raise ZimbraTransportError(f"HTTP {status} from provider")
        return payload
