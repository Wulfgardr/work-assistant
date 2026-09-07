# Roadmap

Stato di partenza: `0.7.0` su `main` (backup cifrato, bozze sul provider, hardening da audit interno 2026-09-07).

## 0.7.1 — Consolidamento (prossimo)

- [ ] Opzione `selective_also_mask_generic_pii` per mascherare email/telefoni anche con `allow_raw`.
- [ ] `defusedxml` + limite dimensione risposte SOAP Zimbra.
- [ ] Limiti dimensione HAR (già 32 MB in import) + streaming entities/vault.
- [ ] Verifica permessi Windows estesa a tutti i segreti (oggi solo registro entità).
- [ ] `doctor` warning quando `source`/`path`/`data_dir` puntano a percorsi sensibili (`~/.ssh`, `/etc`).
- [ ] Distinguere in `doctor`/`mcp-setup` tra broker non disponibile e auth fallita.

## 0.8.0 — Prestazioni provider

- [ ] IMAP: `BODY.PEEK[HEADER]` per `list_messages`, un solo FETCH per lista.
- [ ] Graph: allegati lazy (niente N GET per pagina in `list_messages`).
- [ ] Zimbra: evita `GetMsgRequest` per hit quando `fetch=hits` basta.
- [ ] Maildir: indice `message_id -> key` invece di scansione O(N).
- [ ] `statistics.quantiles` in `benchmark-privacy`, soglie CI per regressioni.

## 0.9.0 — Affidabilità adapter

- [ ] Validazione su server reale per Zimbra/Carbonio e Graph (`adapters/VALIDATION.md`).
- [ ] Propagazione errori allegati Graph invece di `()` silenzioso.
- [ ] Retry/backoff IMAP su disconnessioni, timeout configurabili.
- [ ] Suite di conformità adapter (stessi casi demo su ogni provider).

## 1.0 — Produzione

- [ ] Audit esterno di follow-up (verifica fix High/Medium di questo ciclo).
- [ ] Policy backup/retention documentata + `backup-verify` schedulabile.
- [ ] Guida operativa per multi-utente (permessi OS, systemd/launchd per broker).
- [ ] Criteri di uscita da alpha: adapter verificati, niente `skip` nei test, CI verde multipiattaforma.

## Fuori ambito (confermato)

Invio email dal core, OCR ospitato via rete, pseudonimizzazione di byte binari, garanzia di anonimato.
