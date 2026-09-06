# ADR 0002: testo derivato degli allegati

- Stato: accettata
- Data: 5 settembre 2026

## Contesto

I messaggi contengono allegati in formati diversi (testo, HTML, documenti Office, PDF, immagini). Il core archiviava solo i metadati degli allegati e la revisione Daybreak elencava tra i limiti residui la mancata gestione del contenuto binario. Serviva un modo locale per leggere gli allegati senza inviare byte a terzi e senza introdurre dipendenze di rete nel core.

## Decisione

Il core espone una pipeline di estrazione del testo derivato:

- registro di estrattori indipendenti dal provider (`builtin-text`, `builtin-html`, sempre disponibili);
- AnyDoc (Firecrawl, `pip install '.[attachments]'`) come estrattore facoltativo per documenti Office, EPUB, RTF, CSV e PDF con livello di testo, tutto in locale;
- fallback OCR locale tramite il binario di sistema `tesseract` quando un documento non ha un livello di testo utilizzabile; per i PDF scansionati le pagine vengono prima rese in immagini con `pdftoppm`, se presente; adapter OCR di terze parti partecipano con `is_ocr = True`;
- i servizi OCR ospitati restano fuori ambito: invierebbero contenuti a terzi;
- i byte originali non vengono mai conservati né inoltrati: l'archivio tiene solo il testo derivato con hash della sorgente, il broker pseudonimizza il testo prima di esporlo;
- gli adapter forniscono i byte tramite `fetch_attachment_bytes` oppure dichiarano `provider_unsupported`.

## Alternative considerate

- Dipendenza obbligatoria da AnyDoc: scartata, il core resta installabile senza binari nativi.
- OCR via API ospitata: scartata, incompatibile con il confine locale del broker.
- Conservazione dei byte originali in archivio: scartata, amplia la superficie dei dati protetti senza benefici per gli agenti.

## Conseguenze

La cache è un dato derivato e rigenerabile come la vista di conoscenza. La pseudonimizzazione del contenuto binario resta dichiarata come non disponibile: ciò che attraversa il broker è solo testo derivato e pseudonimizzato, con stato ed estrattore sempre visibili.
