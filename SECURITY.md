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
