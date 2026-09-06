from __future__ import annotations

from importlib import metadata
import hashlib
from typing import Callable

from work_assistant.archive import LocalArchive
from work_assistant.attachments import (
    AttachmentNotAvailable,
    OcrConfig,
    PipelineLimits,
    STATUSES,
    describe_capabilities,
    ensure_default_extractors,
    extract_attachment_text,
)
from work_assistant.config import AccountConfig, AppConfig
from work_assistant.providers import DemoProvider, ImapProvider, MailProvider, MaildirProvider


class UnsupportedProvider(ValueError):
    pass


PROVIDER_ENTRY_POINT_GROUP = "work_assistant.providers"


def _builtin_factories() -> dict[str, Callable[[AccountConfig], MailProvider]]:
    return {
        "demo": lambda account: DemoProvider(
            account.name,
            str(account.options.get("source") or ""),
            attachments_dir=(
                str(account.options["attachments_dir"])
                if account.options.get("attachments_dir")
                else None
            ),
        ),
        "maildir": lambda account: MaildirProvider(
            account.name, str(account.options.get("path") or "")
        ),
        "imap": lambda account: ImapProvider(
            account.name,
            str(account.options.get("host") or ""),
            str(account.options.get("secret_file") or ""),
            username=str(account.options.get("username") or account.address),
            port=int(account.options.get("port", 993)),
            folder=str(account.options.get("folder", "INBOX")),
        ),
    }


def _entry_point_factories() -> dict[str, Callable[[AccountConfig], MailProvider]]:
    """Discover third-party adapters without importing them eagerly."""
    try:
        entry_points = metadata.entry_points(group=PROVIDER_ENTRY_POINT_GROUP)
    except TypeError:
        entry_points = metadata.entry_points().get(PROVIDER_ENTRY_POINT_GROUP, [])
    factories: dict[str, Callable[[AccountConfig], MailProvider]] = {}
    for entry_point in entry_points:
        factories[str(entry_point.name)] = entry_point.load()
    return factories


def available_providers() -> list[str]:
    names = set(_builtin_factories())
    try:
        names.update(_entry_point_factories())
    except Exception:
        pass
    return sorted(names)


def provider_for(account: AccountConfig) -> MailProvider:
    factories = _builtin_factories()
    factory = factories.get(account.provider)
    if factory is None:
        try:
            factory = _entry_point_factories().get(account.provider)
        except Exception as exc:
            raise UnsupportedProvider(
                f"provider {account.provider!r} could not be loaded: {exc}"
            ) from exc
    if factory is None:
        raise UnsupportedProvider(
            f"provider {account.provider!r} is not installed; add an adapter implementing"
            f" MailProvider and register it under the {PROVIDER_ENTRY_POINT_GROUP!r} entry point group"
        )
    if account.provider == "demo" and not account.options.get("source"):
        raise ValueError(f"account {account.name!r} requires source")
    if account.provider == "maildir" and not account.options.get("path"):
        raise ValueError(f"account {account.name!r} requires path")
    if account.provider == "imap" and (
        not account.options.get("host") or not account.options.get("secret_file")
    ):
        raise ValueError(f"account {account.name!r} requires host and secret_file")
    try:
        return factory(account)
    except UnsupportedProvider:
        raise
    except Exception as exc:
        raise UnsupportedProvider(
            f"provider {account.provider!r} failed to initialize: {exc}"
        ) from exc


class WorkAssistant:
    def __init__(self, config: AppConfig):
        self.config = config
        self.archive = LocalArchive(config.data_dir / "archive.sqlite3")

    def _attachment_pipeline(self) -> tuple[PipelineLimits, str]:
        attachments = self.config.attachments
        ensure_default_extractors(
            OcrConfig(mode=attachments.ocr_mode, languages=attachments.ocr_languages)
        )
        return (
            PipelineLimits(
                max_bytes=attachments.max_bytes,
                max_chars=attachments.max_text_chars,
                max_pages=attachments.ocr_max_pages,
            ),
            attachments.ocr_mode,
        )

    def sync(self, account_name: str) -> dict[str, object]:
        account = self.config.accounts[account_name]
        messages = provider_for(account).list_messages()
        changed = self.archive.upsert(messages)
        return {"account": account_name, "observed": len(messages), "changed": changed}

    def attachment_capabilities(self) -> dict[str, object]:
        limits, _ = self._attachment_pipeline()
        capabilities = describe_capabilities()
        return {
            **capabilities,
            "enabled": self.config.attachments.enabled,
            "max_text_chars": limits.max_chars,
            "max_bytes": limits.max_bytes,
            "ocr_mode": self.config.attachments.ocr_mode,
            "ocr_max_pages": limits.max_pages,
        }

    def attachment_text(
        self, account_name: str, message_id: str, attachment_id: str
    ) -> dict[str, object]:
        if not self.config.attachments.enabled:
            return {
                "status": "disabled",
                "detail": "attachment text extraction is disabled by configuration",
            }
        account = self.config.accounts[account_name]
        message = self.archive.get_message(account_name, message_id)
        if message is None:
            return {
                "status": "message_not_synced",
                "detail": "sync the account before reading attachment text",
            }
        known = {
            str(item.get("id") or "")
            for item in message.get("attachments", [])
            if isinstance(item, dict)
        }
        if attachment_id not in known:
            return {
                "status": "attachment_not_found",
                "detail": "no attachment with this id is recorded for the message",
            }
        try:
            data = provider_for(account).fetch_attachment_bytes(message_id, attachment_id)
        except AttachmentNotAvailable as exc:
            return {"status": "provider_unsupported", "detail": str(exc)}
        digest = hashlib.sha256(data).hexdigest()
        cached = self.archive.get_attachment_text(account_name, message_id, attachment_id)
        if cached is not None and cached.get("source_sha256") == digest:
            return {
                "status": str(cached.get("status")),
                "text": str(cached.get("text") or ""),
                "extractor": cached.get("extractor"),
                "truncated": bool(cached.get("truncated")),
                "cached": True,
                "source_sha256": digest,
            }
        limits, ocr_mode = self._attachment_pipeline()
        [record] = [item for item in message["attachments"] if str(item.get("id")) == attachment_id]
        result = extract_attachment_text(
            data,
            filename=str(record.get("filename") or ""),
            content_type=str(record.get("content_type") or "application/octet-stream"),
            limits=limits,
            ocr_mode=ocr_mode,
        )
        assert result.status in STATUSES, f"unknown extraction status {result.status!r}"
        self.archive.store_attachment_text(
            account_name,
            message_id,
            attachment_id,
            digest,
            result.extractor,
            result.status,
            result.text,
            result.truncated,
        )
        return {
            "status": result.status,
            "text": result.text,
            "extractor": result.extractor,
            "truncated": result.truncated,
            "detail": result.detail,
            "cached": False,
            "source_sha256": digest,
        }
