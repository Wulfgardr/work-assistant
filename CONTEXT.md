# Work Assistant domain

Work Assistant turns provider messages into a local, reviewable operational workspace for a person or an AI agent.

## Language

**Account**:
A configured mailbox identity handled as an independent source.
_Avoid_: Tenant, inbox

**Provider adapter**:
A component that reads from or writes to one email service through a stable Work Assistant contract.
_Avoid_: Provider, integration

**Local archive**:
The normalized, integrity-checked local record of material acquired from configured accounts.
_Avoid_: Tesseract, backup

**Knowledge view**:
A rebuildable projection of contacts and interactions derived from the local archive.
_Avoid_: Backup, source of truth

**Draft candidate**:
Proposed email content stored locally until a person authorizes a provider-side draft.
_Avoid_: Draft, sent message

**Agent surface**:
A structured interface, such as MCP, through which an agent inspects or operates Work Assistant.
_Avoid_: Skill

**Skill**:
Instructions that teach an agent how to use Work Assistant within its authority boundaries.
_Avoid_: Tool, plugin
