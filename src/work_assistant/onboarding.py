from __future__ import annotations

from http.cookies import SimpleCookie
import json
from pathlib import Path
from typing import Any

from work_assistant.config import AppConfig


SUPPORTED_ONBOARDING = {"demo", "zimbra"}
ZIMBRA_COOKIE_NAMES = {"ZM_AUTH_TOKEN", "ZX_AUTH_TOKEN"}


def onboarding_plan(provider: str) -> dict[str, Any]:
    provider = provider.lower().strip()
    if provider == "demo":
        return {
            "provider": "demo",
            "adapter_status": "available",
            "steps": [
                {"actor": "agente", "action": "spiega che la fixture contiene messaggi sintetici"},
                {"actor": "persona", "action": "sceglie nome account e fonte JSONL locale"},
                {"actor": "cli", "action": "scrive la configurazione senza credenziali"},
                {"actor": "agente", "action": "sincronizza, elenca e controlla l'archivio"},
            ],
            "secret_policy": "non servono segreti",
        }
    if provider == "zimbra":
        return {
            "provider": "zimbra",
            "adapter_status": "onboarding_ready_adapter_not_bundled",
            "steps": [
                {"actor": "agente", "action": "raccoglie solo host, nome account e indirizzo pubblico"},
                {"actor": "persona", "action": "esegue login e 2FA nel browser"},
                {"actor": "persona", "action": "esporta il file HAR senza inserirlo in chat"},
                {"actor": "cli", "action": "estrae solo i cookie richiesti in un file locale riservato"},
                {"actor": "agente", "action": "controlla lo stato senza leggere valori segreti"},
                {"actor": "persona", "action": "installa un adapter Zimbra compatibile"},
            ],
            "secret_policy": "HAR, password, OTP e cookie restano locali e non entrano in MCP o nei prompt",
        }
    return {
        "provider": provider,
        "adapter_status": "unknown",
        "steps": [
            {"actor": "agente", "action": "identifica un adapter e il contratto di autenticazione"},
            {"actor": "persona", "action": "verifica i permessi prima di configurare segreti"},
        ],
        "secret_policy": "non inserire in chat credenziali, token o esportazioni della casella",
    }


def onboarding_status(config: AppConfig) -> dict[str, Any]:
    accounts = []
    for account in config.accounts.values():
        session_path = config.data_dir / "secrets" / f"{account.name}.session.json"
        accounts.append(
            {
                "name": account.name,
                "provider": account.provider,
                "address": account.address,
                "session_material_present": session_path.is_file(),
                "adapter_available": account.provider == "demo",
            }
        )
    return {"schema_version": 1, "accounts": accounts}


def _parse_cookie_header(value: str) -> dict[str, str]:
    cookie = SimpleCookie()
    try:
        cookie.load(value)
    except Exception:
        return {}
    return {name: morsel.value for name, morsel in cookie.items() if morsel.value}


def _entry_cookies(entry: dict[str, Any]) -> dict[str, str]:
    found: dict[str, str] = {}
    request = entry.get("request", {}) or {}
    response = entry.get("response", {}) or {}
    for item in request.get("cookies", []) or []:
        name = item.get("name")
        value = item.get("value")
        if name in ZIMBRA_COOKIE_NAMES and value:
            found[str(name)] = str(value)
    for headers in (request.get("headers", []) or [], response.get("headers", []) or []):
        for header in headers:
            if str(header.get("name", "")).lower() not in {"cookie", "set-cookie"}:
                continue
            for name, value in _parse_cookie_header(str(header.get("value", ""))).items():
                if name in ZIMBRA_COOKIE_NAMES:
                    found[name] = value
    return found


def import_zimbra_har(config: AppConfig, account_name: str, har_path: str | Path) -> dict[str, Any]:
    account = config.accounts[account_name]
    if account.provider not in {"zimbra", "carbonio"}:
        raise ValueError("HAR session import is available only for zimbra or carbonio accounts")
    source = Path(har_path).expanduser().resolve()
    raw = json.loads(source.read_text(encoding="utf-8"))
    entries = raw.get("log", {}).get("entries", []) or []
    cookies: dict[str, str] = {}
    for entry in entries:
        url = str((entry.get("request", {}) or {}).get("url", ""))
        if "/service/soap" in url:
            cookies.update(_entry_cookies(entry))
    if "ZM_AUTH_TOKEN" not in cookies:
        for entry in entries:
            cookies.update(_entry_cookies(entry))
    if "ZM_AUTH_TOKEN" not in cookies:
        raise ValueError("the HAR does not contain the required Zimbra session cookie")
    destination = config.data_dir / "secrets" / f"{account_name}.session.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": account.provider,
                "account": account_name,
                "cookies": {name: cookies.get(name, "") for name in sorted(ZIMBRA_COOKIE_NAMES)},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    destination.chmod(0o600)
    return {
        "account": account_name,
        "stored": True,
        "path": str(destination),
        "cookie_names": sorted(name for name, value in cookies.items() if value),
        "secret_values_exposed": False,
        "source_har_retained": True,
    }
