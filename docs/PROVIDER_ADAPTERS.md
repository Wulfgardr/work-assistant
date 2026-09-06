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
    def fetch_attachment_bytes(self, message_id: str, attachment_id: str) -> bytes: ...
```

Un adapter può rifiutare `save_draft`. Gli adapter dimostrativo e maildir lo rifiutano perché sono di sola lettura; imap, graph e zimbra creano bozze senza mai inviare. L'invio resta fuori dal core pubblico.

`fetch_attachment_bytes` restituisce i byte grezzi detenuti dal provider. Gli adapter che non possono fornirli mantengono l'implementazione predefinita, che segnala `AttachmentNotAvailable`: il core riporta lo stato `provider_unsupported` invece di fallire in silenzio. I byte non vengono mai conservati nell'archivio né inoltrati al gateway: solo il testo derivato, pseudonimizzato, attraversa il broker.

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
- testo derivato degli allegati con cache rigenerabile;
- candidati di risposta locali;
- contratti MCP e CLI.

## Registrazione

Adapter integrati: `demo` (fixture JSONL sintetiche), `maildir` (cartella Maildir locale, senza rete) e `imap` (IMAP generico, solo TLS):

```toml
[accounts.local]
provider = "maildir"
path = "/percorso/locale/Maildir"
address = "alex@example.test"

[accounts.office]
provider = "imap"
host = "imap.example.test"
address = "alex@example.test"
secret_file = "/secure/path/office.imap.secret"
# username = "alex@example.test"  # se diverso dall'indirizzo
# port = 993
# folder = "INBOX"
```

L'adapter IMAP usa solo `IMAP4_SSL`: non esiste un percorso in chiaro. La password per le app vive nel `secret_file` (prima riga, `0600` su POSIX, fuori dal workspace dell'agente) e non viene mai registrata o stampata.

Adapter di terze parti: impacchetta l'adapter e registralo nel gruppo di entry point `work_assistant.providers`. Il valore esposto deve essere un callable che riceve un `AccountConfig` e restituisce un `MailProvider`. L'implementazione di riferimento è il pacchetto sperimentale `adapters/zimbra`:

```toml
[project.entry-points."work_assistant.providers"]
zimbra = "work_assistant_zimbra.provider:zimbra_provider"
carbonio = "work_assistant_zimbra.provider:zimbra_provider"
```

Il pacchetto sperimentale `adapters/graph` segue lo stesso schema per Exchange Online (nomi `graph` e `m365`): autenticazione OAuth2 device code con solo `Mail.Read` delegato, token in un file locale, sola lettura.

Mantieni le opzioni specifiche sotto la tabella dell'account in `work-assistant.toml`. Il core non apre connessioni di rete implicite: ogni accesso esterno vive nell'adapter dichiarato.

Non usare messaggi reali come fixture.
