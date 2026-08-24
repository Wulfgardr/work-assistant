# Implementation handoff: isolated broker

## Selected policy

- `mode = "off"`: no transformation; configuration must report cloud exposure.
- `mode = "all"`: every agent-visible message is pseudonymized.
- `mode = "selective"`: ordered sender rules choose `pseudonymize` or `allow_raw`; `default_action` is mandatory.
- Global entity registry replacements apply to all modes except `off`.

## Work packages

1. Parse and validate privacy configuration without loading secrets.
2. Create workspace-local aliases with keyed stable identifiers.
3. Store reversal values with authenticated encryption and owner-only permissions.
4. Run raw archive operations inside a broker using Unix sockets on macOS/Linux and named pipes on Windows.
5. Expose only filtered list, get, knowledge, draft-candidate, sync and integrity methods.
6. Connect MCP tools using only endpoint and authentication-file settings; never load mailbox configuration in the gateway.
7. Benchmark synthetic workloads and document measured scope.

## Acceptance criteria

- No protected clear value appears in broker responses or gateway logs.
- Alias restoration rejects unknown tokens and occurs only while creating a local artifact.
- Rules are deterministic, first-match and reported with each payload.
- The broker never falls back from `all` or `selective` to `off`.
- Tests and benchmark fixtures contain synthetic data only.
- Deployment instructions keep broker storage outside the agent-readable workspace.

## Rollback

Stop the gateway and broker, preserve the archive and encrypted vault, and restore the previous local-only command. Do not delete the vault while alias-bearing drafts or analyses still exist.
