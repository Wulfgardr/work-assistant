from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from work_assistant.archive import LocalArchive
from work_assistant.config import AppConfig

BACKUP_SCHEMA = 1
KDF_ITERATIONS = 600_000
DEFAULT_PASSPHRASE_ENV = "WORK_ASSISTANT_BACKUP_PASSPHRASE"


class BackupError(RuntimeError):
    pass


def _passphrase(env_var: str) -> bytes:
    value = os.environ.get(env_var, "")
    if not value:
        raise BackupError(
            f"missing passphrase: export {env_var} first (never pass it as a CLI argument)"
        )
    return value.encode()


def _fernet(passphrase: bytes, salt: bytes) -> Fernet:
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt, KDF_ITERATIONS).derive(passphrase)
    from base64 import urlsafe_b64encode

    return Fernet(urlsafe_b64encode(key))


def _owner_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if os.name != "nt":
        os.chmod(path, 0o600)


def create_backup(
    config: AppConfig, out_dir: str | Path, *, passphrase_env: str = DEFAULT_PASSPHRASE_ENV
) -> dict[str, object]:
    """Encrypt the local archive into a backup directory with a hash manifest.

    Keys (AliasVault, broker auth) are deliberately excluded: back them up
    through OS-level secret storage, or pseudonyms cannot be restored.
    """
    source = config.data_dir / "archive.sqlite3"
    secret = _passphrase(passphrase_env)
    if not source.is_file():
        raise BackupError("nothing to back up: sync at least one account first")
    plaintext = source.read_bytes()
    report = LocalArchive(source).verify()
    if report.get("hash_mismatches"):
        raise BackupError("refusing to back up an archive with hash mismatches; run verify first")
    destination = Path(out_dir).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(destination, 0o700)
    salt = os.urandom(16)
    ciphertext = _fernet(secret, salt).encrypt(plaintext)
    archive_name = "archive.sqlite3.fernet"
    _owner_write(destination / archive_name, ciphertext)
    manifest: dict[str, object] = {
        "schema_version": BACKUP_SCHEMA,
        "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kdf": {"name": "pbkdf2-sha256", "iterations": KDF_ITERATIONS, "salt_hex": salt.hex()},
        "files": {
            archive_name: {
                "cipher_sha256": hashlib.sha256(ciphertext).hexdigest(),
                "plain_sha256": hashlib.sha256(plaintext).hexdigest(),
                "plain_size": len(plaintext),
            }
        },
        "counts": {
            "messages": report.get("messages"),
            "attachment_texts": report.get("attachment_texts"),
        },
        "source_verify": {k: report.get(k) for k in ("sqlite", "messages", "hash_mismatches")},
        "key_warning": (
            "AliasVault and broker keys are NOT included; restore them separately "
            "or stored pseudonyms cannot be reversed"
        ),
    }
    _owner_write(destination / "manifest.json", (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return {"path": str(destination), **manifest}


def _read_manifest(backup_dir: Path) -> dict:
    try:
        raw = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupError(f"backup manifest is unreadable: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != BACKUP_SCHEMA:
        raise BackupError("unsupported backup manifest")
    return raw


def restore_backup(
    backup_dir: str | Path,
    data_dir: str | Path,
    *,
    passphrase_env: str = DEFAULT_PASSPHRASE_ENV,
) -> dict[str, object]:
    """Decrypt a backup into a data directory and prove it matches the manifest."""
    source = Path(backup_dir).expanduser()
    manifest = _read_manifest(source)
    archive_name = "archive.sqlite3.fernet"
    entry = manifest.get("files", {}).get(archive_name, {})
    try:
        ciphertext = (source / archive_name).read_bytes()
    except OSError as exc:
        raise BackupError(f"backup archive is missing: {exc}") from exc
    if hashlib.sha256(ciphertext).hexdigest() != entry.get("cipher_sha256"):
        raise BackupError("backup ciphertext does not match the manifest")
    salt = bytes.fromhex(str(manifest.get("kdf", {}).get("salt_hex") or ""))
    try:
        plaintext = _fernet(_passphrase(passphrase_env), salt).decrypt(ciphertext)
    except (InvalidToken, ValueError) as exc:
        raise BackupError("cannot decrypt backup: wrong passphrase or corrupted data") from exc
    if hashlib.sha256(plaintext).hexdigest() != entry.get("plain_sha256"):
        raise BackupError("decrypted archive does not match the manifest")
    target = Path(data_dir).expanduser() / "archive.sqlite3"
    try:
        _owner_write(target, plaintext)
        report = LocalArchive(target).verify()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    expected = manifest.get("counts", {})
    counts_match = (
        report.get("messages") == expected.get("messages")
        and report.get("attachment_texts") == expected.get("attachment_texts")
    )
    if not counts_match or report.get("hash_mismatches"):
        raise BackupError("restored archive differs from the manifest")
    return {
        "restored": str(target),
        "hashes_match": True,
        "counts_match": bool(counts_match),
        "verify": {k: report.get(k) for k in ("sqlite", "messages", "hash_mismatches", "attachment_texts")},
    }


def verify_backup(
    backup_dir: str | Path, *, passphrase_env: str = DEFAULT_PASSPHRASE_ENV
) -> dict[str, object]:
    """Prove a backup by restoring it into an isolated temporary directory."""
    with tempfile.TemporaryDirectory(prefix="work-assistant-restore-proof-") as directory:
        report = restore_backup(backup_dir, directory, passphrase_env=passphrase_env)
    return {"proof": "restore_to_isolated_temporary_directory", **report}
