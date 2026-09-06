from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass
class Check:
    id: str
    ok: bool
    level: str  # "ok", "fail", "info"
    message: str
    hint: str = ""


def _secret_candidates(options: dict[str, object]) -> list[tuple[str, str]]:
    found = []
    for key in ("secret_file", "token_file", "session_file"):
        value = options.get(key)
        if value:
            found.append((key, str(value)))
    return found


def _private_file(path: Path) -> str | None:
    if not path.is_file():
        return "file non trovato"
    if os.name != "nt" and (path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077):
        return "permessi troppo ampi: usa chmod 0600"
    return None


def run_checks(config_path: str | Path) -> list[Check]:
    from work_assistant.broker import BrokerClient, default_auth_path, default_broker_address
    from work_assistant.broker import validate_broker_storage
    from work_assistant.config import ConfigError, load_config
    from work_assistant.service import available_providers, provider_for

    checks: list[Check] = []
    try:
        config = load_config(config_path)
    except (ConfigError, OSError, ValueError) as exc:
        return [Check("config", False, "fail", f"configurazione non valida: {exc}", "ricontrolla il file o riesegui setup")]
    checks.append(Check("config", True, "ok", f"configurazione valida ({len(config.accounts)} account)"))
    try:
        validate_broker_storage(config)
        checks.append(Check("data_dir", True, "ok", "cartella dati fuori dal workspace dell'agente"))
    except Exception as exc:
        checks.append(
            Check(
                "data_dir",
                False,
                "fail",
                f"cartella dati non sicura: {exc}",
                "sposta data_dir fuori dal progetto",
            )
        )
    available = set(available_providers())
    for name, account in config.accounts.items():
        if account.provider not in available:
            hint = "python -m pip install ./adapters/zimbra"
            if account.provider in {"graph", "m365"}:
                hint = "python -m pip install ./adapters/graph"
            checks.append(
                Check(f"adapter:{name}", False, "fail", f"adapter {account.provider!r} non installato", hint)
            )
            continue
        checks.append(Check(f"adapter:{name}", True, "ok", f"adapter {account.provider!r} disponibile"))
        for key, value in _secret_candidates(account.options):
            problem = _private_file(Path(value).expanduser())
            if problem is None:
                checks.append(Check(f"secret:{name}", True, "ok", f"{key} presente e protetto"))
            else:
                checks.append(
                    Check(
                        f"secret:{name}",
                        False,
                        "fail",
                        f"{key}: {problem}",
                        "crea il file in locale con permessi 0600, fuori dal progetto",
                    )
                )
        try:
            provider_for(account)
        except Exception as exc:
            checks.append(
                Check(f"options:{name}", False, "fail", f"opzioni non valide: {exc}", "riesegui setup o correggi il file")
            )
            continue
        checks.append(Check(f"options:{name}", True, "ok", "opzioni valide"))
    try:
        from work_assistant.attachments import ensure_default_extractors

        ensure_default_extractors()
        from work_assistant.attachments import describe_capabilities

        capabilities = describe_capabilities()
        names = ", ".join(item["name"] for item in capabilities["extractors"]) or "nessuno"
        ocr = "attivo" if capabilities["ocr_available"] else "non disponibile (solo testo incorporato)"
        checks.append(
            Check("attachments", True, "info", f"estrattori: {names}; OCR: {ocr}")
        )
    except Exception as exc:
        checks.append(Check("attachments", False, "fail", f"pipeline allegati guasta: {exc}", ""))
    try:
        status = BrokerClient(
            default_broker_address(config), default_auth_path(config), timeout=1
        ).call("privacy_status")
        checks.append(
            Check("broker", True, "ok", f"broker attivo (modalità {status.get('mode')})")
        )
    except Exception:
        checks.append(
            Check(
                "broker",
                True,
                "info",
                "broker non attivo (serve solo per usare un agente)",
                f"avvialo con: work-assistant --config {config.path} broker",
            )
        )
    return checks


def format_human(checks: list[Check]) -> str:
    # ASCII-only marks: Windows consoles without UTF-8 must render this too.
    marks = {"ok": "[ok]", "fail": "[FAIL]", "info": "[info]"}
    lines = []
    for check in checks:
        lines.append(f"{marks.get(check.level, '[?]')} {check.message}")
        if not check.ok and check.hint:
            lines.append(f"    -> {check.hint}")
    return "\n".join(lines) + "\n"


def run_doctor(config_path: str | Path, *, as_json: bool = False) -> int:
    import json

    checks = run_checks(config_path)
    if as_json:
        print(
            json.dumps(
                {
                    "ok": all(check.level != "fail" for check in checks),
                    "checks": [
                        {"id": c.id, "level": c.level, "message": c.message, "hint": c.hint}
                        for c in checks
                    ],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(format_human(checks), end="")
    return 0 if all(check.level != "fail" for check in checks) else 1
