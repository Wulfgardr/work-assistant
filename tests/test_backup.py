import json
import os
from pathlib import Path

import pytest

from work_assistant.archive import LocalArchive
from work_assistant.backup import (
    BackupError,
    create_backup,
    restore_backup,
    verify_backup,
)
from work_assistant.config import load_config
from work_assistant.models import Message
from work_assistant.service import WorkAssistant


ENV = "WORK_ASSISTANT_BACKUP_PASSPHRASE"


def _config(tmp_path: Path) -> Path:
    source = tmp_path / "mail.jsonl"
    source.write_text(
        json.dumps(
            {
                "id": "m-1",
                "sender": "sam@example.test",
                "recipients": ["alex@example.test"],
                "sent_at": "2026-09-06T10:00:00Z",
                "subject": "Synthetic",
                "body_text": "Synthetic body.",
            }
        )
        + "\n"
    )
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        f'data_dir = "{(tmp_path / "data").as_posix()}"\n'
        "[privacy]\nmode = \"all\"\n"
        '[accounts.personal]\nprovider = "demo"\naddress = "alex@example.test"\n'
        f'source = "{source.as_posix()}"\n'
    )
    return config_path


def test_backup_restore_proof_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(ENV, "synthetic-test-passphrase")
    config = load_config(_config(tmp_path))
    app = WorkAssistant(config)
    app.sync("personal")
    app.archive.store_attachment_text("personal", "m-1", "a-1", "s", "builtin-text", "ok", "hi", False)
    backup_dir = tmp_path / "backup"
    manifest = create_backup(config, backup_dir)
    assert manifest["counts"] == {"messages": 1, "attachment_texts": 1}
    assert manifest["key_warning"].startswith("AliasVault")
    assert b"Synthetic body" not in (backup_dir / "archive.sqlite3.fernet").read_bytes()
    proof = verify_backup(backup_dir)
    assert proof["proof"] == "restore_to_isolated_temporary_directory"
    assert proof["counts_match"] is True and proof["hashes_match"] is True
    restored_dir = tmp_path / "restored"
    report = restore_backup(backup_dir, restored_dir)
    restored = LocalArchive(restored_dir / "archive.sqlite3")
    assert restored.get_message("personal", "m-1")["subject"] == "Synthetic"
    assert restored.get_attachment_text("personal", "m-1", "a-1")["text"] == "hi"
    assert report["verify"]["messages"] == 1


def test_backup_requires_passphrase_and_synced_archive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(ENV, raising=False)
    config = load_config(_config(tmp_path))
    with pytest.raises(BackupError, match="export"):
        create_backup(config, tmp_path / "backup")
    monkeypatch.setenv(ENV, "x")
    with pytest.raises(BackupError, match="nothing to back up"):
        create_backup(config, tmp_path / "backup")


def test_restore_rejects_tampering_and_wrong_passphrase(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(ENV, "synthetic-test-passphrase")
    config = load_config(_config(tmp_path))
    WorkAssistant(config).sync("personal")
    backup_dir = tmp_path / "backup"
    create_backup(config, backup_dir)
    target = backup_dir / "archive.sqlite3.fernet"
    raw = bytearray(target.read_bytes())
    raw[len(raw) // 2] ^= 0xFF
    target.write_bytes(bytes(raw))
    with pytest.raises(BackupError):
        verify_backup(backup_dir)
    create_backup(config, backup_dir)
    monkeypatch.setenv(ENV, "wrong-passphrase")
    with pytest.raises(BackupError, match="wrong passphrase"):
        verify_backup(backup_dir)


def test_restore_rejects_count_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(ENV, "synthetic-test-passphrase")
    config = load_config(_config(tmp_path))
    app = WorkAssistant(config)
    app.sync("personal")
    backup_dir = tmp_path / "backup"
    create_backup(config, backup_dir)
    app.archive.upsert(
        [
            Message(
                id="m-2",
                thread_id="m-2",
                account="personal",
                subject="Later",
                sender="sam@example.test",
                recipients=("alex@example.test",),
                sent_at="2026-09-07T10:00:00Z",
                body_text="Later body.",
            )
        ]
    )
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["counts"]["messages"] = 99
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(BackupError, match="differs from the manifest"):
        restore_backup(backup_dir, tmp_path / "restored")


def test_backup_directory_permissions(tmp_path: Path, monkeypatch) -> None:
    if os.name == "nt":
        pytest.skip("POSIX permission bits are not Windows ACLs")
    monkeypatch.setenv(ENV, "synthetic-test-passphrase")
    config = load_config(_config(tmp_path))
    WorkAssistant(config).sync("personal")
    backup_dir = tmp_path / "backup"
    create_backup(config, backup_dir)
    assert backup_dir.stat().st_mode & 0o777 == 0o700
    assert (backup_dir / "manifest.json").stat().st_mode & 0o777 == 0o600
