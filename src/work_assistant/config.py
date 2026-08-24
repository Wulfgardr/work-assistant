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
class AppConfig:
    path: Path
    data_dir: Path
    accounts: dict[str, AccountConfig]


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
    return AppConfig(config_path, data_dir, accounts)
