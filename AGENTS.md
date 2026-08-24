# Work Assistant contributor instructions

- Keep the public core provider-neutral. Put service-specific behavior in provider adapters.
- Use synthetic identities, messages and attachments in source, tests, screenshots and documentation.
- Never commit credentials, HAR files, cookies, tokens, mailbox exports or runtime databases.
- Keep inspection, local writes, provider-side drafts and sending as separate capabilities.
- The public core must not expose a send-email tool.
- Treat the knowledge view as derived data, not as the provider source of truth or a verified backup.
- Cloud-backed agents must use the MCP gateway through the privacy broker. Do not give them direct access to the broker data directory or raw CLI output.
- Call the feature reversible pseudonymization, never guaranteed anonymization.
- Run `pytest`, `python scripts/privacy_check.py` and the skill validator before committing.
