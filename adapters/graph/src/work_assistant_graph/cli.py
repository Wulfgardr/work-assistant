from __future__ import annotations

import argparse
import json

from work_assistant_graph.auth import DeviceFlow, GraphAuthError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="work-assistant-graph-login")
    parser.add_argument("--config", default="work-assistant.toml")
    parser.add_argument("--account", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    from work_assistant.config import load_config

    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    if args.account not in config.accounts:
        raise SystemExit(f"unknown account {args.account!r}")
    account = config.accounts[args.account]
    if account.provider not in {"graph", "m365"}:
        raise SystemExit(f"account {args.account!r} is not a graph account")
    client_id = str(account.options.get("client_id") or "").strip()
    token_file = str(account.options.get("token_file") or "").strip()
    tenant = str(account.options.get("tenant") or "common").strip()
    if not client_id or not token_file:
        raise SystemExit("account requires client_id and token_file")
    try:
        result = DeviceFlow(client_id, token_file, tenant=tenant).login()
    except GraphAuthError as exc:
        raise SystemExit(f"graph login failed: {exc}") from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
