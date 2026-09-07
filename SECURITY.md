# Sicurezza

## Versioni supportate

Work Assistant è software alpha. Le correzioni di sicurezza si applicano all'ultima versione.

## Segnalare una vulnerabilità

Usa una segnalazione privata di sicurezza su GitHub. Non includere messaggi reali, credenziali, cookie, token, dati personali o informazioni soggette a regolazione.

## Confini operativi

- Mantieni configurazioni sensibili e dati di esecuzione fuori da Git.
- Usa messaggi sintetici in issue, test e pull request.
- Verifica le capacità di un adapter prima di abilitarlo.
- Tratta bozze sul provider, flag, etichette, spostamenti, calendario e invio come permessi distinti.
- Non esporre il processo MCP su una rete.
- Verifica un backup con un ripristino in uno spazio isolato. Sincronizzazione e integrità SQLite non sono prove di ripristino.
- Mantieni i file HAR in locale. Non inserirli in prompt, issue o messaggi di supporto.

## Broker di riservatezza

Le modalità `all` e `selective` richiedono il broker locale. Se il broker non è disponibile, il gateway MCP non usa un percorso alternativo in chiaro.

Il broker rifiuta dati protetti collocati nel repository o in un altro workspace di progetto rilevato. L'opzione `unsafe_allow_workspace_data = true` disabilita questo controllo: usala solo per una demo esplicitamente non sicura e senza dati reali.

Il gateway MCP non deve ricevere `work-assistant.toml`. Fornisci solo endpoint e percorso del file di autenticazione mostrati da `broker-info`. La chiave autentica il protocollo filtrato; non abilita letture di file generiche.

Su sistemi POSIX, il registro delle identità, la chiave di pseudonimizzazione, la chiave del broker, i token OAuth, i file di sessione e i segreti IMAP devono essere file regolari (mai symlink), appartenere all'utente e avere permessi `0600`. Su Windows il caricamento rifiuta ACL che concedono accesso a Everyone, Authenticated Users o al gruppo Users. La configurazione della macchina può applicare regole più restrittive. Le chiavi esistenti vengono riverificate a ogni caricamento: un `chmod` allentato fallisce in modo chiuso.

La cassaforte cifrata contiene la mappa reversibile degli alias. La cifratura protegge integrità e riservatezza del file, ma non sostituisce l'isolamento del sistema operativo.

La pseudonimizzazione non garantisce anonimato. Testo libero, fatti rari e stile di scrittura possono restare identificativi. Una regola `allow_raw` consente deliberatamente l'esposizione al modello per i mittenti corrispondenti, inclusi eventuali dati di terzi citati nel messaggio: usala solo per mittenti fidati il cui contenuto non cita terzi sensibili.

## Revisione Daybreak

La revisione del 24 agosto 2026 e le correzioni applicate sono documentate in [`docs/security/DAYBREAK-REVIEW.md`](docs/security/DAYBREAK-REVIEW.md).
