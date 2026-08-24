# Modello di dominio

Work Assistant trasforma i messaggi di uno o più provider in uno spazio operativo locale, controllabile da una persona o da un agente.

## Termini principali

- **Account**: identità di una casella configurata come fonte indipendente. Evita di usare *tenant* o *inbox* con lo stesso significato.

- **Adapter del provider**: componente che traduce un servizio email nel contratto stabile di Work Assistant. Evita il termine generico *integrazione* quando intendi questo componente.

- **Archivio locale**: registro normalizzato e controllato del materiale acquisito dagli account. Non chiamarlo *Tesseract* o *backup*.

- **Vista di conoscenza**: proiezione rigenerabile di contatti e interazioni derivata dall'archivio locale. Non è una fonte originale né un backup.

- **Candidato di risposta**: contenuto proposto e conservato localmente. Non è una bozza presente sul provider e non è un messaggio inviato.

- **Superficie agente**: interfaccia strutturata, come MCP, con cui un agente usa Work Assistant. Non è la skill.

- **Skill**: istruzioni che insegnano a un agente come usare Work Assistant entro i confini autorizzati. Non è uno strumento o un plugin esecutivo.
