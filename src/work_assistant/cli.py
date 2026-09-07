from __future__ import annotations

import argparse
from importlib.resources import files
import json
from pathlib import Path

from work_assistant.benchmark import benchmark_privacy
from work_assistant.backup import BackupError
from work_assistant.broker import default_auth_path, default_broker_address, run_broker
from work_assistant.config import default_data_dir, load_config
from work_assistant.onboarding import import_zimbra_har, onboarding_plan, onboarding_status
from work_assistant.service import WorkAssistant


def _emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _add_draft_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", required=True)
    parser.add_argument("--to", action="append", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body-file", required=True)
    parser.add_argument("--in-reply-to")


def _read_body_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="work-assistant")
    parser.add_argument("--config", default="work-assistant.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="crea una configurazione locale dall'esempio")
    init.add_argument("--force", action="store_true")
    setup = sub.add_parser("setup", help="configurazione guidata passo passo")
    setup.add_argument("--demo", action="store_true", help="demo sintetica in un colpo solo")
    sub.add_parser("doctor", help="controlla configurazione, segreti e adapter").add_argument(
        "--json", action="store_true", help="riporta i controlli in JSON"
    )
    mcp_setup = sub.add_parser("mcp-setup", help="prepara la registrazione MCP per un client")
    mcp_setup.add_argument("--client", required=True, choices=["codex", "claude-code", "claude-desktop", "vscode"])
    mcp_setup.add_argument("--apply", action="store_true", help="registra subito se il client è installato")
    sync = sub.add_parser("sync", help="acquisisce i messaggi di un account configurato")
    sync.add_argument("--account", required=True)
    listing = sub.add_parser("list", help="elenca i messaggi archiviati localmente")
    listing.add_argument("--account")
    listing.add_argument("--limit", type=int, default=20)
    show = sub.add_parser("show", help="mostra un messaggio archiviato localmente")
    show.add_argument("--account", required=True)
    show.add_argument("--id", required=True)
    attachment = sub.add_parser(
        "attachment-text", help="estrae localmente il testo derivato di un allegato"
    )
    attachment.add_argument("--account", required=True)
    attachment.add_argument("--id", required=True)
    attachment.add_argument("--attachment-id", required=True)
    sub.add_parser(
        "attachment-capabilities",
        help="mostra estrattori disponibili, stato OCR e limiti",
    )
    artifact = sub.add_parser("artifact-show", help="mostra un artefatto locale in chiaro")
    artifact.add_argument("--id", type=int, required=True)
    draft = sub.add_parser("draft-candidate", help="salva un candidato locale senza inviare")
    _add_draft_args(draft)
    provider_draft = sub.add_parser(
        "draft-on-provider", help="salva una bozza sul provider senza inviare (solo persona)"
    )
    _add_draft_args(provider_draft)
    sub.add_parser("knowledge", help="ricostruisce la vista di conoscenza locale")
    sub.add_parser("verify", help="controlla archivio, hash e cache derivata")
    backup = sub.add_parser("backup", help="esporta l'archivio cifrato con manifesto di hash")
    backup.add_argument("--out", required=True)
    backup.add_argument("--passphrase-env", default="WORK_ASSISTANT_BACKUP_PASSPHRASE")
    restore = sub.add_parser("restore", help="ripristina un backup in una cartella dati")
    restore.add_argument("--from", dest="backup_dir", required=True)
    restore.add_argument("--data-dir", required=True)
    restore.add_argument("--passphrase-env", default="WORK_ASSISTANT_BACKUP_PASSPHRASE")
    proof = sub.add_parser("backup-verify", help="prova un backup con ripristino isolato")
    proof.add_argument("--from", dest="backup_dir", required=True)
    proof.add_argument("--passphrase-env", default="WORK_ASSISTANT_BACKUP_PASSPHRASE")
    plan = sub.add_parser("onboarding-plan", help="mostra il piano persona-agente")
    plan.add_argument("--provider", required=True)
    sub.add_parser("onboarding-status", help="mostra lo stato senza valori segreti")
    har = sub.add_parser("import-zimbra-har", help="estrae localmente i dati di sessione da un HAR")
    har.add_argument("--account", required=True)
    har.add_argument("--har", required=True)
    benchmark = sub.add_parser("benchmark-privacy", help="misura il costo del broker con posta sintetica")
    benchmark.add_argument("--iterations", type=int, default=200)
    benchmark.add_argument("--body-kib", type=int, default=16)
    benchmark.add_argument("--budget-ms", type=float, default=25)
    broker = sub.add_parser("broker", help="avvia il broker locale attendibile")
    broker.add_argument("--address")
    broker.add_argument("--auth-file")
    mcp = sub.add_parser("mcp", help="avvia il gateway MCP pseudonimizzato su stdio")
    mcp.add_argument("--broker-address", required=True)
    mcp.add_argument("--broker-auth-file", required=True)
    sub.add_parser("broker-info", help="mostra endpoint e file di autenticazione del gateway")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        destination = Path(args.config)
        if destination.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite {destination}; pass --force")
        example = files("work_assistant").joinpath("templates/work-assistant.example.toml")
        content = example.read_text(encoding="utf-8")
        data_line = f'data_dir = "{default_data_dir().as_posix()}"\n'
        content = content.replace("schema_version = 1\n", f"schema_version = 1\n{data_line}", 1)
        destination.write_text(content, encoding="utf-8")
        _emit({"created": str(destination), "data_dir": str(default_data_dir())})
        return 0
    if args.command == "mcp":
        from work_assistant.mcp_server import run

        run(args.broker_address, args.broker_auth_file)
        return 0
    if args.command == "broker":
        run_broker(args.config, args.address, args.auth_file)
        return 0
    if args.command == "onboarding-plan":
        _emit(onboarding_plan(args.provider))
        return 0
    if args.command == "benchmark-privacy":
        _emit(benchmark_privacy(args.iterations, args.body_kib, args.budget_ms))
        return 0
    if args.command == "setup":
        from work_assistant.setup import SetupAborted, run_setup

        try:
            run_setup(Path(args.config), demo=args.demo)
        except SetupAborted as exc:
            print(exc)
            return 1
        return 0
    if args.command == "doctor":
        from work_assistant.doctor import run_doctor

        return run_doctor(args.config, as_json=args.json)
    if args.command == "mcp-setup":
        from work_assistant.mcp_setup import run_mcp_setup

        return run_mcp_setup(args.config, args.client, apply=args.apply)
    app = WorkAssistant(load_config(args.config))
    if args.command == "sync":
        _emit(app.sync(args.account))
    elif args.command == "list":
        _emit(app.archive.list_messages(args.account, args.limit))
    elif args.command == "show":
        message = app.archive.get_message(args.account, args.id)
        if message is None:
            raise SystemExit("message not found")
        _emit(message)
    elif args.command == "attachment-text":
        _emit(app.attachment_text(args.account, args.id, args.attachment_id))
    elif args.command == "attachment-capabilities":
        _emit(app.attachment_capabilities())
    elif args.command == "artifact-show":
        artifact = app.archive.get_local_artifact(args.id)
        if artifact is None:
            raise SystemExit("artifact not found")
        _emit(artifact)
    elif args.command == "draft-candidate":
        body = _read_body_file(args.body_file)
        draft_id = app.archive.create_draft_candidate(
            args.account, args.to, args.subject, body, args.in_reply_to
        )
        _emit({"draft_candidate_id": draft_id, "status": "local_candidate", "sent": False})
    elif args.command == "draft-on-provider":
        body = _read_body_file(args.body_file)
        try:
            _emit(
                app.save_provider_draft(args.account, args.to, args.subject, body, args.in_reply_to)
            )
        except Exception as exc:
            raise SystemExit(f"provider draft failed: {exc}") from exc
    elif args.command == "knowledge":
        from work_assistant._fs import owner_write

        view = app.archive.build_knowledge_view()
        target = app.config.data_dir / "knowledge.json"
        owner_write(target, (json.dumps(view, ensure_ascii=False, indent=2) + "\n").encode())
        _emit({"path": str(target), **view})
    elif args.command == "verify":
        _emit(app.archive.verify())
    elif args.command == "backup":
        from work_assistant.backup import create_backup

        try:
            _emit(create_backup(app.config, args.out, passphrase_env=args.passphrase_env))
        except BackupError as exc:
            raise SystemExit(f"backup failed: {exc}") from exc
    elif args.command == "restore":
        from work_assistant.backup import restore_backup

        try:
            _emit(restore_backup(args.backup_dir, args.data_dir, passphrase_env=args.passphrase_env))
        except BackupError as exc:
            raise SystemExit(f"restore failed: {exc}") from exc
    elif args.command == "backup-verify":
        from work_assistant.backup import verify_backup

        try:
            _emit(verify_backup(args.backup_dir, passphrase_env=args.passphrase_env))
        except BackupError as exc:
            raise SystemExit(f"backup proof failed: {exc}") from exc
    elif args.command == "onboarding-status":
        _emit(onboarding_status(app.config))
    elif args.command == "import-zimbra-har":
        _emit(import_zimbra_har(app.config, args.account, args.har))
    elif args.command == "broker-info":
        _emit(
            {
                "broker_address": default_broker_address(app.config),
                "broker_auth_file": str(default_auth_path(app.config)),
                "contains_mailbox_configuration": False,
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
