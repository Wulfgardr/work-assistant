# work-assistant-graph

Experimental **read-only** Microsoft Graph adapter for Work Assistant (Exchange Online / M365 mail). Delegated `Mail.Read` only, via OAuth2 device code flow: no passwords, no client secrets, no shared credentials.

## Install

```bash
python -m pip install ./adapters/graph
```

Registration happens through the `work_assistant.providers` entry point group (`graph` and `m365`).

## Configure

Register an app once in Microsoft Entra with:

- type: public client (mobile & desktop);
- delegated permission: `Mail.Read` (plus `offline_access` for refresh tokens);
- no client secret, no redirect URI beyond the defaults.

```toml
[accounts.office]
provider = "graph"
address = "alex@example.test"
client_id = "00000000-0000-0000-0000-000000000000"
tenant = "common"
token_file = "/secure/path/office.graph.token.json"
```

`tenant` accepts `common`, `organizations`, a tenant id, or a verified domain. Use the narrowest value that covers the account.

## Sign in

The person approves access in their own browser; tokens stay in the local file:

```bash
work-assistant-graph-login --config work-assistant.toml --account office
```

The command prints only the server-provided verification URI and user code. The token cache (`0600`, outside any agent workspace) is refreshed silently by the adapter.

## Boundaries

- Read-only: `save_draft` refuses; sync never marks messages as read.
- Only `fileAttachment` parts expose bytes; nested or reference attachments stay metadata-only.
- Attachment bytes are returned to the core only; derived pseudonymized text is what crosses the broker.
- A dedicated security review is still required before production use (see `docs/security/DAYBREAK-REVIEW.md` in the core repository).

## Develop

Use only synthetic fixtures. Run the adapter tests without installing anything, from the repository root:

```bash
PYTHONPATH=src:adapters/graph/src python -m pytest adapters/graph/tests -q
```
