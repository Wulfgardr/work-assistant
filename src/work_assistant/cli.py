from __future__ import annotations

import argparse
from importlib.resources import files
import json
from pathlib import Path

from work_assistant.benchmark import benchmark_privacy
from work_assistant.broker import default_auth_path, default_broker_address, run_broker
from work_assistant.config import default_data_dir, load_config
from work_assistant.onboarding import import_zimbra_har, onboarding_plan, onboarding_status
from work_assistant.service import WorkAssistant


def _emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="work-assistant")
    parser.add_argument("--config", default="work-assistant.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="crea una configurazione locale dall'esempio")
    init.add_argument("--force", action="store_true")
    sync = sub.add_parser("sync", help="acquisisce i messaggi di un account configurato")
    sync.add_argument("--account", required=True)
    listing = sub.add_parser("list", help="elenca i messaggi archiviati localmente")
    listing.add_argument("--account")
    listing.add_argument("--limit", type=int, default=20)
    show = sub.add_parser("show", help="mostra un messaggio archiviato localmente")
    show.add_argument("--account", required=True)
    show.add_argument("--id", required=True)
    artifact = sub.add_parser("artifact-show", help="mostra un artefatto locale in chiaro")
    artifact.add_argument("--id", type=int, required=True)
    draft = sub.add_parser("draft-candidate", help="salva un candidato locale senza inviare")
    draft.add_argument("--account", required=True)
    draft.add_argument("--to", action="append", required=True)
    draft.add_argument("--subject", required=True)
    draft.add_argument("--body-file", required=True)
    draft.add_argument("--in-reply-to")
    sub.add_parser("knowledge", help="ricostruisce la vista di conoscenza locale")
    sub.add_parser("verify", help="controlla SQLite e gli hash dei messaggi")
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
    elif args.command == "artifact-show":
        artifact = app.archive.get_local_artifact(args.id)
        if artifact is None:
            raise SystemExit("artifact not found")
        _emit(artifact)
    elif args.command == "draft-candidate":
        body = Path(args.body_file).read_text(encoding="utf-8")
        draft_id = app.archive.create_draft_candidate(
            args.account, args.to, args.subject, body, args.in_reply_to
        )
        _emit({"draft_candidate_id": draft_id, "status": "local_candidate", "sent": False})
    elif args.command == "knowledge":
        view = app.archive.build_knowledge_view()
        target = app.config.data_dir / "knowledge.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(view, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _emit({"path": str(target), **view})
    elif args.command == "verify":
        _emit(app.archive.verify())
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
