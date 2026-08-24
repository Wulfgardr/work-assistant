# Revisione di hardening: pseudonimizzazione dei dati per agenti

## Evidenze

La revisione ha analizzato MCP, archivio e configurazione al commit `ffdd499`. L'archivio era locale, ma il server MCP restituiva direttamente il contenuto dei messaggi. Le evidenze sono definite in [`context.md`](context.md).

## Vincoli

Il progetto richiede alias reversibili, continuità tra più account, regole per mittente e candidati di risposta utili. Il modello cloud non deve ricevere la mappa di inversione. Una persona può disabilitare la funzione, ma la configurazione deve rendere esplicita l'esposizione.

## Decisione

È stato scelto un broker locale isolabile con modalità `off`, `all` e `selective`. Il broker conserva dati in chiaro, mappa degli alias e ripristino. Il gateway MCP riceve solo payload filtrati.

Un filtro nello stesso processo resta utile come difesa aggiuntiva, ma non protegge i dati se l'agente può leggere direttamente archivio e chiave.

## Decisioni operative

- La cartella dati del broker deve stare fuori dal workspace dell'agente.
- Le regole usano le azioni esplicite `pseudonymize` e `allow_raw`.
- Il registro globale delle identità si applica anche ai messaggi consentiti in chiaro.
- Il gateway riceve uno schema a lista chiusa e riferimenti opachi.
