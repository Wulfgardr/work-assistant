from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass
from fnmatch import fnmatchcase
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import threading
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from work_assistant.config import PrivacyConfig


TOKEN_RE = re.compile(r"\[\[WA:([A-Z_]+):([A-F0-9]{24})\]\]")
TOKEN_LIKE_RE = re.compile(r"\[\[WA:[^\]]*\]\]")
EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?[0-9][0-9 .()/-]{7,}[0-9])(?!\w)")


class PrivacyError(RuntimeError):
    pass


class UnknownAlias(PrivacyError):
    pass


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    matched_pattern: str | None


class PrivacyPolicy:
    def __init__(self, config: PrivacyConfig):
        self.config = config

    def decide(self, sender: str) -> PolicyDecision:
        if self.config.mode == "off":
            return PolicyDecision("allow_raw", None)
        if self.config.mode == "all":
            return PolicyDecision("pseudonymize", None)
        normalized = sender.casefold()
        for rule in self.config.sender_rules:
            if fnmatchcase(normalized, rule.pattern.casefold()):
                return PolicyDecision(rule.action, rule.pattern)
        return PolicyDecision(self.config.default_action, None)


class AliasVault:
    """Workspace-local stable aliases with authenticated encrypted values."""

    def __init__(self, data_dir: str | Path):
        root = Path(data_dir)
        self.key_path = root / "secrets" / "privacy.key"
        self.vault_path = root / "privacy" / "aliases.jsonl"
        self._key = self._load_or_create_key()
        self._values: dict[str, str] = {}
        self._lock = threading.Lock()
        self._load()

    @staticmethod
    def _owner_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, data)
        finally:
            os.close(descriptor)

    def _load_or_create_key(self) -> bytes:
        if not self.key_path.exists():
            self._owner_write(self.key_path, urlsafe_b64encode(os.urandom(32)) + b"\n")
        encoded = self.key_path.read_bytes().strip()
        key = urlsafe_b64decode(encoded)
        if len(key) != 32:
            raise PrivacyError("privacy key must decode to 32 bytes")
        return key

    def _load(self) -> None:
        if not self.vault_path.exists():
            return
        aes = AESGCM(self._key)
        for line_number, line in enumerate(self.vault_path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                record = json.loads(line)
                token = str(record["token"])
                nonce = urlsafe_b64decode(record["nonce"])
                ciphertext = urlsafe_b64decode(record["ciphertext"])
                self._values[token] = aes.decrypt(nonce, ciphertext, token.encode()).decode()
            except Exception as exc:
                raise PrivacyError(f"invalid alias vault record at line {line_number}") from exc

    @staticmethod
    def _canonical(kind: str, value: str) -> str:
        normalized = value.strip()
        if kind == "EMAIL":
            return normalized.casefold()
        if kind == "PHONE":
            return re.sub(r"\D", "", normalized)
        return normalized

    def protect(self, kind: str, value: str) -> str:
        kind = re.sub(r"[^A-Z_]", "_", kind.upper())
        canonical = self._canonical(kind, value)
        digest = hmac.new(self._key, f"{kind}\0{canonical}".encode(), hashlib.sha256).hexdigest()[:24].upper()
        token = f"[[WA:{kind}:{digest}]]"
        with self._lock:
            existing = self._values.get(token)
            if existing is not None:
                if self._canonical(kind, existing) != canonical:
                    raise PrivacyError("alias collision detected")
                return token
            nonce = os.urandom(12)
            ciphertext = AESGCM(self._key).encrypt(nonce, value.encode(), token.encode())
            record = {
                "token": token,
                "nonce": urlsafe_b64encode(nonce).decode(),
                "ciphertext": urlsafe_b64encode(ciphertext).decode(),
            }
            self.vault_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.vault_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(descriptor, (json.dumps(record, sort_keys=True) + "\n").encode())
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._values[token] = value
        return token

    def restore(self, token: str) -> str:
        value = self._values.get(token)
        if value is None:
            raise UnknownAlias("unknown or foreign pseudonym")
        return value


class Pseudonymizer:
    def __init__(self, config: PrivacyConfig, data_dir: str | Path):
        self.config = config
        self.policy = PrivacyPolicy(config)
        self.vault = AliasVault(data_dir)
        self.entities = self._load_entities(config.entities_path)

    @staticmethod
    def _load_entities(path: Path | None) -> tuple[tuple[str, str], ...]:
        if path is None or not path.exists():
            return ()
        raw = json.loads(path.read_text(encoding="utf-8"))
        values: list[tuple[str, str]] = []
        for kind, entries in raw.items():
            if not isinstance(entries, list):
                raise PrivacyError("privacy entity registry values must be lists")
            values.extend((str(kind).upper(), str(value)) for value in entries if str(value))
        return tuple(sorted(values, key=lambda item: len(item[1]), reverse=True))

    def protect_text(self, text: str, *, global_only: bool = False) -> str:
        if self.config.mode == "off":
            return text
        output = TOKEN_LIKE_RE.sub("[[WA_INPUT_TOKEN_REMOVED]]", text)
        for kind, value in self.entities:
            output = re.sub(re.escape(value), lambda match, k=kind: self.vault.protect(k, match.group(0)), output, flags=re.I)
        if global_only:
            return output
        output = EMAIL_RE.sub(lambda match: self.vault.protect("EMAIL", match.group(0)), output)
        output = PHONE_RE.sub(lambda match: self.vault.protect("PHONE", match.group(0)), output)
        return output

    def protect_address(self, value: str) -> str:
        return self.vault.protect("EMAIL", value) if value else value

    def protect_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        sender = str(payload.get("sender") or "")
        decision = self.policy.decide(sender)
        protect_all = decision.action == "pseudonymize"
        if protect_all:
            result["sender"] = self.protect_address(sender)
            result["recipients"] = [self.protect_address(str(value)) for value in payload.get("recipients", [])]
        result["subject"] = self.protect_text(str(payload.get("subject") or ""), global_only=not protect_all)
        result["body_text"] = self.protect_text(str(payload.get("body_text") or ""), global_only=not protect_all)
        attachments = []
        for item in payload.get("attachments", []) or []:
            copy = dict(item)
            copy["filename"] = self.protect_text(str(copy.get("filename") or ""), global_only=not protect_all)
            attachments.append(copy)
        result["attachments"] = attachments
        result["_privacy"] = {
            "mode": self.config.mode,
            "action": decision.action,
            "matched_sender_pattern": decision.matched_pattern,
            "pseudonymization_is_not_anonymization": True,
        }
        return result

    def protect_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        message = {
            **payload,
            "body_text": "",
            "recipients": [],
            "attachments": [],
        }
        protected = self.protect_message(message)
        for key in ("body_text", "recipients", "attachments"):
            protected.pop(key, None)
        return protected

    def restore_text(self, text: str) -> str:
        if self.config.mode == "off":
            return text
        for match in TOKEN_LIKE_RE.finditer(text):
            if TOKEN_RE.fullmatch(match.group(0)) is None:
                raise UnknownAlias("malformed pseudonym")
        return TOKEN_RE.sub(lambda match: self.vault.restore(match.group(0)), text)

    def restore_addresses(self, values: list[str]) -> list[str]:
        if self.config.mode == "off":
            return values
        restored = [self.restore_text(value) for value in values]
        if self.config.mode == "all" and any(value == original for value, original in zip(restored, values)):
            raise PrivacyError("privacy mode all requires pseudonymized recipients")
        return restored

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.config.mode,
            "default_action": self.config.default_action,
            "sender_rule_count": len(self.config.sender_rules),
            "entity_count": len(self.entities),
            "vault_entries": len(self.vault._values),
            "key_exposed": False,
            "warning": "pseudonymization reduces disclosure but does not guarantee anonymity",
        }
