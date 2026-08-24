# Security policy

## Supported versions

Work Assistant is alpha software. Security fixes apply to the latest release only.

## Report a vulnerability

Open a private GitHub security advisory after the public repository exists. Do not include real messages, credentials, cookies, access tokens, personal data or regulated information in a report.

## Operating boundaries

- Keep configuration secrets and runtime data outside Git.
- Use synthetic messages in issues, tests and pull requests.
- Review an adapter's capabilities before enabling it.
- Treat provider-side drafts, flags, labels, moves, calendar changes and sending as separate permissions.
- Do not expose the local MCP process to a network without adding authentication and transport security.
- Verify backups by restoring them into an isolated workspace. A successful sync or SQLite integrity check is not restore proof.
- Keep HAR exports local. Never paste them into a prompt, issue or support message.

## Agent privacy broker

`privacy.mode = "all"` or `"selective"` requires the local broker. The MCP gateway has no raw fallback when the broker is unavailable.

For the broker to be a security boundary, keep `data_dir` outside every agent-readable workspace. Use an OS sandbox, separate container volume or equivalent access control that permits the gateway to reach only the broker endpoint and its authentication file. Running broker and shell-capable agent under the same unrestricted account protects against accidental MCP disclosure, but not against direct file reads.

The MCP gateway must not receive `work-assistant.toml`. Give it only the broker endpoint and authentication-file path reported by `broker-info`. The authentication key permits access only to the broker's filtered protocol; the broker exposes no raw-read or generic file operation.

The encrypted alias vault is pseudonymization, not irreversible anonymization. Unmatched free text, rare facts and writing style can remain identifying. `allow_raw` rules deliberately permit cloud-model exposure for matching senders.
