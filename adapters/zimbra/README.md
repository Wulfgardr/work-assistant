# work-assistant-zimbra

Experimental Zimbra/Carbonio adapter for Work Assistant: read plus standalone drafts, never sends. Request shapes follow the published SOAP reference (`SearchRequest`, `GetMsgRequest`, `SaveDraftRequest`, content servlet), but server versions differ: verify against the target host before trusting any sync.

## Install

```bash
python -m pip install ./adapters/zimbra
```

Registration happens through the `work_assistant.providers` entry point group (`zimbra` and `carbonio`).

## Configure

```toml
[accounts.work]
provider = "zimbra"
host = "mail.example.test"
address = "alex@example.test"
session_file = "/secure/path/work.session.json"
```

Create the session file locally with the core command (never paste it anywhere):

```bash
work-assistant --config work-assistant.toml import-zimbra-har \
  --account work \
  --har /percorso/locale/session.har
```

## Security boundaries

- HTTPS only: plain HTTP hosts are refused, TLS verification stays on.
- HTTPS responses are limited to 25 MiB before parsing; injected SOAP transports are checked too.
- Search dates use an explicit `en_US` locale; `after:` excludes the named day. `since` accepts an inclusive UTC date or an exclusive timestamp with a timezone. Partial or duplicated search pages fail without returning a partial mailbox.
- Search and message reads preserve read flags. Session expiry during a body read stops synchronization.
- `save_draft` verifies the Drafts folder before writing, then reads the same ID and checks its folder, draft flag, recipients, subject and plain body. Reply drafts remain unsupported. An uncertain save/readback must be inspected in webmail; do not repeat the write automatically.
- Session material stays in the local file (`0600`, outside any agent workspace).
- Attachment bytes are returned to the core only; derived pseudonymized text is what crosses the broker.
- A dedicated security review is still required before production use (see `docs/security/DAYBREAK-REVIEW.md` in the core repository).

These source-level reliability fixes were adapted from the local Work Assistant implementation. No private source history, operational configuration, mailbox data or experimental Events activation is included. Synthetic tests do not establish compatibility with a live server.

## Real-server validation

Follow [`../VALIDATION.md`](../VALIDATION.md) with a dedicated synthetic test account before trusting any sync.

## Develop

Use only synthetic fixtures. Run the adapter tests without installing anything, from the repository root:

```bash
PYTHONPATH=src:adapters/zimbra/src python -m pytest adapters/zimbra/tests -q
```
