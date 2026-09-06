import json
import mailbox
from email.message import EmailMessage
import os
from pathlib import Path
import subprocess
import sys

import pytest

from work_assistant.archive import LocalArchive
from work_assistant.attachments import (
    AnyDocExtractor,
    AttachmentNotAvailable,
    HtmlExtractor,
    NeedsOcr,
    PipelineLimits,
    PlainTextExtractor,
    describe_capabilities,
    extract_attachment_text,
    register_extractor,
    register_renderer,
    registered_extractors,
    reset_extractors_for_tests,
    unregister_extractor,
    unregister_renderer,
)
from work_assistant.broker import SafeBroker
from work_assistant.config import ConfigError, load_config
from work_assistant.onboarding import onboarding_plan, onboarding_status
from work_assistant.providers import DemoProvider
from work_assistant.service import (
    UnsupportedProvider,
    WorkAssistant,
    available_providers,
    provider_for,
)


@pytest.fixture(autouse=True)
def isolated_extractors():
    reset_extractors_for_tests()
    yield
    reset_extractors_for_tests()


def _demo_config(tmp_path: Path, body: str = "Synthetic note for alex@example.test") -> Path:
    source = tmp_path / "mail.jsonl"
    source.write_text(
        json.dumps(
            {
                "id": "m-1",
                "sender": "sam@example.test",
                "recipients": ["alex@example.test"],
                "sent_at": "2026-09-05T10:00:00Z",
                "subject": "Synthetic attachment",
                "body_text": "See the attached note.",
                "attachments": [
                    {
                        "id": "a-1",
                        "filename": "note.txt",
                        "content_type": "text/plain",
                        "size": len(body.encode()),
                    }
                ],
            }
        )
        + "\n"
    )
    attachments_dir = tmp_path / "mail.attachments"
    attachments_dir.mkdir()
    (attachments_dir / "a-1").write_text(body)
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        f'data_dir = "{(tmp_path / "data").as_posix()}"\n'
        '[privacy]\nmode = "all"\n'
        '[accounts.personal]\nprovider = "demo"\naddress = "alex@example.test"\n'
        f'source = "{source.as_posix()}"\n'
    )
    return config_path


def test_builtin_text_html_empty_and_limits() -> None:
    register_extractor(PlainTextExtractor())
    register_extractor(HtmlExtractor())
    text = extract_attachment_text(b"hello synthetic", filename="n.txt", content_type="text/plain")
    assert (text.status, text.text, text.extractor) == ("ok", "hello synthetic", "builtin-text")
    html = extract_attachment_text(
        b"<p>Hello <b>synthetic</b></p>", filename="n.html", content_type="text/html"
    )
    assert html.status == "ok" and html.text == "Hello synthetic" and "<" not in html.text
    assert extract_attachment_text(b"", filename="n.txt", content_type="text/plain").status == "empty"
    big = extract_attachment_text(
        b"x" * 16, filename="n.txt", content_type="text/plain", limits=PipelineLimits(max_bytes=10)
    )
    assert big.status == "too_large"
    clipped = extract_attachment_text(
        b"abcdefgh", filename="n.txt", content_type="text/plain", limits=PipelineLimits(max_chars=5)
    )
    assert (clipped.status, clipped.text, clipped.truncated) == ("ok", "abcde", True)


def test_unsupported_without_anydoc_and_ocr_disabled() -> None:
    register_extractor(PlainTextExtractor())
    pdf = extract_attachment_text(b"%PDF-1.4 synthetic", filename="n.pdf", content_type="application/pdf")
    assert pdf.status == "unsupported"
    off = extract_attachment_text(
        b"%PDF-1.4 synthetic", filename="n.pdf", content_type="application/pdf", ocr_mode="off"
    )
    assert off.status == "ocr_not_configured"


def test_scanned_pdf_uses_render_and_ocr_chain() -> None:
    class ScannedPdf:
        name = "fake-doc"

        def supports(self, *, content_type: str, filename: str) -> bool:
            return content_type == "application/pdf"

        def extract(self, data: bytes, *, content_type: str, filename: str) -> str:
            raise NeedsOcr("image-only synthetic pdf")

    class FakeOcr:
        name = "fake-ocr"
        is_ocr = True

        def supports(self, *, content_type: str, filename: str) -> bool:
            return content_type == "image/png"

        def extract(self, data: bytes, *, content_type: str, filename: str) -> str:
            return "synthetic ocr transcript"

    class FakeRenderer:
        name = "fake-render"

        def supports(self, *, content_type: str, filename: str) -> bool:
            return content_type == "application/pdf"

        def available(self) -> bool:
            return True

        def render(self, data: bytes, *, max_pages: int) -> list[bytes]:
            assert max_pages >= 1
            return [b"fake-page-one", b"fake-page-two"]

    register_extractor(ScannedPdf())
    register_extractor(FakeOcr())
    waiting = extract_attachment_text(b"%PDF synthetic", filename="s.pdf", content_type="application/pdf")
    assert waiting.status == "needs_ocr"
    # The fakes stand in for pdftoppm+tesseract without requiring system binaries.
    register_renderer(FakeRenderer())
    chained = extract_attachment_text(
        b"%PDF synthetic", filename="s.pdf", content_type="application/pdf"
    )
    assert chained.status == "ok"
    assert chained.extractor == "fake-render+fake-ocr"
    assert "[page 1]\nsynthetic ocr transcript" in chained.text
    assert "[page 2]\nsynthetic ocr transcript" in chained.text
    report = describe_capabilities()
    assert report["pdf_ocr_available"] is True
    unregister_renderer("fake-render")
    assert describe_capabilities()["pdf_ocr_available"] is False


def test_anydoc_converts_rtf_when_installed() -> None:
    pytest.importorskip("anydoc")
    register_extractor(AnyDocExtractor())
    result = extract_attachment_text(
        b"{\\rtf1\\ansi Synthetic attachment note.}",
        filename="note.rtf",
        content_type="application/rtf",
    )
    assert result.status == "ok"
    assert result.extractor == "anydoc"
    assert "Synthetic attachment note" in result.text


def test_attachment_text_cache_round_trip(tmp_path: Path) -> None:
    archive = LocalArchive(tmp_path / "archive.sqlite3")
    assert archive.get_attachment_text("personal", "m-1", "a-1") is None
    archive.store_attachment_text("personal", "m-1", "a-1", "sha", "builtin-text", "ok", "hi", False)
    cached = archive.get_attachment_text("personal", "m-1", "a-1")
    assert cached is not None and cached["text"] == "hi" and cached["truncated"] is False
    archive.store_attachment_text("personal", "m-1", "a-1", "sha2", "builtin-text", "ok", "hi2", True)
    updated = archive.get_attachment_text("personal", "m-1", "a-1")
    assert updated is not None and updated["source_sha256"] == "sha2" and updated["truncated"] is True


def test_service_attachment_text_caches_by_source_hash(tmp_path: Path) -> None:
    config = load_config(_demo_config(tmp_path))
    app = WorkAssistant(config)
    assert app.sync("personal")["changed"] == 1
    first = app.attachment_text("personal", "m-1", "a-1")
    assert first["status"] == "ok" and first["cached"] is False
    assert first["extractor"] == "builtin-text"
    assert "alex@example.test" in str(first["text"])
    second = app.attachment_text("personal", "m-1", "a-1")
    assert second["cached"] is True and second["source_sha256"] == first["source_sha256"]
    (tmp_path / "mail.attachments" / "a-1").write_text("Changed synthetic body.")
    third = app.attachment_text("personal", "m-1", "a-1")
    assert third["cached"] is False and third["source_sha256"] != first["source_sha256"]
    assert app.attachment_text("personal", "missing", "a-1")["status"] == "message_not_synced"
    assert app.attachment_text("personal", "m-1", "missing")["status"] == "attachment_not_found"


def test_demo_provider_rejects_unsafe_attachment_references(tmp_path: Path) -> None:
    provider = DemoProvider("personal", tmp_path / "mail.jsonl")
    with pytest.raises(AttachmentNotAvailable):
        provider.fetch_attachment_bytes("m-1", "../outside")
    with pytest.raises(AttachmentNotAvailable):
        provider.fetch_attachment_bytes("m-1", "")
    with pytest.raises(AttachmentNotAvailable):
        provider.fetch_attachment_bytes("m-1", "absent")


def test_broker_attachment_text_never_exposes_bytes_or_clear_pii(tmp_path: Path) -> None:
    body = "Contact alex@example.test at +39 02 1234 5678 about the synthetic note."
    broker = SafeBroker(load_config(_demo_config(tmp_path, body)))
    broker.dispatch("sync", {"account": "personal"})
    listing = broker.dispatch("list", {"account": "personal"})
    message = broker.dispatch("get", {"account": "personal", "message_id": listing[0]["message_ref"]})
    attachment_ref = message["attachments"][0]["attachment_ref"]
    result = broker.dispatch(
        "attachment_text",
        {
            "account": "personal",
            "message_id": listing[0]["message_ref"],
            "attachment_id": attachment_ref,
        },
    )
    assert result["status"] == "ok"
    assert "alex@example.test" not in result["text"]
    assert "[[WA:EMAIL:" in result["text"]
    assert result["_privacy"]["action"] == "pseudonymize"
    assert "provider_metadata" not in str(result)
    capabilities = broker.dispatch("attachment_capabilities", {})
    assert any(item["name"] == "builtin-text" for item in capabilities["extractors"])


def test_maildir_provider_sync_and_attachment_fetch(tmp_path: Path) -> None:
    box = mailbox.Maildir(str(tmp_path / "box"), create=True)
    outgoing = EmailMessage()
    outgoing["From"] = "sam@example.test"
    outgoing["To"] = "alex@example.test"
    outgoing["Subject"] = "Synthetic maildir note"
    outgoing["Message-ID"] = "<synthetic-1@example.test>"
    outgoing.set_content("See the attached synthetic note.")
    outgoing.add_attachment(
        b"Synthetic maildir attachment body.",
        maintype="text",
        subtype="plain",
        filename="note.txt",
    )
    box.add(outgoing)
    box.close()
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        f'data_dir = "{(tmp_path / "data").as_posix()}"\n'
        '[privacy]\nmode = "all"\n'
        '[accounts.local]\nprovider = "maildir"\naddress = "alex@example.test"\n'
        f'path = "{(tmp_path / "box").as_posix()}"\n'
    )
    app = WorkAssistant(load_config(config_path))
    assert app.sync("local") == {"account": "local", "observed": 1, "changed": 1}
    stored = app.archive.list_messages("local", 10)[0]
    payload = app.archive.get_message("local", "synthetic-1@example.test")
    assert payload is not None and len(payload["attachments"]) == 1
    assert stored["attachments"][0]["filename"] == "note.txt"
    result = app.attachment_text("local", "synthetic-1@example.test", "part-1")
    assert result["status"] == "ok"
    assert "Synthetic maildir attachment body" in str(result["text"])


def test_provider_registry_lists_bundled_adapters_and_rejects_unknown(tmp_path: Path) -> None:
    assert {"demo", "maildir"} <= set(available_providers())
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        '[accounts.missing]\nprovider = "carrier-pigeon"\naddress = "a@example.test"\n'
    )
    config = load_config(config_path)
    with pytest.raises(UnsupportedProvider, match="not installed"):
        provider_for(config.accounts["missing"])


def test_config_attachment_defaults_and_validation(tmp_path: Path) -> None:
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        '[accounts.personal]\nprovider = "demo"\naddress = "a@example.test"\nsource = "mail.jsonl"\n'
    )
    config = load_config(config_path)
    assert config.attachments.enabled is True
    assert config.attachments.max_text_chars == 20000
    assert config.attachments.ocr_mode == "auto"
    bad = tmp_path / "bad.toml"
    bad.write_text(
        "schema_version = 1\n"
        '[attachments]\nocr_mode = "cloud"\n'
        '[accounts.personal]\nprovider = "demo"\naddress = "a@example.test"\nsource = "mail.jsonl"\n'
    )
    with pytest.raises(ConfigError):
        load_config(bad)


def test_onboarding_covers_maildir_carbonio_and_adapter_availability(tmp_path: Path) -> None:
    assert onboarding_plan("carbonio")["adapter_status"] == "onboarding_ready_adapter_not_bundled"
    assert onboarding_plan("maildir")["adapter_status"] == "available"
    config_path = tmp_path / "work-assistant.toml"
    config_path.write_text(
        "schema_version = 1\n"
        f'data_dir = "{(tmp_path / "data").as_posix()}"\n'
        '[accounts.local]\nprovider = "maildir"\naddress = "a@example.test"\n'
        f'path = "{(tmp_path / "box").as_posix()}"\n'
        '[accounts.work]\nprovider = "zimbra"\naddress = "b@example.test"\n'
        'host = "mail.example.test"\n'
    )
    status = onboarding_status(load_config(config_path))
    by_name = {item["name"]: item for item in status["accounts"]}
    assert by_name["local"]["adapter_available"] is True
    assert by_name["work"]["adapter_available"] is False


def test_cli_attachment_commands_use_local_archive(tmp_path: Path) -> None:
    config_path = _demo_config(tmp_path)
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    sync = subprocess.run(
        [sys.executable, "-m", "work_assistant", "--config", str(config_path), "sync", "--account", "personal"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert json.loads(sync.stdout)["changed"] == 1
    read = subprocess.run(
        [
            sys.executable,
            "-m",
            "work_assistant",
            "--config",
            str(config_path),
            "attachment-text",
            "--account",
            "personal",
            "--id",
            "m-1",
            "--attachment-id",
            "a-1",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert json.loads(read.stdout)["status"] == "ok"
    capabilities = subprocess.run(
        [sys.executable, "-m", "work_assistant", "--config", str(config_path), "attachment-capabilities"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert "builtin-text" in capabilities.stdout


def test_capabilities_report_documents_local_only_guarantees() -> None:
    register_extractor(PlainTextExtractor())
    report = describe_capabilities()
    assert report["ocr_available"] is False
    assert any("never cross the broker" in note for note in report["notes"])
    assert [item.name for item in registered_extractors()] == ["builtin-text"]
    unregister_extractor("builtin-text")
    assert registered_extractors() == []
