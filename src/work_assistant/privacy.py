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


def _windows_acl_is_private(path: Path) -> bool:
    """Return false when a Windows file grants access to broad user groups."""
    if os.name != "nt":
        return True
    import ctypes
    from ctypes import wintypes

    class AclSizeInformation(ctypes.Structure):
        _fields_ = [
            ("AceCount", wintypes.DWORD),
            ("AclBytesInUse", wintypes.DWORD),
            ("AclBytesFree", wintypes.DWORD),
        ]

    class AceHeader(ctypes.Structure):
        _fields_ = [
            ("AceType", wintypes.BYTE),
            ("AceFlags", wintypes.BYTE),
            ("AceSize", wintypes.WORD),
        ]

    class AccessAllowedAce(ctypes.Structure):
        _fields_ = [
            ("Header", AceHeader),
            ("Mask", wintypes.DWORD),
            ("SidStart", wintypes.DWORD),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    advapi32.GetAclInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    result = advapi32.GetNamedSecurityInfoW(
        str(path), 1, 4, None, None, ctypes.byref(dacl), None, ctypes.byref(descriptor)
    )
    if result != 0 or not dacl.value:
        if descriptor.value:
            kernel32.LocalFree(descriptor)
        return False
    broad_sids = {"S-1-1-0", "S-1-5-11", "S-1-5-32-545"}
    info = AclSizeInformation()
    if not advapi32.GetAclInformation(dacl, ctypes.byref(info), ctypes.sizeof(info), 2):
        kernel32.LocalFree(descriptor)
        return False
    try:
        for index in range(info.AceCount):
            ace_pointer = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
                return False
            ace = ctypes.cast(ace_pointer, ctypes.POINTER(AccessAllowedAce)).contents
            if ace.Header.AceType != 0 or ace.Mask == 0:
                continue
            sid_pointer = ctypes.c_void_p(
                ace_pointer.value + AccessAllowedAce.SidStart.offset
            )
            sid_text = wintypes.LPWSTR()
            if not advapi32.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_text)):
                return False
            try:
                if sid_text.value in broad_sids:
                    return False
            finally:
                kernel32.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        return True
    finally:
        kernel32.LocalFree(descriptor)


def _assert_private_registry(path: Path) -> None:
    _assert_private_path(path, "privacy entity registry")


def _assert_private_registry_like(path: Path) -> None:
    _assert_private_path(path, "privacy key")


def _assert_private_path(path: Path, what: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise PrivacyError(f"{what} must be a regular file")
    if os.name == "nt":
        if not _windows_acl_is_private(path):
            raise PrivacyError(f"{what} ACL grants access to a broad Windows group")
        return
    stat = path.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise PrivacyError(f"{what} must be owner-only (0600)")


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    matched_rule_id: str | None


class PrivacyPolicy:
    def __init__(self, config: PrivacyConfig):
        self.config = config

    def decide(self, sender: str) -> PolicyDecision:
        if self.config.mode == "off":
            return PolicyDecision("allow_raw", None)
        if self.config.mode == "all":
            return PolicyDecision("pseudonymize", None)
        normalized = sender.casefold()
        for index, rule in enumerate(self.config.sender_rules, 1):
            if fnmatchcase(normalized, rule.pattern.casefold()):
                return PolicyDecision(rule.action, f"sender-rule-{index}")
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
        else:
            # Re-verify on every load: a later chmod 644 would de-pseudonymize everything.
            _assert_private_registry_like(self.key_path)
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
        _assert_private_registry(path)
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

    def protect_reference(self, kind: str, value: str) -> str:
        return self.vault.protect(kind, value) if value else value

    def restore_reference(self, value: str) -> str:
        return self.vault.restore(value)

    def protect_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        sender = str(payload.get("sender") or "")
        decision = self.policy.decide(sender)
        protect_all = decision.action == "pseudonymize"
        protected_sender = self.protect_address(sender) if protect_all else sender
        recipients = [str(value) for value in payload.get("recipients", [])]
        protected_recipients = (
            [self.protect_address(value) for value in recipients] if protect_all else recipients
        )
        attachments = []
        for item in payload.get("attachments", []) or []:
            attachments.append(
                {
                    "attachment_ref": self.protect_reference("ATTACHMENT_ID", str(item.get("id") or "")),
                    "filename": self.protect_text(
                        str(item.get("filename") or ""), global_only=not protect_all
                    ),
                    "content_type": str(item.get("content_type") or "application/octet-stream"),
                    "size": item.get("size") if isinstance(item.get("size"), int) else None,
                }
            )
        return {
            "message_ref": self.protect_reference("MESSAGE_ID", str(payload.get("id") or payload.get("provider_id") or "")),
            "thread_ref": self.protect_reference("THREAD_ID", str(payload.get("thread_id") or "")),
            "account": str(payload.get("account") or ""),
            "sent_at": str(payload.get("sent_at") or ""),
            "sender": protected_sender,
            "recipients": protected_recipients,
            "subject": self.protect_text(str(payload.get("subject") or ""), global_only=not protect_all),
            "body_text": self.protect_text(str(payload.get("body_text") or ""), global_only=not protect_all),
            "attachments": attachments,
            "_privacy": {
                "mode": self.config.mode,
                "action": decision.action,
                "matched_rule_id": decision.matched_rule_id,
                "pseudonymization_is_not_anonymization": True,
            },
        }

    def protect_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        protected = self.protect_message({**payload, "body_text": ""})
        return {
            "message_ref": protected["message_ref"],
            "thread_ref": protected["thread_ref"],
            "account": protected["account"],
            "sent_at": protected["sent_at"],
            "sender": protected["sender"],
            "subject": protected["subject"],
            "attachment_count": len(protected["attachments"]),
            "_privacy": protected["_privacy"],
        }

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
