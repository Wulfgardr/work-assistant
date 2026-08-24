import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from work_assistant.archive import LocalArchive
from work_assistant.broker import BrokerClient, SafeBroker, default_auth_path, default_broker_address
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
    assert decision.matched_pattern == "newsletter@*"


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


def test_selective_allow_raw_still_applies_global_entities(tmp_path: Path) -> None:
    entities = tmp_path / "entities.json"
    entities.write_text('{"PERSON": ["Alex Example"]}')
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


def test_safe_broker_never_returns_clear_protected_message(tmp_path: Path) -> None:
    source = tmp_path / "mail.jsonl"
    source.write_text(
        '{"id":"m-1","sender":"alex@example.test","recipients":["team@example.test"],'
        '"sent_at":"2026-08-24T10:00:00Z","subject":"Private note",'
        '"body_text":"Email alex@example.test","folder":"inbox"}\n'
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
    message = broker.dispatch("get", {"account": "personal", "message_id": "m-1"})
    assert "alex@example.test" not in str(listing)
    assert "alex@example.test" not in str(message)
    draft = broker.dispatch(
        "draft_candidate",
        {
            "account": "personal",
            "to": [message["sender"]],
            "subject": "Re: Private note",
            "body": f"Thanks {message['sender']}",
            "in_reply_to": "m-1",
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
