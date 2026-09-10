# work-assistant-graph

Experimental Microsoft Graph adapter for Work Assistant (Exchange Online / M365 mail): read plus provider drafts, never sends. Delegated `Mail.ReadWrite` only, via OAuth2 device code flow: no passwords, no client secrets, no shared credentials.

## Install

```bash
python -m pip install ./adapters/graph
```

Registration happens through the `work_assistant.providers` entry point group (`graph` and `m365`).

## Configure

Register an app once in Microsoft Entra with:

- type: public client (mobile & desktop);
- delegated permission: `Mail.ReadWrite` (plus `offline_access` for refresh tokens);
- enable **Allow public client flows** under Authentication;
- select supported account types matching the target account and tenant;
- no client secret, no redirect URI beyond the defaults.

`Mail.ReadWrite` is required for provider drafts and also permits mail updates and deletion. It does not grant sending; never add `Mail.Send`. Existing installations that used `Mail.Read` must update the app permission and run login again to obtain consent. Tenant policy may require administrator approval.

See [Microsoft permissions](https://learn.microsoft.com/en-us/graph/api/user-post-messages?view=graph-rest-1.0) and [device flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code).

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

- Read plus drafts, never sends: `save_draft` creates drafts (standalone or reply); sync never marks messages as read.
- Only `fileAttachment` parts expose bytes; nested or reference attachments stay metadata-only.
- Attachment bytes are returned to the core only; derived pseudonymized text is what crosses the broker.
- A dedicated security review is still required before production use (see `docs/security/DAYBREAK-REVIEW.md` in the core repository).

## Real-server validation

Follow [`../VALIDATION.md`](../VALIDATION.md) with a dedicated synthetic test account before trusting any sync.

## Develop

Use only synthetic fixtures. Run the adapter tests without installing anything, from the repository root:

```bash
PYTHONPATH=src:adapters/graph/src python -m pytest adapters/graph/tests -q
```
