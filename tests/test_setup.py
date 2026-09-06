import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from work_assistant.cli import main
from work_assistant.config import load_config
from work_assistant.doctor import run_checks, run_doctor
from work_assistant.mcp_setup import desktop_snippet, run_mcp_setup, server_command
from work_assistant.setup import SetupAborted, render_config, run_setup


ROOT = Path(__file__).resolve().parents[1]


def _demo_repo(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "examples", tmp_path / "examples")
    return tmp_path / "work-assistant.toml"


def _answers(monkeypatch, values: list[str]):
    iterator = iter(values)

    def fake_input(prompt: str = "") -> str:
        try:
            return next(iterator)
        except StopIteration as exc:
            raise EOFError("answers exhausted") from exc

    monkeypatch.setattr("builtins.input", fake_input)


def test_setup_demo_is_one_shot(tmp_path: Path) -> None:
    config_path = _demo_repo(tmp_path)
    report = run_setup(config_path, demo=True)
    assert report["synced"] == ["personal"]
    config = load_config(config_path)
    assert config.privacy.mode == "all"
    assert set(config.accounts) == {"personal"}
    assert config.data_dir != tmp_path


def test_setup_demo_backs_up_existing_config(tmp_path: Path) -> None:
    config_path = _demo_repo(tmp_path)
    run_setup(config_path, demo=True)
    run_setup(config_path, demo=True)
    assert len(list(tmp_path.glob("work-assistant.toml.bak.*"))) == 1


def test_setup_interactive_imap_flow(monkeypatch, tmp_path: Path) -> None:
    secret = tmp_path / "office.secret"
    secret.write_text("synthetic-app-password\n")
    secret.chmod(0o600)
    monkeypatch.setattr(
        "work_assistant.service.WorkAssistant.sync", lambda self, name: {"account": name, "observed": 3, "changed": 3}
    )
    _answers(
        monkeypatch,
        [
            "",  # privacy: default all
            "3",  # type: imap
            "lavoro",  # name
            "alex@example.test",  # address
            "https://imap.example.test/x",  # host: invalid, retry
            "imap.example.test",  # host: valid
            "",  # username: default address
            str(secret),  # secret file
            "n",  # no more accounts
        ],
    )
    config_path = tmp_path / "work-assistant.toml"
    report = run_setup(config_path)
    assert report["synced"] == ["lavoro (3 messaggi)"]
    config = load_config(config_path)
    account = config.accounts["lavoro"]
    assert account.provider == "imap"
    assert account.options["host"] == "imap.example.test"
    assert account.options["username"] == "alex@example.test"
    assert "synthetic-app-password" not in config_path.read_text()


def test_setup_aborts_cleanly_on_eof(monkeypatch, tmp_path: Path) -> None:
    _answers(monkeypatch, [])
    with pytest.raises(SetupAborted):
        run_setup(tmp_path / "work-assistant.toml")


def test_render_config_quotes_safely(tmp_path: Path) -> None:
    text = render_config(
        tmp_path / "data",
        "all",
        [
            {
                "name": "lavoro",
                "provider": "imap",
                "address": 'we"ird\\alex@example.test',
                "options": {"host": "imap.example.test", "secret_file": "C:\\segreti\\a.secret"},
            }
        ],
    )
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(text)
    account = load_config(config_path).accounts["lavoro"]
    assert account.address == 'we"ird\\alex@example.test'
    assert account.options["secret_file"].endswith("a.secret")


def test_doctor_reports_healthy_config(tmp_path: Path, capsys) -> None:
    config_path = _demo_repo(tmp_path)
    run_setup(config_path, demo=True)
    assert run_doctor(config_path) == 0
    out = capsys.readouterr().out
    assert "✓" in out and "✗" not in out


def test_doctor_flags_missing_secret_with_hint(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        f'data_dir = "{(tmp_path / "data").as_posix()}"\n'
        "[privacy]\nmode = \"all\"\n"
        '[accounts.office]\nprovider = "imap"\naddress = "a@example.test"\n'
        'host = "imap.example.test"\nsecret_file = "missing.secret"\n'
    )
    assert run_doctor(config_path) == 1
    out = capsys.readouterr().out
    assert "✗" in out and "0600" in out
    assert run_doctor(config_path, as_json=True) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert any(check["level"] == "fail" for check in payload["checks"])


def test_doctor_flags_missing_adapter(tmp_path: Path) -> None:
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        '[accounts.missing]\nprovider = "carrier-pigeon"\naddress = "a@example.test"\n'
    )
    levels = {check.id: check.level for check in run_checks(config_path)}
    assert levels["adapter:missing"] == "fail"


def test_mcp_setup_prints_ready_commands(tmp_path: Path, capsys) -> None:
    config_path = _demo_repo(tmp_path)
    run_setup(config_path, demo=True)
    assert run_mcp_setup(config_path, "codex") == 0
    out = capsys.readouterr().out
    assert "codex mcp add work-assistant" in out and "broker" in out
    assert run_mcp_setup(config_path, "claude-desktop") == 0
    assert "mcpServers" in capsys.readouterr().out
    assert run_mcp_setup(config_path, "telepathy") == 2
    snippet = json.loads(desktop_snippet(server_command("addr", "auth")))
    assert snippet["mcpServers"]["work-assistant"]["args"][-1] == "auth"


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX helper script")
def test_mcp_setup_apply_registers_when_client_exists(tmp_path: Path, monkeypatch) -> None:
    helper = tmp_path / "codex"
    helper.write_text("#!/bin/sh\necho registered >> \"$WA_LOG\"\n")
    helper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("WA_LOG", str(tmp_path / "calls.log"))
    config_path = _demo_repo(tmp_path)
    run_setup(config_path, demo=True)
    assert run_mcp_setup(config_path, "codex", apply=True) == 0
    assert "registered" in (tmp_path / "calls.log").read_text()


def test_cli_wires_new_commands(tmp_path: Path) -> None:
    config_path = _demo_repo(tmp_path)
    assert main(["--config", str(config_path), "setup", "--demo"]) == 0
    assert main(["--config", str(config_path), "doctor"]) == 0
    assert main(["--config", str(config_path), "mcp-setup", "--client", "vscode"]) == 0


def test_full_demo_flow_through_subprocess(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "examples", tmp_path / "examples")
    config_path = tmp_path / "work-assistant.toml"
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    setup = subprocess.run(
        [sys.executable, "-m", "work_assistant", "--config", str(config_path), "setup", "--demo"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert setup.returncode == 0, setup.stderr
    doctor = subprocess.run(
        [sys.executable, "-m", "work_assistant", "--config", str(config_path), "doctor"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert doctor.returncode == 0, doctor.stdout
    assert "✓" in doctor.stdout
