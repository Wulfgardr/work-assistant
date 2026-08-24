import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from importlib.resources import files

from work_assistant.archive import LocalArchive
from work_assistant.config import load_config
from work_assistant.onboarding import import_zimbra_har, onboarding_plan
from work_assistant.service import WorkAssistant


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_configuration_matches_repository_example() -> None:
    packaged = files("work_assistant").joinpath("templates/work-assistant.example.toml")
    assert packaged.read_bytes() == (ROOT / "work-assistant.example.toml").read_bytes()


def test_multi_account_sync_and_archive(tmp_path: Path) -> None:
    config_text = (ROOT / "work-assistant.example.toml").read_text()
    config_text = config_text.replace(
        "schema_version = 1\n",
        f'schema_version = 1\ndata_dir = "{(tmp_path / "workspace").as_posix()}"\n',
        1,
    )
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(config_text)
    examples = tmp_path / "examples"
    shutil.copytree(ROOT / "examples", examples)
    app = WorkAssistant(load_config(config_path))
    assert app.sync("personal") == {"account": "personal", "observed": 2, "changed": 2}
    assert app.sync("team") == {"account": "team", "observed": 1, "changed": 1}
    assert len(app.archive.list_messages()) == 3
    assert app.sync("personal")["changed"] == 0


def test_archive_integrity_and_knowledge(tmp_path: Path) -> None:
    archive = LocalArchive(tmp_path / "archive.sqlite3")
    assert archive.verify() == {"sqlite": "ok", "messages": 0, "hash_mismatches": 0}
    assert archive.build_knowledge_view()["message_count"] == 0


def test_draft_candidate_is_local(tmp_path: Path) -> None:
    archive = LocalArchive(tmp_path / "archive.sqlite3")
    draft_id = archive.create_draft_candidate(
        "personal", ["sam@example.test"], "Re: Project review", "I will review it."
    )
    assert draft_id == 1


def test_zimbra_onboarding_keeps_secret_values_local(tmp_path: Path) -> None:
    config_path = tmp_path / "work-assistant.toml"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        "schema_version = 1\n"
        f'data_dir = "{workspace.as_posix()}"\n'
        "[accounts.work]\n"
        'provider = "zimbra"\n'
        'address = "alex@example.test"\n'
        'host = "mail.example.test"\n'
    )
    har_path = tmp_path / "session.har"
    har_path.write_text(
        '{"log":{"entries":[{"request":{"url":"https://mail.example.test/service/soap/SearchRequest",'
        '"cookies":[{"name":"ZM_AUTH_TOKEN","value":"synthetic-zm-cookie-value"},'
        '{"name":"ZX_AUTH_TOKEN","value":"synthetic-zx-cookie-value"}]}}]}}'
    )
    config = load_config(config_path)
    result = import_zimbra_har(config, "work", har_path)
    assert result["secret_values_exposed"] is False
    destination = Path(result["path"])
    if os.name != "nt":
        assert destination.stat().st_mode & 0o777 == 0o600
    assert "synthetic-zm-cookie-value" in destination.read_text()
    assert onboarding_plan("zimbra")["adapter_status"] == "onboarding_ready_adapter_not_bundled"


def test_init_writes_external_platform_data_directory(tmp_path: Path) -> None:
    config_path = tmp_path / "work-assistant.toml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "work_assistant",
            "--config",
            str(config_path),
            "init",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    created = load_config(config_path)
    assert created.data_dir != tmp_path / "workspace"
    assert not created.data_dir.is_relative_to(ROOT)
    assert Path(json.loads(result.stdout)["data_dir"]) == created.data_dir
