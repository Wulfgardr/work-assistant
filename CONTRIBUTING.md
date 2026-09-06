# Contribuire a Work Assistant

Mantieni ogni modifica piccola, indipendente dal provider e verificabile.

1. Usa solo identità e messaggi sintetici.
2. Non registrare in Git esportazioni, credenziali, cookie, token o database operativi.
3. Inserisci il comportamento specifico di un servizio nel relativo adapter.
4. Mantieni il core pubblico privo di accessi di rete impliciti.
5. Aggiungi test per il comportamento osservabile e per gli stati di errore.
6. Esegui `pytest`, i test degli adapter (`adapters/*/tests`), `python scripts/privacy_check.py` e `python scripts/validate_skill.py` prima di aprire una pull request.

Gli adapter generici e senza dipendenze vivono in `src/work_assistant/providers/`. Gli adapter di servizi specifici vivono in pacchetti separati sotto `adapters/<nome>/`, con transport iniettabile per i test e registrazione via entry point `work_assistant.providers`.

L'invio di email non appartiene al core pubblico. Una proposta di scrittura sul provider deve definire capacità, anteprima, conferma e ricevuta di verifica come confini separati.
