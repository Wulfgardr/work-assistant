from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
import tomllib


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AccountConfig:
    name: str
    provider: str
    address: str
    options: dict[str, object]


@dataclass(frozen=True)
class SenderRule:
    pattern: str
    action: str


@dataclass(frozen=True)
class PrivacyConfig:
    mode: str
    default_action: str
    sender_rules: tuple[SenderRule, ...]
    entities_path: Path | None


@dataclass(frozen=True)
class AttachmentConfig:
    enabled: bool
    max_text_chars: int
    max_bytes: int
    ocr_mode: str
    ocr_languages: str
    ocr_max_pages: int


@dataclass(frozen=True)
class AppConfig:
    path: Path
    data_dir: Path
    accounts: dict[str, AccountConfig]
    privacy: PrivacyConfig
    unsafe_allow_workspace_data: bool
    attachments: AttachmentConfig


def default_data_dir() -> Path:
    """Return the per-user application data directory for this platform."""
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "WorkAssistant"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "WorkAssistant"
    root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "work-assistant"


def _load_privacy(raw: object, base: Path, data_dir: Path) -> PrivacyConfig:
    item = raw if isinstance(raw, dict) else {}
    mode = str(item.get("mode", "off")).strip().lower()
    if mode not in {"off", "all", "selective"}:
        raise ConfigError("privacy.mode must be off, all or selective")
    if mode == "selective" and "default_action" not in item:
        raise ConfigError("privacy.default_action is required in selective mode")
    default = str(item.get("default_action", "pseudonymize")).strip().lower()
    if default not in {"pseudonymize", "allow_raw"}:
        raise ConfigError("privacy.default_action must be pseudonymize or allow_raw")
    rules: list[SenderRule] = []
    for index, rule in enumerate(item.get("sender_rules", []) or []):
        if not isinstance(rule, dict):
            raise ConfigError(f"privacy.sender_rules[{index}] must be a table")
        pattern = str(rule.get("pattern", "")).strip()
        action = str(rule.get("action", "")).strip().lower()
        if not pattern or action not in {"pseudonymize", "allow_raw"}:
            raise ConfigError(f"privacy.sender_rules[{index}] requires pattern and a valid action")
        rules.append(SenderRule(pattern, action))
    entities = item.get("entities_path")
    entities_path = (base / str(entities)).resolve() if entities else data_dir / "privacy" / "entities.json"
    return PrivacyConfig(mode, default, tuple(rules), entities_path)


def _load_attachments(raw: object) -> AttachmentConfig:
    item = raw if isinstance(raw, dict) else {}
    enabled = bool(item.get("enabled", True))
    try:
        max_chars = int(item.get("max_text_chars", 20000))
        max_bytes = int(item.get("max_bytes", 32 * 1024 * 1024))
        max_pages = int(item.get("ocr_max_pages", 10))
    except (TypeError, ValueError) as exc:
        raise ConfigError("attachments limits must be integers") from exc
    if max_chars < 1 or max_bytes < 1024 or max_pages < 1:
        raise ConfigError("attachments limits are too small")
    ocr_mode = str(item.get("ocr_mode", "auto")).strip().lower()
    if ocr_mode not in {"auto", "off"}:
        raise ConfigError('attachments.ocr_mode must be "auto" or "off"')
    ocr_languages = str(item.get("ocr_languages", "auto")).strip()
    if not ocr_languages:
        raise ConfigError("attachments.ocr_languages must not be empty")
    return AttachmentConfig(enabled, max_chars, max_bytes, ocr_mode, ocr_languages, max_pages)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    if raw.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")
    base = config_path.parent
    configured_data_dir = raw.get("data_dir")
    data_dir = (
        (base / str(configured_data_dir)).expanduser().resolve()
        if configured_data_dir
        else default_data_dir().expanduser().resolve()
    )
    raw_accounts = raw.get("accounts")
    if not isinstance(raw_accounts, dict) or not raw_accounts:
        raise ConfigError("at least one account is required")
    accounts: dict[str, AccountConfig] = {}
    for name, item in raw_accounts.items():
        if not isinstance(item, dict):
            raise ConfigError(f"account {name!r} must be a table")
        provider = str(item.get("provider", "")).strip()
        address = str(item.get("address", "")).strip()
        if not provider or not address:
            raise ConfigError(f"account {name!r} requires provider and address")
        options = {k: v for k, v in item.items() if k not in {"provider", "address"}}
        for location_key in ("source", "path"):
            if location_key in options:
                options[location_key] = str((base / str(options[location_key])).resolve())
        accounts[name] = AccountConfig(name, provider, address, options)
    return AppConfig(
        config_path,
        data_dir,
        accounts,
        _load_privacy(raw.get("privacy"), base, data_dir),
        bool(raw.get("unsafe_allow_workspace_data", False)),
        _load_attachments(raw.get("attachments")),
    )
