<div align="center">

# Work Assistant

**Your archive stays local. Agent exposure is explicit. You stay in control.**

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
- **Privacy broker + MCP gateway** — clear data stays in the trusted local broker; the agent receives policy-filtered payloads.
- **Reversible pseudonyms** — stable workspace-local aliases are restored only while creating local artifacts.
- **Plain CLI** — inspect and operate the same core without an agent.
- **Review-first drafts** — the public core stores local draft candidates and reports `sent: false`.
- **Local restored artifacts** — analyses, summaries and contact notes return through the broker and are de-pseudonymized only in local storage.

```text
Codex / Claude
      │ pseudonymized MCP
      ▼
   MCP gateway
      │ authenticated local IPC
      ▼
   Privacy broker
      ├── clear local archive
      ├── encrypted alias vault
      ├── knowledge view
      └── local draft candidates
         │
   provider adapters
      ├── demo JSONL ✓
      ├── Zimbra      external adapter
      ├── Microsoft   community adapter
      └── Gmail/IMAP  community adapter
```

## Quick start

Requirements: Python 3.11 or later.

```bash
git clone https://github.com/your-account/work-assistant.git
cd work-assistant
python3 -m venv .venv
```

Activate the environment:

```bash
# macOS or Linux
source .venv/bin/activate
cp work-assistant.example.toml work-assistant.toml
```

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
Copy-Item work-assistant.example.toml work-assistant.toml
```

Then install on any platform:

```bash
python -m pip install .
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

The commands above are the local operator surface. Do not expose their raw output to a cloud-backed terminal agent. Agent use goes through the privacy broker and MCP gateway below.

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
python -m pip install '.[mcp]'
```

Start the trusted broker in a local terminal or service before starting the agent:

```bash
work-assistant --config work-assistant.toml broker
```

The broker uses an owner-only Unix socket on macOS/Linux and an authenticated named pipe on Windows. If it is unavailable, the MCP gateway fails closed and does not read the archive directly.

### Codex

Register the local MCP server from the repository root:

```bash
work-assistant --config work-assistant.toml broker-info

codex mcp add work-assistant -- \
  "$PWD/.venv/bin/work-assistant" \
  mcp \
  --broker-address '<value from broker-info>' \
  --broker-auth-file '<value from broker-info>'
```

Do not pass `work-assistant.toml` to the gateway. Only the broker loads mailbox configuration. The gateway receives the safe IPC endpoint and its authentication file.

On Windows, replace `.venv/bin/work-assistant` with `.venv\Scripts\work-assistant.exe` in client configuration.

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
        "mcp",
        "--broker-address",
        "<value from broker-info>",
        "--broker-auth-file",
        "<value from broker-info>"
      ]
    }
  }
}
```

For Claude Code, the equivalent registration is:

```bash
claude mcp add work-assistant -- \
  "$PWD/.venv/bin/work-assistant" \
  mcp \
  --broker-address '<value from broker-info>' \
  --broker-auth-file '<value from broker-info>'
```

### Intelligent use from a terminal

The `work-assistant` CLI is deterministic; it does not contain a model. A terminal agent must connect through MCP so the broker can apply privacy policy. Raw CLI commands are for a trusted local human operator:

```bash
work-assistant --config work-assistant.toml list --account personal --limit 10
work-assistant --config work-assistant.toml show --account personal --id p-001
```

To store a proposed reply manually without writing to a provider:

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

[privacy]
mode = "all"
default_action = "pseudonymize"
entities_path = "./private/privacy-entities.json"

[accounts.personal]
provider = "demo"
source = "./examples/demo-mailbox.jsonl"
address = "alex@example.test"
```

Keep credentials, exports and operational data outside Git. Use environment variables or an adapter-specific secret store for real providers.

### Privacy modes

- `off` — no transformation. Agent-visible content may reach the model provider.
- `all` — pseudonymize every sender before content crosses the broker boundary.
- `selective` — use ordered sender rules; the first match wins.

Use explicit actions instead of ambiguous opt-in/opt-out labels:

```toml
[privacy]
mode = "selective"
default_action = "pseudonymize"
entities_path = "./private/privacy-entities.json"

[[privacy.sender_rules]]
pattern = "newsletter@example.test"
action = "allow_raw"

[[privacy.sender_rules]]
pattern = "*@sensitive.example"
action = "pseudonymize"
```

The optional entity registry protects names or organizations wherever they occur, including messages from an `allow_raw` sender:

```json
{
  "PERSON": ["Alex Example"],
  "ORG": ["Example Clinic"]
}
```

This is reversible pseudonymization, not guaranteed anonymity. Rare facts, unmatched prose and writing style can still identify a person.

Model-generated analyses can return through `mail_local_artifact`. The broker accepts only `analysis`, `summary` or `contact_note`, restores known aliases, stores the clear result locally and returns only an artifact ID. A trusted operator can inspect it with `work-assistant artifact-show --id ID`.

### Machine-specific privacy benchmark

Run a synthetic benchmark before choosing a mode:

```bash
work-assistant benchmark-privacy \
  --iterations 200 \
  --body-kib 16 \
  --budget-ms 25
```

It compares broker round trips for `off`, `all`, selective `allow_raw` and selective pseudonymization. The recommendation uses the overhead budget you provide. It excludes provider, model and internet latency and never reads real mail. Performance does not make `allow_raw` safe; it only helps you understand the local cost.

One measured example is available in [`docs/benchmarks/privacy-broker-macos-2026-08-24.md`](docs/benchmarks/privacy-broker-macos-2026-08-24.md). Always prefer a fresh run on the target machine.

## Operating systems

The core, policy, vault, benchmark and broker use Python APIs available on Windows, Linux and macOS:

| Platform | Local broker transport | Isolation direction |
| --- | --- | --- |
| Windows | Authenticated named pipe | Broker service plus agent sandbox/container |
| Linux | Owner-only Unix socket | Service sandbox or container with isolated data volume |
| macOS | Owner-only Unix socket | Sandboxed service or container with isolated data volume |

The broker data directory must remain outside the agent-readable workspace. The code is designed for all three platforms; the GitHub CI matrix is the publication gate for claiming verified cross-platform behavior.

See [`docs/PLATFORMS.md`](docs/PLATFORMS.md) for the distinction between designed and currently verified support.

## Add a provider

Implement the small `MailProvider` protocol in [`src/work_assistant/providers/base.py`](src/work_assistant/providers/base.py), then register the adapter in `provider_for()`.

An adapter owns provider-specific authentication, pagination and identifiers. The core owns normalized messages, local integrity, knowledge views and draft candidates. See [`docs/PROVIDER_ADAPTERS.md`](docs/PROVIDER_ADAPTERS.md).

## Safety model

- The demo adapter is read-only.
- MCP runs over local `stdio`; the server opens no network port.
- Broker IPC uses Unix sockets or Windows named pipes, never a listening TCP port.
- Alias values are encrypted with AES-GCM; stable alias identifiers use keyed HMAC.
- `off`, `all` and ordered `selective` rules make model exposure explicit.
- `mail_draft_candidate` writes only to the local archive.
- Onboarding MCP tools never accept or return secret values.
- The public core exposes no send tool.
- Runtime data and common credential formats are ignored by Git.
- A knowledge view is derived data, not a backup or provider source of truth.

Before using real mail, read [`SECURITY.md`](SECURITY.md). Provider adapters must document their read and write capabilities explicitly.

## Status

This is an alpha foundation extracted from a working local-first system. The provider-neutral core, demo adapter, multi-account configuration, SQLite archive, privacy broker, encrypted alias vault, CLI and MCP gateway are implemented. Production provider adapters and attachment-content pseudonymization remain future work.

## Development

```bash
python -m pip install '.[dev,mcp]'
pytest
python scripts/privacy_check.py
work-assistant benchmark-privacy --iterations 50
```

MIT licensed. Contributions should use synthetic fixtures only.
