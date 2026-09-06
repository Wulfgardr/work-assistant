# work-assistant-zimbra

Experimental **read-only** Zimbra/Carbonio adapter for Work Assistant. Request shapes follow the published SOAP reference (`SearchRequest`, `GetMsgRequest`, content servlet), but server versions differ: verify against the target host before trusting any sync.

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
- No side effects: search never marks messages as read; `save_draft` refuses.
- Session material stays in the local file (`0600`, outside any agent workspace).
- Attachment bytes are returned to the core only; derived pseudonymized text is what crosses the broker.
- A dedicated security review is still required before production use (see `docs/security/DAYBREAK-REVIEW.md` in the core repository).

## Develop

Use only synthetic fixtures. Run the adapter tests without installing anything, from the repository root:

```bash
PYTHONPATH=src:adapters/zimbra/src python -m pytest adapters/zimbra/tests -q
```
