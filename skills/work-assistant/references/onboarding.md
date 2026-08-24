# Adaptive onboarding

Use this procedure when the user asks to configure Work Assistant or add an account.

1. Call `mail_onboarding_plan` for the named provider.
2. Explain which steps belong to the agent, human and local CLI.
3. Collect only non-secret settings such as account name, email address and host.
4. Ask the human to complete login and 2FA directly in the provider's browser interface.
5. For Zimbra or Carbonio browser-session authentication, tell the human to export the HAR locally and run `work-assistant import-zimbra-har`. Never ask for the HAR path through MCP and never ask the user to paste HAR content into chat.
6. Call `mail_onboarding_status`. It returns only booleans and adapter state.
7. Stop if the adapter is unavailable, session material is missing, TLS verification fails or provider permissions exceed the reviewed scope.

Do not automate trusted-device enrollment. Do not request a password, OTP, token, cookie value or complete mailbox export in a prompt.
