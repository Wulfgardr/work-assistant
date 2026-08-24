# Contributing

Keep changes small, provider-neutral and testable.

1. Use synthetic identities and messages only.
2. Do not commit exports, credentials, cookies, tokens or operational databases.
3. Keep provider behavior inside an adapter.
4. Keep the public core free of implicit network access.
5. Add tests for observable behavior and failure states.
6. Run `pytest` and `python scripts/privacy_check.py` before opening a pull request.

Sending email is outside the public core. Proposals to add provider-side writes must define an explicit capability, dry-run behavior, confirmation boundary and verification receipt.
