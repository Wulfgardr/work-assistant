# Onboarding adattativo

Usa questa procedura per configurare Work Assistant o aggiungere un account.

Per una configurazione da zero indica `work-assistant setup` (o `setup --demo` per provare subito); per diagnosticare problemi indica `work-assistant doctor`; per registrare il client indica `work-assistant mcp-setup --client <nome>`.

1. Chiama `mail_onboarding_plan` per il provider indicato.
2. Spiega quali passaggi appartengono all'agente, alla persona e alla CLI locale.
3. Raccogli solo impostazioni non segrete, come nome account, indirizzo e host.
4. Chiedi alla persona di eseguire login e autenticazione a due fattori nel browser del provider.
5. Per Zimbra o Carbonio, indica il comando locale `work-assistant import-zimbra-har`. Non chiedere il percorso tramite MCP e non chiedere di incollare il contenuto in chat.
6. Per Microsoft Graph, indica `work-assistant-graph-login`: la persona approva nel browser, i token restano nel file locale.
7. Per IMAP, indica un file segreto locale con permessi `0600`: la password non entra mai in chat né in MCP.
8. Chiama `mail_onboarding_status`. Il risultato contiene solo stato e valori booleani.
9. Fermati se l'adapter non è disponibile, mancano dati di sessione, TLS non è verificato o i permessi superano l'ambito controllato.

Non automatizzare l'autorizzazione di un dispositivo attendibile. Non richiedere password, OTP, token, cookie o esportazioni complete in un prompt.
