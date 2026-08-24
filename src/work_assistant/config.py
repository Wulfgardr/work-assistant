from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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
class AppConfig:
    path: Path
    data_dir: Path
    accounts: dict[str, AccountConfig]
    privacy: PrivacyConfig


def _load_privacy(raw: object, base: Path) -> PrivacyConfig:
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
    entities_path = (base / str(entities)).resolve() if entities else None
    return PrivacyConfig(mode, default, tuple(rules), entities_path)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)
    if raw.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")
    base = config_path.parent
    data_dir = (base / str(raw.get("data_dir", "./workspace"))).resolve()
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
        if "source" in options:
            options["source"] = str((base / str(options["source"])).resolve())
        accounts[name] = AccountConfig(name, provider, address, options)
    return AppConfig(config_path, data_dir, accounts, _load_privacy(raw.get("privacy"), base))
