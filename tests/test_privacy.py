import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import tempfile
from multiprocessing import Pipe

import pytest

from work_assistant.archive import LocalArchive
from work_assistant.broker import (
    BrokerClient,
    BrokerError,
    SafeBroker,
    default_auth_path,
    default_broker_address,
    validate_broker_storage,
)
from work_assistant.config import ConfigError, PrivacyConfig, SenderRule, load_config
from work_assistant.models import Message
from work_assistant.privacy import AliasVault, PrivacyError, PrivacyPolicy, Pseudonymizer, UnknownAlias


def privacy(mode: str, default: str = "pseudonymize", *rules: SenderRule) -> PrivacyConfig:
    return PrivacyConfig(mode, default, tuple(rules), None)


def test_policy_modes_and_first_sender_match() -> None:
    assert PrivacyPolicy(privacy("off")).decide("person@example.test").action == "allow_raw"
    assert PrivacyPolicy(privacy("all")).decide("person@example.test").action == "pseudonymize"
    policy = PrivacyPolicy(
        privacy(
            "selective",
            "pseudonymize",
            SenderRule("newsletter@*", "allow_raw"),
            SenderRule("*@example.test", "pseudonymize"),
        )
    )
    decision = policy.decide("newsletter@example.test")
    assert decision.action == "allow_raw"
    assert decision.matched_rule_id == "sender-rule-1"


def test_selective_mode_requires_explicit_default(tmp_path: Path) -> None:
    config = tmp_path / "work-assistant.toml"
    config.write_text(
        "schema_version = 1\n"
        '[privacy]\nmode = "selective"\n'
        '[accounts.personal]\nprovider = "demo"\naddress = "a@example.test"\nsource = "mail.jsonl"\n'
    )
    with pytest.raises(ConfigError):
        load_config(config)


def test_aliases_are_stable_reversible_and_workspace_local(tmp_path: Path) -> None:
    first = AliasVault(tmp_path / "one")
    alias = first.protect("EMAIL", "alex@example.test")
    assert alias == first.protect("EMAIL", "ALEX@example.test")
    assert first.restore(alias) == "alex@example.test"
    assert "alex@example.test" not in first.vault_path.read_text(encoding="utf-8")
    second = AliasVault(tmp_path / "two")
    assert second.protect("EMAIL", "alex@example.test") != alias
    with pytest.raises(UnknownAlias):
        second.restore(alias)


def test_pseudonymizer_round_trip_and_unknown_alias_fail_closed(tmp_path: Path) -> None:
    engine = Pseudonymizer(privacy("all"), tmp_path)
    payload = {
        "id": "m-1",
        "sender": "alex@example.test",
        "recipients": ["team@example.test"],
        "subject": "Call +39 02 1234 5678",
        "body_text": "Reply to alex@example.test",
        "attachments": [{"filename": "alex@example.test-note.txt"}],
    }
    protected = engine.protect_message(payload)
    assert "alex@example.test" not in str(protected)
    assert protected["_privacy"]["action"] == "pseudonymize"
    assert engine.restore_text(protected["body_text"]) == payload["body_text"]
    with pytest.raises(UnknownAlias):
        engine.restore_text("[[WA:EMAIL:AAAAAAAAAAAAAAAAAAAAAAAA]]")
    with pytest.raises(PrivacyError):
        engine.restore_addresses(["raw@example.test"])


def test_token_like_input_cannot_inject_a_restorable_alias(tmp_path: Path) -> None:
    engine = Pseudonymizer(privacy("all"), tmp_path)
    protected = engine.protect_text("Untrusted [[WA:EMAIL:AAAAAAAAAAAAAAAAAAAAAAAA]] input")
    assert "[[WA:EMAIL:AAAAAAAAAAAAAAAAAAAAAAAA]]" not in protected
    assert "WA_INPUT_TOKEN_REMOVED" in protected


@pytest.mark.skipif(os.name == "nt", reason="positive Windows ACL setup is deployment-specific")
def test_selective_allow_raw_still_applies_global_entities(tmp_path: Path) -> None:
    entities = tmp_path / "entities.json"
    entities.write_text('{"PERSON": ["Alex Example"]}')
    if os.name != "nt":
        entities.chmod(0o600)
    config = PrivacyConfig(
        "selective",
        "pseudonymize",
        (SenderRule("newsletter@*", "allow_raw"),),
        entities,
    )
    engine = Pseudonymizer(config, tmp_path / "data")
    protected = engine.protect_message(
        {
            "sender": "newsletter@example.test",
            "recipients": ["reader@example.test"],
            "subject": "Interview with Alex Example",
            "body_text": "Alex Example joined the event.",
            "attachments": [],
        }
    )
    assert protected["sender"] == "newsletter@example.test"
    assert "Alex Example" not in protected["body_text"]
    assert protected["_privacy"]["action"] == "allow_raw"
    assert protected["_privacy"]["matched_rule_id"] == "sender-rule-1"
    assert "newsletter@*" not in str(protected)


def test_safe_broker_never_returns_clear_protected_message(tmp_path: Path) -> None:
    source = tmp_path / "mail.jsonl"
    source.write_text(
        '{"id":"m-1","sender":"alex@example.test","recipients":["team@example.test"],'
        '"sent_at":"2026-08-24T10:00:00Z","subject":"Private note",'
        '"body_text":"Email alex@example.test","folder":"private-folder",'
        '"provider_metadata":{"raw_identity":"person@example.test"},'
        '"attachments":[{"id":"person@example.test","filename":"note.txt"}]}\n'
    )
    config_path = tmp_path / "work-assistant.toml"
    data_dir = tmp_path / "data"
    config_path.write_text(
        "schema_version = 1\n"
        f'data_dir = "{data_dir.as_posix()}"\n'
        '[privacy]\nmode = "all"\n'
        '[accounts.personal]\nprovider = "demo"\naddress = "owner@example.test"\n'
        f'source = "{source.as_posix()}"\n'
    )
    broker = SafeBroker(load_config(config_path))
    broker.dispatch("sync", {"account": "personal"})
    listing = broker.dispatch("list", {"account": "personal"})
    assert listing[0]["message_ref"] != "m-1"
    assert listing[0]["attachment_count"] == 1
    assert "provider_metadata" not in listing[0]
    message = broker.dispatch(
        "get", {"account": "personal", "message_id": listing[0]["message_ref"]}
    )
    assert "alex@example.test" not in str(listing)
    assert "alex@example.test" not in str(message)
    assert "private-folder" not in str(message)
    assert "raw_identity" not in str(message)
    assert message["attachments"][0]["attachment_ref"] != "person@example.test"
    draft = broker.dispatch(
        "draft_candidate",
        {
            "account": "personal",
            "to": [message["sender"]],
            "subject": "Re: Private note",
            "body": f"Thanks {message['sender']}",
            "in_reply_to": message["message_ref"],
        },
    )
    assert draft["sent"] is False
    archive = LocalArchive(tmp_path / "data" / "archive.sqlite3")
    with archive.connect() as connection:
        row = connection.execute("SELECT to_json, body FROM draft_candidates").fetchone()
    assert "alex@example.test" in row["to_json"]
    assert "alex@example.test" in row["body"]
    artifact = broker.dispatch(
        "local_artifact",
        {
            "kind": "analysis",
            "title": f"Analysis for {message['sender']}",
            "body": f"Follow up with {message['sender']}",
        },
    )
    assert artifact["clear_content_returned"] is False
    restored = archive.get_local_artifact(artifact["local_artifact_id"])
    assert "alex@example.test" in restored["title"]
    assert "alex@example.test" in restored["body"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not Windows ACLs")
def test_entity_registry_fails_closed_when_group_readable(tmp_path: Path) -> None:
    entities = tmp_path / "entities.json"
    entities.write_text('{"PERSON": ["Alex Example"]}')
    entities.chmod(0o644)
    config = PrivacyConfig("all", "pseudonymize", (), entities)
    with pytest.raises(PrivacyError, match="owner-only"):
        Pseudonymizer(config, tmp_path / "data")


@pytest.mark.skipif(os.name != "nt", reason="requires Windows ACLs")
def test_entity_registry_rejects_broad_windows_acl(tmp_path: Path) -> None:
    entities = tmp_path / "entities.json"
    entities.write_text('{"PERSON": ["Alex Example"]}')
    subprocess.run(
        ["icacls", str(entities), "/grant", "*S-1-1-0:(R)"],
        check=True,
        capture_output=True,
        text=True,
    )
    config = PrivacyConfig("all", "pseudonymize", (), entities)
    with pytest.raises(PrivacyError, match="ACL"):
        Pseudonymizer(config, tmp_path / "data")


def test_broker_rejects_protected_data_inside_project(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    source = tmp_path / "mail.jsonl"
    source.write_text("")
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        'data_dir = "./workspace"\n'
        '[privacy]\nmode = "all"\n'
        '[accounts.personal]\nprovider = "demo"\naddress = "a@example.test"\n'
        'source = "mail.jsonl"\n'
    )
    with pytest.raises(BrokerError, match="outside the agent workspace"):
        validate_broker_storage(load_config(config_path))


def test_default_broker_address_matches_platform(tmp_path: Path) -> None:
    source = tmp_path / "mail.jsonl"
    source.write_text("")
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        '[accounts.personal]\nprovider = "demo"\naddress = "a@example.test"\n'
        f'source = "{source.as_posix()}"\n'
    )
    address = default_broker_address(load_config(config_path))
    if os.name == "nt":
        assert address.startswith(r"\\.\pipe\work-assistant-")
    else:
        assert address.endswith(".sock")
        assert len(address.encode()) < 100


def test_broker_ipc_is_authenticated_and_returns_safe_status(tmp_path: Path) -> None:
    source = tmp_path / "mail.jsonl"
    source.write_text("")
    config_path = tmp_path / "work-assistant.toml"
    data_dir = tmp_path / "data"
    config_path.write_text(
        "schema_version = 1\n"
        f'data_dir = "{data_dir.as_posix()}"\n'
        '[privacy]\nmode = "all"\n'
        '[accounts.personal]\nprovider = "demo"\naddress = "a@example.test"\n'
        f'source = "{source.as_posix()}"\n'
    )
    config = load_config(config_path)
    process = subprocess.Popen(
        [sys.executable, "-m", "work_assistant", "--config", str(config_path), "broker"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = BrokerClient(default_broker_address(config), default_auth_path(config), timeout=1)
    deadline = time.monotonic() + 5
    try:
        while True:
            try:
                status = client.call("privacy_status")
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        assert status["mode"] == "all"
        assert status["key_exposed"] is False
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.skipif(os.name == "nt", reason="uses a Unix-domain socket probe")
def test_one_unauthenticated_idle_client_does_not_block_broker(tmp_path: Path) -> None:
    source = tmp_path / "mail.jsonl"
    source.write_text("")
    config_path = tmp_path / "work-assistant.toml"
    data_dir = tmp_path / "data"
    config_path.write_text(
        "schema_version = 1\n"
        f'data_dir = "{data_dir.as_posix()}"\n'
        '[privacy]\nmode = "all"\n'
        '[accounts.personal]\nprovider = "demo"\naddress = "a@example.test"\n'
        f'source = "{source.as_posix()}"\n'
    )
    config = load_config(config_path)
    process = subprocess.Popen(
        [sys.executable, "-m", "work_assistant", "--config", str(config_path), "broker"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    address = default_broker_address(config)
    idle = socket.socket(socket.AF_UNIX)
    deadline = time.monotonic() + 5
    try:
        while True:
            try:
                idle.connect(address)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        started = time.monotonic()
        status = BrokerClient(address, default_auth_path(config), timeout=1).call("privacy_status")
        assert status["mode"] == "all"
        assert time.monotonic() - started < 1
    finally:
        idle.close()
        process.terminate()
        process.wait(timeout=5)


def test_authenticated_idle_handler_closes_after_deadline(tmp_path: Path) -> None:
    from work_assistant.broker import REQUEST_IDLE_TIMEOUT, _handle_connection

    source = tmp_path / "mail.jsonl"
    source.write_text("")
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        f'data_dir = "{(tmp_path / "data").as_posix()}"\n'
        '[privacy]\nmode = "all"\n'
        '[accounts.personal]\nprovider = "demo"\naddress = "a@example.test"\n'
        f'source = "{source.as_posix()}"\n'
    )
    server, client = Pipe(duplex=True)
    thread = threading.Thread(target=_handle_connection, args=(server, SafeBroker(load_config(config_path))))
    started = time.monotonic()
    thread.start()
    thread.join(REQUEST_IDLE_TIMEOUT + 1)
    client.close()
    assert not thread.is_alive()
    assert time.monotonic() - started < REQUEST_IDLE_TIMEOUT + 1


@pytest.mark.skipif(os.name == "nt", reason="uses a Unix-domain socket probe")
def test_client_timeout_covers_connection_authentication(tmp_path: Path) -> None:
    address = Path(tempfile.gettempdir()) / f"wa-test-{os.getpid()}-{time.time_ns()}.sock"
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(address))
    server.listen(1)
    accepted = threading.Event()

    def stall() -> None:
        connection, _ = server.accept()
        accepted.set()
        try:
            time.sleep(1)
        finally:
            connection.close()

    threading.Thread(target=stall, daemon=True).start()
    auth = tmp_path / "broker.auth"
    auth.write_text("a" * 64)
    started = time.monotonic()
    try:
        with pytest.raises(BrokerError, match="connection timed out"):
            BrokerClient(address, auth, timeout=0.2).call("privacy_status")
    finally:
        server.close()
        address.unlink(missing_ok=True)
    assert accepted.wait(0.5)
    assert time.monotonic() - started < 0.8
