from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


CLIENTS = ("codex", "claude-code", "claude-desktop", "vscode")


def server_command(broker_address: str, broker_auth_file: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "work_assistant",
        "mcp",
        "--broker-address",
        broker_address,
        "--broker-auth-file",
        broker_auth_file,
    ]


def _mcp_add_cmd(binary: str, command: list[str]) -> list[str]:
    return [binary, "mcp", "add", "work-assistant", "--", *command]


def codex_command(command: list[str]) -> list[str]:
    return _mcp_add_cmd("codex", command)


def claude_command(command: list[str]) -> list[str]:
    return _mcp_add_cmd("claude", command)


def desktop_snippet(command: list[str]) -> str:
    return json.dumps(
        {
            "mcpServers": {
                "work-assistant": {"command": command[0], "args": command[1:]}
            }
        },
        ensure_ascii=False,
        indent=2,
    )


def _shell(words: list[str]) -> str:
    return " ".join(f"'{word}'" if " " in word else word for word in words)


def broker_running(config) -> bool:
    from work_assistant.broker import BrokerClient, default_auth_path, default_broker_address

    try:
        BrokerClient(
            default_broker_address(config), default_auth_path(config), timeout=1
        ).call("privacy_status")
        return True
    except Exception:
        return False


def run_mcp_setup(config_path: str | Path, client: str, *, apply: bool = False) -> int:
    from work_assistant.broker import default_auth_path, default_broker_address
    from work_assistant.config import load_config

    if client not in CLIENTS:
        print(f"Client non supportato: {client}. Scegli tra: {', '.join(CLIENTS)}.")
        return 2
    config = load_config(config_path)
    address = default_broker_address(config)
    auth_file = str(default_auth_path(config))
    command = server_command(address, auth_file)
    if not broker_running(config):
        print("Il broker non è attivo: avvialo prima in un terminale dedicato.")
        print(f"  work-assistant --config {config.path} broker")
        print("Poi registra il server MCP.")
    if client == "codex":
        full = codex_command(command)
        binary = shutil.which("codex")
    elif client == "claude-code":
        full = claude_command(command)
        binary = shutil.which("claude")
    else:
        binary = None
    if client in {"claude-desktop", "vscode"}:
        where = "claude_desktop_config.json (sezione mcpServers)" if client == "claude-desktop" else ".vscode/mcp.json (sezione servers)"
        print(f"Copia questo blocco in {where}:")
        print(desktop_snippet(command))
        return 0
    if apply and binary:
        completed = subprocess.run(full, capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            print(f"Registrazione fallita: {completed.stderr.strip() or completed.stdout.strip()}")
            return 1
        print("Server work-assistant registrato. Chiedi all'agente di usarlo senza inviare nulla.")
        return 0
    print("Esegui questo comando:")
    print(f"  {_shell(full)}")
    return 0
