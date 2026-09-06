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
        """Elenca account configurati, adapter e indirizzi."""
        return client.call("accounts")

    @mcp.tool(name="mail_onboarding_plan")
    def mail_onboarding_plan(provider: str) -> dict[str, Any]:
        """Restituisce un piano persona-agente senza richiedere segreti."""
        return onboarding_plan(provider)

    @mcp.tool(name="mail_onboarding_status")
    def mail_onboarding_status() -> dict[str, Any]:
        """Controlla la configurazione senza leggere o restituire segreti."""
        return client.call("onboarding_status")

    @mcp.tool(name="mail_sync")
    def mail_sync(account: str) -> dict[str, object]:
        """Acquisisce i messaggi di un account e aggiorna l'archivio locale."""
        return client.call("sync", account=account)

    @mcp.tool(name="mail_list")
    def mail_list(account: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        """Elenca i metadati dei messaggi presenti nell'archivio locale."""
        return client.call("list", account=account, limit=max(1, min(limit, 100)))

    @mcp.tool(name="mail_get")
    def mail_get(account: str, message_id: str) -> dict[str, Any]:
        """Legge un messaggio completo dall'archivio locale."""
        return client.call("get", account=account, message_id=message_id)

    @mcp.tool(name="mail_draft_candidate")
    def mail_draft_candidate(
        account: str,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> dict[str, object]:
        """Salva un candidato locale. Non scrive sul provider e non invia email."""
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
        """Costruisce una vista derivata di contatti e interazioni."""
        return client.call("knowledge")

    @mcp.tool(name="mail_local_artifact")
    def mail_local_artifact(kind: str, title: str, body: str) -> dict[str, Any]:
        """Ripristina alias conosciuti e salva localmente un'analisi o una nota."""
        return client.call("local_artifact", kind=kind, title=title, body=body)

    @mcp.tool(name="mail_verify_archive")
    def mail_verify_archive() -> dict[str, object]:
        """Controlla integrità SQLite e hash dei payload."""
        return client.call("verify")

    @mcp.tool(name="mail_attachment_capabilities")
    def mail_attachment_capabilities() -> dict[str, Any]:
        """Riporta estrattori disponibili, stato OCR e limiti senza contenuti."""
        return client.call("attachment_capabilities")

    @mcp.tool(name="mail_attachment_text")
    def mail_attachment_text(account: str, message_id: str, attachment_id: str) -> dict[str, Any]:
        """Legge il testo derivato di un allegato. I byte originali non lasciano mai il broker."""
        return client.call(
            "attachment_text",
            account=account,
            message_id=message_id,
            attachment_id=attachment_id,
        )

    @mcp.tool(name="mail_privacy_status")
    def mail_privacy_status() -> dict[str, Any]:
        """Riporta modalità e numero di regole senza chiavi o alias in chiaro."""
        return client.call("privacy_status")

    return mcp


def run(
    broker_address: str,
    broker_auth_file: str,
) -> None:
    create_server(broker_address, broker_auth_file).run()
