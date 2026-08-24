# Riservatezza nell'uso con agenti

Leggi questa procedura prima di usare contenuti email con un agente.

1. Chiama `mail_privacy_status` prima della prima richiesta di contenuto.
2. Se la modalità è `off`, avvisa che il contenuto visibile all'agente può raggiungere il fornitore del modello.
3. In modalità `all`, usa solo alias e riferimenti restituiti da Work Assistant. Non modificarli.
4. In modalità `selective`, controlla `_privacy.action`. `allow_raw` indica un'esposizione intenzionale.
5. Crea candidati di risposta con gli alias restituiti. Il broker ripristina quelli conosciuti e rifiuta gli altri.
6. Usa `mail_local_artifact` per analisi o note che devono essere ripristinate localmente. Lo strumento restituisce solo un ID opaco.
7. Un agente cloud non deve usare i comandi CLI in chiaro né leggere direttamente SQLite.

La pseudonimizzazione riduce l'esposizione degli identificativi diretti. Non garantisce anonimato e non elimina il contesto identificativo dal testo non riconosciuto.
