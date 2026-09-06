from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from work_assistant_graph.auth import DeviceFlow, GraphAuthError


GRAPH_BASE = "https://graph.microsoft.com"


class GraphError(RuntimeError):
    pass


class JsonTransport:
    """Default HTTPS JSON transport. Plain HTTP is refused."""

    def __init__(self, timeout: float = 30):
        self.timeout = timeout

    def request(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None = None
    ) -> tuple[int, bytes]:
        if not url.startswith("https://"):
            raise GraphError("refusing non-HTTPS endpoint")
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            return int(exc.code), exc.read()
        except OSError as exc:
            raise GraphError(f"graph endpoint is unreachable: {exc}") from exc


class GraphClient:
    """Minimal Microsoft Graph client with one transparent 401 retry."""

    def __init__(
        self,
        auth: DeviceFlow,
        transport: JsonTransport | None = None,
        *,
        max_pages: int = 10,
    ):
        self.auth = auth
        self.transport = transport or JsonTransport()
        self.max_pages = max(1, max_pages)

    def _get(self, url: str, token: str) -> tuple[int, dict]:
        status, payload = self.transport.request(
            "GET", url, {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )
        try:
            return status, json.loads(payload.decode() or "{}")
        except ValueError as exc:
            raise GraphError(f"invalid graph response: {exc}") from exc

    def get(self, path: str, params: dict[str, str] | None = None) -> dict:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{GRAPH_BASE}{path}{query}"
        status, body = self._get(url, self.auth.access_token())
        if status == 401:
            try:
                refreshed = self.auth.refresh()
            except GraphAuthError as exc:
                raise GraphError(f"graph authentication failed: {exc}") from exc
            status, body = self._get(url, str(refreshed.get("access_token") or ""))
        if status == 429:
            raise GraphError("graph throttled the request; retry later")
        if status != 200:
            code = str(body.get("error", {}).get("code") or f"HTTP {status}")
            raise GraphError(f"graph request failed: {code}")
        return body

    def get_url(self, url: str) -> dict:
        status, body = self._get(url, self.auth.access_token())
        if status != 200:
            raise GraphError(f"graph request failed: HTTP {status}")
        return body

    def list_paged(self, path: str, params: dict[str, str]) -> list[dict]:
        items: list[dict] = []
        body = self.get(path, params)
        pages = 0
        while True:
            items.extend(item for item in body.get("value", []) if isinstance(item, dict))
            link = body.get("@odata.nextLink")
            pages += 1
            if not link or pages >= self.max_pages:
                break
            body = self.get_url(str(link))
        return items
