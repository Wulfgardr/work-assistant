from __future__ import annotations

from typing import Any

from work_assistant.config import load_config
from work_assistant.onboarding import onboarding_plan, onboarding_status
from work_assistant.service import WorkAssistant


def create_server(config_path: str):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("MCP support is not installed; run pip install -e '.[mcp]'") from exc

    app = WorkAssistant(load_config(config_path))
    mcp = FastMCP("work-assistant")

    @mcp.tool(name="mail_accounts")
    def mail_accounts() -> list[dict[str, str]]:
        """List configured account names, provider adapters, and addresses."""
        return [
            {"name": item.name, "provider": item.provider, "address": item.address}
            for item in app.config.accounts.values()
        ]

    @mcp.tool(name="mail_onboarding_plan")
    def mail_onboarding_plan(provider: str) -> dict[str, Any]:
        """Return an adaptive human-agent setup plan without requesting secrets."""
        return onboarding_plan(provider)

    @mcp.tool(name="mail_onboarding_status")
    def mail_onboarding_status() -> dict[str, Any]:
        """Inspect account setup state without reading or returning secret values."""
        return onboarding_status(app.config)

    @mcp.tool(name="mail_sync")
    def mail_sync(account: str) -> dict[str, object]:
        """Acquire messages for one account and update the local archive."""
        return app.sync(account)

    @mcp.tool(name="mail_list")
    def mail_list(account: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        """List message metadata from the local archive."""
        return app.archive.list_messages(account, max(1, min(limit, 100)))

    @mcp.tool(name="mail_get")
    def mail_get(account: str, message_id: str) -> dict[str, Any]:
        """Read one complete message from the local archive."""
        return app.archive.get_message(account, message_id) or {"error": "message_not_found"}

    @mcp.tool(name="mail_draft_candidate")
    def mail_draft_candidate(
        account: str,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> dict[str, object]:
        """Store a local draft candidate. This tool never writes to a provider or sends mail."""
        draft_id = app.archive.create_draft_candidate(account, to, subject, body, in_reply_to)
        return {"draft_candidate_id": draft_id, "status": "local_candidate", "sent": False}

    @mcp.tool(name="mail_knowledge")
    def mail_knowledge() -> dict[str, object]:
        """Build a derived contact and interaction view from the local archive."""
        return app.archive.build_knowledge_view()

    @mcp.tool(name="mail_verify_archive")
    def mail_verify_archive() -> dict[str, object]:
        """Run SQLite integrity and payload hash checks."""
        return app.archive.verify()

    return mcp


def run(config_path: str) -> None:
    create_server(config_path).run()
