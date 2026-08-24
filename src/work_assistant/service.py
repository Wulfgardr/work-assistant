from __future__ import annotations

from work_assistant.archive import LocalArchive
from work_assistant.config import AccountConfig, AppConfig
from work_assistant.providers import DemoProvider, MailProvider


class UnsupportedProvider(ValueError):
    pass


def provider_for(account: AccountConfig) -> MailProvider:
    if account.provider == "demo":
        source = account.options.get("source")
        if not source:
            raise ValueError(f"account {account.name!r} requires source")
        return DemoProvider(account.name, str(source))
    raise UnsupportedProvider(
        f"provider {account.provider!r} is not installed; add an adapter implementing MailProvider"
    )


class WorkAssistant:
    def __init__(self, config: AppConfig):
        self.config = config
        self.archive = LocalArchive(config.data_dir / "archive.sqlite3")

    def sync(self, account_name: str) -> dict[str, object]:
        account = self.config.accounts[account_name]
        messages = provider_for(account).list_messages()
        changed = self.archive.upsert(messages)
        return {"account": account_name, "observed": len(messages), "changed": changed}
