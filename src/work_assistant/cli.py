from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from work_assistant.config import load_config
from work_assistant.onboarding import import_zimbra_har, onboarding_plan, onboarding_status
from work_assistant.service import WorkAssistant


def _emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="work-assistant")
    parser.add_argument("--config", default="work-assistant.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a local configuration from the example")
    init.add_argument("--force", action="store_true")
    sync = sub.add_parser("sync", help="acquire messages from one configured account")
    sync.add_argument("--account", required=True)
    listing = sub.add_parser("list", help="list locally archived messages")
    listing.add_argument("--account")
    listing.add_argument("--limit", type=int, default=20)
    show = sub.add_parser("show", help="show one locally archived message")
    show.add_argument("--account", required=True)
    show.add_argument("--id", required=True)
    draft = sub.add_parser("draft-candidate", help="store a local draft candidate; never sends")
    draft.add_argument("--account", required=True)
    draft.add_argument("--to", action="append", required=True)
    draft.add_argument("--subject", required=True)
    draft.add_argument("--body-file", required=True)
    draft.add_argument("--in-reply-to")
    sub.add_parser("knowledge", help="rebuild the local knowledge view")
    sub.add_parser("verify", help="verify SQLite and message payload hashes")
    plan = sub.add_parser("onboarding-plan", help="show the human-agent setup plan")
    plan.add_argument("--provider", required=True)
    sub.add_parser("onboarding-status", help="show setup state without secret values")
    har = sub.add_parser("import-zimbra-har", help="extract session material locally from a HAR")
    har.add_argument("--account", required=True)
    har.add_argument("--har", required=True)
    sub.add_parser("mcp", help="run the MCP server over stdio")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init":
        destination = Path(args.config)
        if destination.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite {destination}; pass --force")
        example = Path(__file__).resolve().parents[2] / "work-assistant.example.toml"
        shutil.copyfile(example, destination)
        _emit({"created": str(destination)})
        return 0
    if args.command == "mcp":
        from work_assistant.mcp_server import run

        run(args.config)
        return 0
    if args.command == "onboarding-plan":
        _emit(onboarding_plan(args.provider))
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
