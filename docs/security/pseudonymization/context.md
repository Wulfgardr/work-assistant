# Evidence context

Source root: local `work-assistant-public` checkout at `ffdd49983783506b2f4fc5b7310421b7969ecab7`.

| ID | Source | SHA-256 | Relevance |
| --- | --- | --- | --- |
| `E001` | `src/work_assistant/mcp_server.py` | `2cb82c2bfa75bce25e89eab5c375458c7e4786a89eefb5ba465b7af9f758956b` | MCP returns raw addresses, subjects and bodies. |
| `E002` | `src/work_assistant/archive.py` | `d3c25a9efe0a435af925d0e2bffa56ff45892208368ec3f5e83755dcf75b16bf` | The archive intentionally retains clear local records. |
| `E003` | `src/work_assistant/config.py` | `dae762beb5a684d7518a1218859afe2af24ec392832977a77c24027d0c8fb694` | Configuration has no privacy policy contract. |
| `E004` | `README.md` | `00167b6c622879f67a4448e5d5549d195f4409801838b888867a97458252d122` | Agent usage currently shares the direct MCP surface. |
| `E005` | `SECURITY.md` | `24b35b2d97bf8dd47cde9b215f3a35971b0ac05eedf81987a5b67dc698068a0c` | Existing guidance does not create a process boundary. |

Collection digest: `adf157f16efff48e1d34eba864fcec9fac951f8fd217ebc0c17f6b3a2dc35a76`.

No production messages, credentials or provider sessions were inspected. Performance had not been measured when the proposal was written.

