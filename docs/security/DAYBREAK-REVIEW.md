# Revisione di sicurezza Daybreak — 24 agosto 2026

## Esito

La revisione ha analizzato il commit `daa257a` rispetto a `ffdd499`. L'ambito comprendeva broker locale, cassaforte degli alias, pseudonimizzazione, IPC, configurazione e gateway MCP.

Daybreak ha rilevato sette problemi: uno medio e sei bassi. La versione `0.3.0` applica una correzione per ogni percorso rilevato e aggiunge test di regressione sintetici.

## Correzioni

| ID | Gravità | Problema | Correzione |
| --- | --- | --- | --- |
| `WA-SEC-001` | Media | Archivio e chiavi finivano nel repository per impostazione predefinita. | `init` usa la cartella dati dell'utente; il broker rifiuta depositi protetti nel workspace. |
| `WA-SEC-002` | Bassa | Il registro delle identità poteva restare nel repository con permessi ampi. | Il registro predefinito vive sotto `data_dir`; POSIX richiede proprietario e `0600`, Windows rifiuta ACL con gruppi ampi. |
| `WA-SEC-003` | Bassa | La trasformazione copiava campi e metadati non dichiarati. | Le risposte usano uno schema a lista chiusa; ID e riferimenti diventano alias opachi; `provider_metadata` è escluso. |
| `WA-SEC-004` | Bassa | La risposta esponeva il valore letterale della regola per mittente. | La risposta contiene solo `sender-rule-N`. |
| `WA-SEC-005` | Bassa | Un client non autenticato poteva bloccare l'unico ciclo di accettazione. | Quattro worker fissi separano l'autenticazione dal servizio delle richieste. |
| `WA-SEC-006` | Bassa | Connessioni autenticate inattive creavano thread senza limite. | Il broker usa un numero fisso di handler e chiude le connessioni inattive dopo la scadenza. |
| `WA-SEC-007` | Bassa | Il timeout iniziava dopo connessione e autenticazione. | Un'unica scadenza copre connessione, autenticazione, richiesta e risposta; i tentativi sospesi sono limitati. |

## Verifica

I test di regressione provano:

- percorso dati esterno generato da `init`;
- rifiuto del workspace;
- rifiuto di un registro POSIX leggibile dal gruppo;
- assenza di cartella, metadati e ID del provider nelle risposte;
- assenza del valore letterale delle regole;
- disponibilità del broker con un client non autenticato inattivo;
- chiusura di una connessione autenticata inattiva;
- applicazione del timeout durante l'autenticazione.

Tutte le fixture sono sintetiche.

## Limiti residui

- Named pipe Windows e socket Linux richiedono il passaggio della matrice GitHub Actions sul commit pubblicato.
- Non esiste ancora un adapter di produzione. Autenticità del mittente, limiti upstream e metadati di un adapter reale richiederanno una revisione dedicata.
- La pseudonimizzazione non tratta il contenuto binario degli allegati e non garantisce anonimato.
- Quattro connessioni non autenticate simultanee possono occupare tutti i worker di autenticazione fino alla chiusura dei client. Il trasporto resta locale e deve essere protetto dall'isolamento del sistema operativo.

## Provenienza della revisione

- Modello revisore: Daybreak Blue.
- Scan ID: `b93f41b3-e39e-4908-9b8a-c237a9be51a4`.
- Metodo: analisi del diff, tracciamento dei flussi, prove sintetiche locali e analisi dei percorsi di attacco.
- Dati reali usati: nessuno.
