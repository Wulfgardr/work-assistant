# Istruzioni per chi contribuisce con un agente

- Mantieni il core pubblico indipendente dal provider. Inserisci il comportamento specifico negli adapter.
- Usa solo identità, messaggi e allegati sintetici in codice, test, screenshot e documentazione.
- Non registrare in Git credenziali, file HAR, cookie, token, esportazioni delle caselle o database operativi.
- Mantieni separate ispezione, scrittura locale, bozza sul provider e invio.
- Il core pubblico non deve esporre uno strumento di invio.
- Tratta la vista di conoscenza come dato derivato, non come fonte originale o backup verificato.
- Gli agenti collegati a modelli cloud devono usare il gateway MCP attraverso il broker.
- Mantieni la cartella dati del broker fuori dal workspace leggibile dall'agente.
- Chiama la funzione pseudonimizzazione reversibile, non anonimizzazione.
- Prima di un commit esegui `pytest`, `python scripts/privacy_check.py` e il validatore della skill.
