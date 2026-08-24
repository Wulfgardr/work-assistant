---
name: work-assistant
description: Operate a configured Work Assistant instance through MCP or CLI for mailbox inspection, local knowledge, and review-first draft candidates. Use when the user asks to work with email through Work Assistant; do not use it for unrelated mail clients.
---

# Work Assistant

Use the configured Work Assistant tools as the operational surface. The skill provides decision rules; it does not replace the MCP server or CLI.

For initial setup or a new account, read [references/onboarding.md](references/onboarding.md).
Before exposing mail content to an agent, read [references/privacy.md](references/privacy.md).

## Select the account

Use `mail_accounts` before mailbox work when the user did not identify an account. Do not combine similarly named accounts or infer that a shared account is the user's personal account.

## Work from local evidence

Use `mail_list` to narrow the scope, then `mail_get` for the exact message. Call `mail_sync` only when the user asks for current provider data or when freshness is necessary and the configured adapter supports acquisition.

Separate message content, derived knowledge and inference. `mail_knowledge` is a rebuildable view; it is not the provider source of truth or a complete backup.

## Preserve authority

- A request to inspect, summarize or propose text does not authorize provider mutation.
- `mail_draft_candidate` creates local proposed content only. Report its ID and `sent: false`.
- Do not claim that a draft exists at the provider unless an adapter-specific tool writes it and a provider readback confirms it.
- Do not send email unless a separately installed provider capability explicitly supports sending and the user authorizes the exact message in the current turn.

## Protect data

Return only the message content needed for the request. Do not place real messages, identities, credentials or attachments in source code, tests, public issues or external research.

When an archive or recovery claim matters, call `mail_verify_archive` and describe exactly what it proves. SQLite integrity and payload hashes do not prove that a backup can be restored.
