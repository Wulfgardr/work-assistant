# Agent privacy

Read this reference before using mail content with an agent.

1. Call `mail_privacy_status` before the first content request.
2. If mode is `off`, tell the user that agent-visible mail may be sent to the model provider. Do not silently continue with sensitive content.
3. In `all` mode, use only aliases returned by Work Assistant. Never invent or edit an alias.
4. In `selective` mode, inspect `_privacy.action` on every result. `allow_raw` means the payload was intentionally not pseudonymized for that sender.
5. Create draft candidates with the returned aliases. The broker restores them locally and rejects unknown or malformed aliases.
6. Use `mail_local_artifact` for alias-bearing analyses, summaries or contact notes that must be restored locally. The tool returns only an opaque local ID.
7. Do not use raw CLI `list`, `show`, `knowledge`, `artifact-show` or direct SQLite reads from a cloud-backed agent.

Pseudonymization reduces direct identifier disclosure. It does not guarantee anonymity or remove identifying context from unmatched prose.
