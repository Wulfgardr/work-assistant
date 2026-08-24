# Adapter dei provider

Un adapter traduce un servizio email nel modello stabile di Work Assistant.

## Contratto richiesto

Implementa `MailProvider`:

```python
class MailProvider(Protocol):
    def list_messages(self, *, since: str | None = None) -> list[Message]: ...
    def save_draft(
        self,
        *,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> str: ...
```

Un adapter può rifiutare `save_draft`. L'adapter dimostrativo lo rifiuta.

## Responsabilità dell'adapter

- autenticazione e rinnovo dei token;
- paginazione e limiti del provider;
- conversione di identificativi e orari;
- acquisizione degli allegati e calcolo degli hash;
- descrizione esatta delle capacità di lettura e scrittura;
- verifica di ogni modifica applicata sul provider.

## Responsabilità del core

- instradamento tra più account;
- normalizzazione e archivio locale;
- controlli di integrità;
- vista di conoscenza derivata;
- candidati di risposta locali;
- contratti MCP e CLI.

## Registrazione

Aggiungi il pacchetto dell'adapter e registra il nome in `work_assistant.service.provider_for`. Mantieni le opzioni specifiche sotto la tabella dell'account in `work-assistant.toml`.

Non usare messaggi reali come fixture.
