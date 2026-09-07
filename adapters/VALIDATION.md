# Validazione su server reale

Gli adapter in questa cartella sono sperimentali: i test usano transport finti con risposte sintetiche. Prima di un uso in produzione, esegui questa checklist contro il server reale con un account di prova dedicato. Usa solo messaggi sintetici.

## Tutti gli adapter

1. `sync` su una casella di prova e confronto dei conteggi con la webmail.
2. Lettura di un messaggio con allegato: `attachment-text` produce testo leggibile e lo stato è `ok`.
3. Creazione di una bozza sul provider (`draft-on-provider`), verifica nella webmail, eliminazione.
4. Scadenza credenziali: sessione revocata o password cambiata produce un errore che indica il rinnovo (mai una traccia con valori segreti).
5. Nessun segreto in log, output o issue: token, cookie e password restano nei file locali.

## Zimbra / Carbonio (`adapters/zimbra`)

6. `import-zimbra-har` da un HAR reale: riporta solo i nomi dei cookie.
7. `sync` con più di 100 messaggi: la paginazione non perde né duplica.
8. `list_messages(since=...)`: nessun messaggio più vecchio del filtro.
9. Allegato sopra qualche MB: `fetch_attachment_bytes` completa senza errori.
10. Bozza standalone creata e ritrovata nella webmail; bozza di risposta rifiutata con messaggio chiaro.

## Microsoft Graph (`adapters/graph`)

6. `work-assistant-graph-login`: approvazione nel browser, cache token `0600`.
7. Refresh silente dopo scadenza dell'access token (nessun nuovo login).
8. Throttling: sotto carico l'adapter attende `Retry-After` invece di fallire.
9. `createReply` con `in_reply_to`: la bozza risultante cita il messaggio originale.
10. Permessi minimi: l'app Entra ha solo `Mail.Read` delegato (+ `offline_access`).

## IMAP integrato (`demo` no, `imap` sì)

6. Provider comuni (Gmail con app password, Outlook, server Dovecot): login, cartella non-INBOX, bozza in Drafts ritrovata nel client.
7. Cartella bozze mancante: errore chiaro, nessuna scrittura parziale.

## Esito

Annotazione di data, versione server, account di prova (sintetico) ed esiti accanto a ogni punto. Una validazione riuscita non sostituisce la revisione di sicurezza dedicata richiesta in `docs/security/DAYBREAK-REVIEW.md`.
