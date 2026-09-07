from __future__ import annotations

import json
import os
from pathlib import Path
import time
import urllib.parse
import urllib.request


SCOPES = ("Mail.Read", "offline_access")
LOGIN_HOST = "https://login.microsoftonline.com"


class GraphAuthError(RuntimeError):
    pass


def _check_tenant(tenant: str) -> str:
    tenant = tenant.strip()
    if not tenant or "/" in tenant or " " in tenant or tenant.startswith("."):
        raise GraphAuthError("tenant must be a bare directory id, domain, or one of common/organizations")
    return tenant


class FormTransport:
    """Default HTTPS form transport. Plain HTTP is refused."""

    def __init__(self, timeout: float = 30):
        self.timeout = timeout

    def post_form(self, url: str, fields: dict[str, str]) -> dict:
        if not url.startswith("https://"):
            raise GraphAuthError("refusing non-HTTPS endpoint")
        body = urllib.parse.urlencode(fields).encode()
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode())
        except OSError as exc:
            raise GraphAuthError(f"identity endpoint is unreachable: {exc}") from exc


class TokenStore:
    """Local OAuth token cache. Never printed, never committed."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def load(self) -> dict:
        if not self.path.is_file():
            return {}
        if self.path.is_symlink():
            raise GraphAuthError("token cache must be a regular file")
        if os.name != "nt":
            try:
                stat = self.path.stat()
                if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
                    raise GraphAuthError("token cache must be owner-only (0600)")
            except OSError as exc:
                raise GraphAuthError(f"token cache is unreadable: {exc}") from exc
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GraphAuthError(f"token cache is unreadable: {exc}") from exc
        return raw if isinstance(raw, dict) else {}

    def save(self, tokens: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(tokens, indent=2) + "\n").encode()
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(tmp, self.path)
        if os.name != "nt":
            os.chmod(self.path, 0o600)


class DeviceFlow:
    """OAuth2 device code flow for public clients (delegated Mail.Read only).

    No client secret is ever needed or stored. The `device_code` is used
    locally for polling and never printed; only the server-provided user
    message (code + verification URI) is shown to the person.
    """

    def __init__(
        self,
        client_id: str,
        token_file: str | Path,
        *,
        tenant: str = "common",
        transport: FormTransport | None = None,
        timeout: float = 30,
    ):
        client_id = client_id.strip()
        if not client_id:
            raise GraphAuthError("client_id is required; register an app with Mail.Read delegated")
        self.client_id = client_id
        self.tenant = _check_tenant(tenant)
        self.store = TokenStore(token_file)
        self.transport = transport or FormTransport(timeout=timeout)

    @property
    def _base(self) -> str:
        return f"{LOGIN_HOST}/{self.tenant}/oauth2/v2.0"

    def _scope(self) -> str:
        return " ".join(SCOPES)

    def login(self) -> dict[str, object]:
        challenge = self.transport.post_form(
            f"{self._base}/devicecode",
            {"client_id": self.client_id, "scope": self._scope()},
        )
        for key in ("user_code", "verification_uri", "device_code"):
            if not challenge.get(key):
                raise GraphAuthError("identity endpoint returned an invalid device challenge")
        print(challenge.get("message") or (
            f"To sign in, open {challenge['verification_uri']} "
            f"and enter code {challenge['user_code']}"
        ))
        interval = max(1, int(challenge.get("interval", 5)))
        deadline = time.monotonic() + max(60, int(challenge.get("expires_in", 900)))
        device_code = str(challenge["device_code"])
        while time.monotonic() < deadline:
            time.sleep(interval)
            result = self.transport.post_form(
                f"{self._base}/token",
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": self.client_id,
                    "device_code": device_code,
                },
            )
            error = str(result.get("error") or "")
            if error in {"authorization_pending"}:
                continue
            if error == "slow_down":
                interval += 5
                continue
            if error:
                raise GraphAuthError(f"device authorization failed: {error}")
            tokens = self._with_expiry(result)
            self.store.save(tokens)
            return {"stored": True, "path": str(self.store.path), "secret_values_exposed": False}
        raise GraphAuthError("device authorization expired before approval")

    @staticmethod
    def _with_expiry(result: dict) -> dict:
        try:
            lifetime = int(result.get("expires_in", 3600))
        except (TypeError, ValueError):
            lifetime = 3600
        return {**result, "expires_at": int(time.time()) + max(60, lifetime)}

    def refresh(self) -> dict:
        cached = self.store.load()
        refresh_token = str(cached.get("refresh_token") or "")
        if not refresh_token:
            raise GraphAuthError("no refresh token; run work-assistant-graph-login first")
        result = self.transport.post_form(
            f"{self._base}/token",
            {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": refresh_token,
                "scope": self._scope(),
            },
        )
        if result.get("error"):
            raise GraphAuthError(f"token refresh failed: {result['error']}")
        merged = {**cached, **self._with_expiry(result)}
        if not merged.get("refresh_token"):
            merged["refresh_token"] = refresh_token
        self.store.save(merged)
        return merged

    def access_token(self) -> str:
        cached = self.store.load()
        token = str(cached.get("access_token") or "")
        try:
            expires_at = int(cached.get("expires_at", 0))
        except (TypeError, ValueError):
            expires_at = 0
        if token and expires_at - time.time() > 60:
            return token
        return str(self.refresh().get("access_token") or "")
