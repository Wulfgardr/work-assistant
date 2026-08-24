# Contesto delle evidenze

Radice analizzata: checkout locale `work-assistant-public` al commit `ffdd49983783506b2f4fc5b7310421b7969ecab7`.

| ID | Fonte | SHA-256 | Rilevanza |
| --- | --- | --- | --- |
| `E001` | `src/work_assistant/mcp_server.py` | `2cb82c2bfa75bce25e89eab5c375458c7e4786a89eefb5ba465b7af9f758956b` | MCP restituiva indirizzi, oggetti e corpi in chiaro. |
| `E002` | `src/work_assistant/archive.py` | `d3c25a9efe0a435af925d0e2bffa56ff45892208368ec3f5e83755dcf75b16bf` | L'archivio conserva intenzionalmente record locali in chiaro. |
| `E003` | `src/work_assistant/config.py` | `dae762beb5a684d7518a1218859afe2af24ec392832977a77c24027d0c8fb694` | Non esisteva un contratto di riservatezza. |
| `E004` | `README.md` | `00167b6c622879f67a4448e5d5549d195f4409801838b888867a97458252d122` | L'uso con agenti puntava al processo MCP diretto. |
| `E005` | `SECURITY.md` | `24b35b2d97bf8dd47cde9b215f3a35971b0ac05eedf81987a5b67dc698068a0c` | Le indicazioni non creavano una separazione di processo. |

Digest della raccolta: `adf157f16efff48e1d34eba864fcec9fac951f8fd217ebc0c17f6b3a2dc35a76`.

L'analisi non ha usato messaggi, credenziali o sessioni reali. Al momento della proposta non esisteva una misura delle prestazioni.
