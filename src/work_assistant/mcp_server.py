from __future__ import annotations

from typing import Any

from work_assistant.broker import BrokerClient
from work_assistant.onboarding import onboarding_plan


def create_server(
    broker_address: str,
    broker_auth_file: str,
):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("MCP support is not installed; run pip install '.[mcp]'") from exc

    client = BrokerClient(broker_address, broker_auth_file)
    mcp = FastMCP("work-assistant")

    @mcp.tool(name="mail_accounts")
    def mail_accounts() -> list[dict[str, str]]:
        """List configured account names, provider adapters, and addresses."""
        return client.call("accounts")

    @mcp.tool(name="mail_onboarding_plan")
    def mail_onboarding_plan(provider: str) -> dict[str, Any]:
        """Return an adaptive human-agent setup plan without requesting secrets."""
        return onboarding_plan(provider)

    @mcp.tool(name="mail_onboarding_status")
    def mail_onboarding_status() -> dict[str, Any]:
        """Inspect account setup state without reading or returning secret values."""
        return client.call("onboarding_status")

    @mcp.tool(name="mail_sync")
    def mail_sync(account: str) -> dict[str, object]:
        """Acquire messages for one account and update the local archive."""
        return client.call("sync", account=account)

    @mcp.tool(name="mail_list")
    def mail_list(account: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        """List message metadata from the local archive."""
        return client.call("list", account=account, limit=max(1, min(limit, 100)))

    @mcp.tool(name="mail_get")
    def mail_get(account: str, message_id: str) -> dict[str, Any]:
        """Read one complete message from the local archive."""
        return client.call("get", account=account, message_id=message_id)

    @mcp.tool(name="mail_draft_candidate")
    def mail_draft_candidate(
        account: str,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> dict[str, object]:
        """Store a local draft candidate. This tool never writes to a provider or sends mail."""
        return client.call(
            "draft_candidate",
            account=account,
            to=to,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
        )

    @mcp.tool(name="mail_knowledge")
    def mail_knowledge() -> dict[str, object]:
        """Build a derived contact and interaction view from the local archive."""
        return client.call("knowledge")

    @mcp.tool(name="mail_local_artifact")
    def mail_local_artifact(kind: str, title: str, body: str) -> dict[str, Any]:
        """Restore known aliases and store an analysis, summary, or contact note locally."""
        return client.call("local_artifact", kind=kind, title=title, body=body)

    @mcp.tool(name="mail_verify_archive")
    def mail_verify_archive() -> dict[str, object]:
        """Run SQLite integrity and payload hash checks."""
        return client.call("verify")

    @mcp.tool(name="mail_privacy_status")
    def mail_privacy_status() -> dict[str, Any]:
        """Report active privacy mode and rule counts without keys or clear aliases."""
        return client.call("privacy_status")

    return mcp


def run(
    broker_address: str,
    broker_auth_file: str,
) -> None:
    create_server(broker_address, broker_auth_file).run()
