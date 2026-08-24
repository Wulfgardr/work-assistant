# Implementazione del broker isolato

## Regole selezionate

- `mode = "off"`: nessuna trasformazione; la configurazione deve segnalare l'esposizione.
- `mode = "all"`: ogni messaggio visibile all'agente viene pseudonimizzato.
- `mode = "selective"`: regole ordinate scelgono `pseudonymize` o `allow_raw`; `default_action` è obbligatoria.
- Il registro globale delle identità si applica in tutte le modalità tranne `off`.

## Componenti

1. Configurazione validata senza caricare segreti nel gateway.
2. Alias stabili derivati da una chiave locale.
3. Mappa di inversione cifrata e accessibile al proprietario.
4. Broker su socket Unix o named pipe autenticata.
5. Schema di risposta esplicito, senza copia dei metadati del provider.
6. Gateway MCP configurato solo con endpoint e file di autenticazione.
7. Benchmark su carichi sintetici.

## Criteri di accettazione

- Nessun valore protetto in chiaro compare nelle risposte del broker.
- Il ripristino rifiuta alias sconosciuti.
- Le regole sono deterministiche e restituiscono solo un ID opaco.
- Un errore non degrada `all` o `selective` a `off`.
- Archivio, chiavi e registro identità restano fuori dal workspace dell'agente.
- Connessioni e worker hanno limiti espliciti.

## Ripristino della versione precedente

Arresta gateway e broker. Conserva archivio e cassaforte cifrata. Non eliminare la cassaforte finché esistono candidati o analisi che contengono alias.
