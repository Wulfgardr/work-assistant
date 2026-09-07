from __future__ import annotations

import json
import time
from collections.abc import Callable
import urllib.error
import urllib.parse
import urllib.request

from work_assistant_graph.auth import DeviceFlow, GraphAuthError


GRAPH_BASE = "https://graph.microsoft.com"
MAX_THROTTLE_RETRIES = 2
MAX_THROTTLE_WAIT = 60.0


class GraphError(RuntimeError):
    pass


class JsonTransport:
    """Default HTTPS JSON transport. Plain HTTP is refused."""

    def __init__(self, timeout: float = 30):
        self.timeout = timeout

    def request(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None = None
    ) -> tuple[int, dict[str, str], bytes]:
        if not url.startswith("https://"):
            raise GraphError("refusing non-HTTPS endpoint")
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return int(response.status), dict(response.headers.items()), response.read()
        except urllib.error.HTTPError as exc:
            return int(exc.code), dict(exc.headers.items()), exc.read()
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
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.auth = auth
        self.transport = transport or JsonTransport()
        self.max_pages = max(1, max_pages)
        self.sleeper = sleeper

    def _send(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None = None
    ) -> tuple[int, bytes]:
        attempts = 0
        while True:
            status, response_headers, raw = self.transport.request(method, url, headers, body)
            if status in {429, 503} and attempts < MAX_THROTTLE_RETRIES:
                try:
                    wait = float(response_headers.get("Retry-After", "1"))
                except ValueError:
                    wait = 1.0
                self.sleeper(max(0.0, min(MAX_THROTTLE_WAIT, wait)))
                attempts += 1
                continue
            if status == 429:
                raise GraphError("graph throttled the request; retry later")
            return status, raw

    def _get(self, url: str, token: str) -> tuple[int, dict]:
        status, payload = self._send(
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
        if status != 200:
            code = str(body.get("error", {}).get("code") or f"HTTP {status}")
            raise GraphError(f"graph request failed: {code}")
        return body

    def _mutate(self, method: str, path: str, payload: dict) -> dict:
        url = f"{GRAPH_BASE}{path}"
        body = json.dumps(payload).encode()
        token = self.auth.access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        status, raw = self._send(method, url, headers, body)
        if status == 401:
            try:
                refreshed = self.auth.refresh()
            except GraphAuthError as exc:
                raise GraphError(f"graph authentication failed: {exc}") from exc
            headers = {
                "Authorization": f"Bearer {refreshed.get('access_token')}",
                "Content-Type": "application/json",
            }
            status, raw = self._send(method, url, headers, body)
        try:
            parsed = json.loads(raw.decode() or "{}")
        except ValueError as exc:
            raise GraphError(f"invalid graph response: {exc}") from exc
        if status not in {200, 201}:
            code = str(parsed.get("error", {}).get("code") or f"HTTP {status}")
            raise GraphError(f"graph request failed: {code}")
        return parsed

    def post(self, path: str, payload: dict) -> dict:
        return self._mutate("POST", path, payload)

    def patch(self, path: str, payload: dict) -> dict:
        return self._mutate("PATCH", path, payload)

    def get_url(self, url: str) -> dict:
        # SSRF guard: nextLink is server-controlled; only follow same-host Graph URLs
        # and never send the Bearer token to another host.
        base_host = urllib.parse.urlparse(GRAPH_BASE).netloc.lower()
        try:
            host = (urllib.parse.urlparse(url).netloc or "").lower()
        except ValueError as exc:
            raise GraphError(f"invalid graph next link: {exc}") from exc
        if host != base_host or not url.startswith("https://"):
            raise GraphError("refusing to follow a graph next link off the Graph host")
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
