---
name: work-assistant
description: Usa un'istanza configurata di Work Assistant tramite MCP o CLI per ispezionare caselle, costruire conoscenza locale e preparare candidati di risposta. Non usare per client email non collegati a Work Assistant.
---

# Work Assistant

Usa gli strumenti Work Assistant come superficie operativa. La skill contiene regole decisionali; non sostituisce MCP o CLI.

Per la prima configurazione leggi [references/onboarding.md](references/onboarding.md). Prima di esporre contenuti a un agente leggi [references/privacy.md](references/privacy.md).

## Seleziona l'account

Usa `mail_accounts` quando la persona non indica una casella. Non unire account simili e non trattare una casella condivisa come personale.

## Usa evidenze locali

Usa `mail_list` per restringere il campo e `mail_get` per il messaggio esatto. Esegui `mail_sync` solo quando serve uno stato aggiornato e l'adapter configurato supporta l'acquisizione.

Separa contenuto del messaggio, conoscenza derivata e inferenza. `mail_knowledge` è una vista rigenerabile, non la fonte originale o un backup completo.

## Rispetta l'autorità

- Una richiesta di ispezione o proposta non autorizza modifiche sul provider.
- `mail_draft_candidate` crea solo contenuto locale. Riporta ID e `sent: false`.
- Non affermare che esiste una bozza sul provider senza scrittura e rilettura da parte di un adapter.
- Non inviare email. Il core pubblico non espone questa capacità.

## Proteggi i dati

Restituisci solo il contenuto necessario. Non inserire messaggi reali, identità, credenziali o allegati in codice, test, issue pubbliche o ricerca esterna.

Quando conta una dichiarazione di archivio o recupero, usa `mail_verify_archive` e descrivi il suo limite: integrità SQLite e hash non provano il ripristino di un backup.
