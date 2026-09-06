# Supporto delle piattaforme

Work Assistant richiede Python 3.11 o successivo e punta a Windows, Linux e macOS.

## Comportamento comune

- schema unico per configurazione e regole;
- archivio SQLite locale;
- cassaforte AES-GCM e pseudonimi derivati con HMAC;
- protocollo JSON autenticato tra gateway e broker;
- strumenti MCP e comandi CLI equivalenti;
- configurazione guidata (`setup`), diagnosi (`doctor`) e registrazione MCP (`mcp-setup`) solo con la libreria standard, identici su ogni piattaforma;
- benchmark sintetico della pseudonimizzazione.

## Trasporto del broker

| Piattaforma | Trasporto | Evidenza disponibile |
| --- | --- | --- |
| macOS | Socket Unix locale | Test locale e benchmark da 200 iterazioni |
| Linux | Socket Unix locale | Verifica nella matrice GitHub Actions |
| Windows | Named pipe autenticata | Verifica nella matrice GitHub Actions |

Il broker non apre una porta TCP. La distribuzione deve mantenere archivio, chiavi e registro delle identità fuori dal workspace dell'agente.

## Differenze di installazione

- Eseguibile su macOS e Linux: `.venv/bin/work-assistant`.
- Eseguibile su Windows: `.venv\Scripts\work-assistant.exe`.
- macOS e Linux usano una directory di esecuzione e un socket accessibili al proprietario.
- Windows usa una named pipe. La cartella dati richiede anche un ACL limitato all'account del broker.

Non descrivere una piattaforma come verificata se il job GitHub Actions del commit pubblicato non è terminato con esito positivo.
