<div align="center">

# Work Assistant

**Your email stays local. Your agent gets useful tools. You stay in control.**

Provider-neutral email operations for Codex, Claude and the command line.

[Quick start](#quick-start) · [Use with an agent](#use-with-an-agent) · [Add a provider](#add-a-provider) · [Safety model](#safety-model)

</div>

---

Work Assistant turns one or more mailboxes into a local, structured workspace. It gives an AI agent explicit tools to inspect messages, build context and prepare local draft candidates.

It is not an autonomous sender. The included public core never sends email.

## What you get

- **Multiple accounts** — each mailbox has its own name, address and provider adapter.
- **Local archive** — normalized messages are stored in SQLite with payload hashes.
- **Knowledge view** — contacts and interactions are rebuilt from the archive, not hidden in a model.
- **Agent-ready MCP server** — use the same tools from Codex, Claude or another MCP client.
- **Plain CLI** — inspect and operate the same core without an agent.
- **Review-first drafts** — the public core stores local draft candidates and reports `sent: false`.

```text
Codex / Claude / CLI
         │
      MCP or commands
         │
   Work Assistant core
      ├── local archive
      ├── knowledge view
      └── draft candidates
         │
   provider adapters
      ├── demo JSONL ✓
      ├── Zimbra      planned extraction
      ├── Microsoft   community adapter
      └── Gmail/IMAP  community adapter
```

## Quick start

Requirements: Python 3.11 or later.

```bash
git clone https://github.com/your-account/work-assistant.git
cd work-assistant
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp work-assistant.example.toml work-assistant.toml
```

Load the two synthetic mailboxes:

```bash
work-assistant --config work-assistant.toml sync --account personal
work-assistant --config work-assistant.toml sync --account team
work-assistant --config work-assistant.toml list
work-assistant --config work-assistant.toml knowledge
work-assistant --config work-assistant.toml verify
```

All runtime data is written to `./workspace/`, which Git ignores.

## Adaptive onboarding

Work Assistant can divide setup between the agent, the local CLI and the human:

```text
Agent: explain and diagnose → Human: login and 2FA → CLI: store secrets locally
```

Ask the MCP server for a provider-specific plan, or inspect it directly:

```bash
work-assistant onboarding-plan --provider demo
work-assistant onboarding-plan --provider zimbra
work-assistant --config work-assistant.toml onboarding-status
```

For Zimbra or Carbonio installations that authenticate through a browser session, complete login and 2FA in the browser, export the HAR locally, then run:

```bash
work-assistant --config work-assistant.toml import-zimbra-har \
  --account work \
  --har /local/path/session.har
```

The helper extracts only the required session cookie names into `workspace/secrets/`, applies owner-only permissions and never prints their values. It does not delete the HAR. Move or delete that sensitive export yourself after verification.

The agent can inspect onboarding status through MCP, but HAR files, passwords, OTPs and cookie values never pass through the model. The public repository prepares this safe setup boundary; a production Zimbra adapter is not bundled yet.

## Use with an agent

Install the MCP dependency:

```bash
python -m pip install -e '.[mcp]'
```

### Codex

Register the local MCP server from the repository root:

```bash
codex mcp add work-assistant -- \
  "$PWD/.venv/bin/work-assistant" \
  --config "$PWD/work-assistant.toml" mcp
```

Then ask Codex:

> Use Work Assistant. Sync the `personal` account, show the latest messages and prepare a local reply candidate for the project review. Do not send anything.

The optional skill is in [`skills/work-assistant`](skills/work-assistant). Copy or symlink it into your Codex skills directory if you want the operating rules to load automatically.

### Claude Desktop or Claude Code

Point an MCP configuration at the same executable:

```json
{
  "mcpServers": {
    "work-assistant": {
      "command": "/absolute/path/work-assistant/.venv/bin/work-assistant",
      "args": [
        "--config",
        "/absolute/path/work-assistant/work-assistant.toml",
        "mcp"
      ]
    }
  }
}
```

For Claude Code, the equivalent registration is:

```bash
claude mcp add work-assistant -- \
  "$PWD/.venv/bin/work-assistant" \
  --config "$PWD/work-assistant.toml" mcp
```

### Intelligent use from a terminal

The `work-assistant` CLI is deterministic; it does not contain a model. It becomes an intelligent surface when Codex CLI, Claude Code or another terminal agent calls it or connects through MCP.

Humans and agents therefore use the same local core:

```bash
work-assistant --config work-assistant.toml list --account personal --limit 10
work-assistant --config work-assistant.toml show --account personal --id p-001
```

To store a proposed reply without writing to a provider:

```bash
printf 'Thanks. I will review the note by Friday.\n' > reply.txt
work-assistant --config work-assistant.toml draft-candidate \
  --account personal \
  --to sam@example.test \
  --subject 'Re: Project review' \
  --in-reply-to p-001 \
  --body-file reply.txt
```

## Configuration

Each table below `[accounts]` is an independent mailbox:

```toml
schema_version = 1
data_dir = "./workspace"

[accounts.personal]
provider = "demo"
source = "./examples/demo-mailbox.jsonl"
address = "alex@example.test"
```

Keep credentials, exports and operational data outside Git. Use environment variables or an adapter-specific secret store for real providers.

## Add a provider

Implement the small `MailProvider` protocol in [`src/work_assistant/providers/base.py`](src/work_assistant/providers/base.py), then register the adapter in `provider_for()`.

An adapter owns provider-specific authentication, pagination and identifiers. The core owns normalized messages, local integrity, knowledge views and draft candidates. See [`docs/PROVIDER_ADAPTERS.md`](docs/PROVIDER_ADAPTERS.md).

## Safety model

- The demo adapter is read-only.
- MCP runs over local `stdio`; the server opens no network port.
- `mail_draft_candidate` writes only to the local archive.
- Onboarding MCP tools never accept or return secret values.
- The public core exposes no send tool.
- Runtime data and common credential formats are ignored by Git.
- A knowledge view is derived data, not a backup or provider source of truth.

Before using real mail, read [`SECURITY.md`](SECURITY.md). Provider adapters must document their read and write capabilities explicitly.

## Status

This is an alpha foundation extracted from a working local-first system. The provider-neutral core, demo adapter, multi-account configuration, SQLite archive, CLI and MCP surface are implemented. Production provider adapters and attachment blob storage remain future work.

## Development

```bash
python -m pip install -e '.[dev,mcp]'
pytest
python scripts/privacy_check.py
```

MIT licensed. Contributions should use synthetic fixtures only.
