# ADR 0001: Candidate open-source license

- Status: Proposed
- Date: 2026-08-24

## Context

Work Assistant needs an explicit license before public distribution. A permissive license lowers adoption friction; a copyleft license better preserves public access to derivatives.

## Candidate decision

Use MIT for the first public release because the provider adapter ecosystem benefits from low integration friction.

## Alternatives

- Apache-2.0 adds an explicit patent grant with more text.
- AGPL-3.0 requires network-served derivatives to publish corresponding source and better protects the commons.

## Consequences

MIT permits proprietary derivatives and hosted services. Confirm or replace this candidate before adding a public remote or publishing a release.
