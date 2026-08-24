# Security Hardening Review: Agent data pseudonymization

## Evidence Basis

I inspected the current MCP, archive and configuration boundaries at commit `ffdd499`. The archive is deliberately local, but the MCP server currently returns message content directly. The evidence is defined in [context.md](context.md).

## Constraints

We need reversible aliases, multi-account continuity, configurable sender policies and useful drafts. A cloud model must not receive the reversal map. Users may disable the feature, but the configuration must make that exposure explicit. No latency budget was supplied, so performance claims require a synthetic benchmark.

## Opportunity Portfolio

| Opportunity | Evidence | Options | Recommendation | Proposal |
| --- | --- | --- | --- | --- |
| Separate clear mail from the agent boundary | Raw MCP responses and co-located archive (`E001`–`E005`) | Inline filter; isolated broker; local-model-only | Isolated broker with `off`, `all` and `selective` policies | [Agent privacy boundary](proposals/agent-privacy-boundary.md) |

## Recommendation Summary

We selected the isolated broker. It keeps clear data, alias mapping and restoration in a trusted local process. The MCP gateway receives only policy-filtered payloads and returns alias-bearing draft candidates to the broker. Inline filtering remains useful as defense in depth, but it cannot protect data when an agent can read the archive and key directly.

## Next Decisions

- Deployment must keep the broker data directory outside the agent-readable workspace.
- Sender rules use explicit `pseudonymize` and `allow_raw` actions.
- Entity registry entries apply globally so an allowed message cannot casually reveal a protected person mentioned elsewhere.

