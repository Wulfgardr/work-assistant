# Platform support

Work Assistant targets Python 3.11 or later on Windows, Linux and macOS.

## Shared behavior

- one configuration and policy schema;
- SQLite local archive;
- AES-GCM alias vault and HMAC-derived pseudonyms;
- authenticated JSON broker protocol;
- identical MCP tools and CLI commands;
- synthetic privacy benchmark.

## Native broker transport

| Platform | Transport | Current evidence |
| --- | --- | --- |
| macOS | Unix-domain socket | Locally tested, including 200-iteration benchmark |
| Linux | Unix-domain socket | CI matrix configured; remote run required before verified claim |
| Windows | Named pipe | CI matrix configured; remote run required before verified claim |

The broker does not listen on TCP. Platform-specific deployment must keep the clear archive and alias key outside the agent-readable workspace while allowing access to the broker endpoint and authentication file.

## Installation differences

- macOS/Linux virtual environment executable: `.venv/bin/work-assistant`.
- Windows virtual environment executable: `.venv\Scripts\work-assistant.exe`.
- macOS/Linux broker endpoints use owner-only runtime directories and socket files.
- Windows uses an authenticated named pipe; deployment should also apply appropriate account and ACL isolation to the broker data directory.

Do not describe Linux or Windows as verified until their GitHub Actions jobs pass on the published revision.
