# WebSocket v2 — implementazione e prove del 16 novembre 2026

**Il percorso sperimentale è implementato, ma la migrazione operativa non è completata.**
Due tentativi sulla B hanno incontrato un timeout prima del termine del
riscaldamento. Il criterio di stabilità impedisce la promozione: HTTP resta il
percorso operativo e il firmware originale della B è stato ripristinato,
verificato integralmente e avviato in entrambi i tentativi.

## Cosa è disponibile

- Endpoint `/api/v2/ws` nello stesso servizio multiclient di HTTP, con sessioni,
  modello legato alla sessione, correlazione uint64, CRC, coda e worker condivisi.
- Contratto binario SCW1 con corpi SCB1/SCR1 conservati; limiti di dimensione,
  connessioni, deadline, invii e disconnessioni durante l'inferenza.
- Registro esplicito dei prefissi verificati per il medesimo suffisso.
- Firmware ESP-IDF isolato con percorso ottimizzato e selezione WS/HTTP persistente/
  HTTP close. Componenti congelati, Espressif WS 1.8.0 con licenza e digest.
- Runner con backup/ripristino verificati, snapshot delle revisioni installate,
  acquisizione e analizzatore che rifiuta una promozione da dati incompleti.

La revisione successiva alle due installazioni aggiunge backoff delle connessioni
e confronto integrale dei 432 punteggi canonici con riferimenti congelati dalle
attivazioni già verificate sulla scheda. Questa revisione è compilata; non è stata
installata né validata sulla B. Le prove già acquisite verificano correlazione,
intestazione, valori finiti e CRC dei punteggi, senza confronto integrale locale
dei punteggi del suffisso. I 35 confronti integrali del prefisso sono riusciti.

## Evidenza PC

[Suite multiclient: 25 test](server-tests.log),
[test TCP reali: 2 test](socket-tests.log), [build finale](build.log).
I test TCP esercitano frammentazione RFC, limite con chiusura 1009 e rilascio
connessioni. I test del servizio comprendono sostituzione della sessione con
Invoke attiva, correlazione, CRC e contatori duplicati.

| Client simulati | Tentativi | Risposte corrette | Rifiuti capacità |
|---|---:|---:|---:|
| 2 | 200 | 200 | 0 |
| 32 | 3.200 | 3.088 | 112 |

Tutti i punteggi delle risposte riuscite coincidono integralmente con il suffisso
locale. Tre frammenti RFC per ogni richiesta. I rifiuti 429 sono registrati come
rifiuti, non come inferenze completate. [2 client](pc-2.json), [32 client](pc-32.json).
Questa è una verifica PC, non una prova di contesa Wi-Fi tra 32 dispositivi.

## Evidenza B

| Tentativo | Buffer WS | Risposte riuscite | Minimo interno | Esito |
|---|---:|---:|---:|---|
| 1 | 2.048 B | 78 | 45.815 B | Timeout richiesta 78 |
| 2 | 4.656 B | 97 | 35.079 B | Timeout richiesta 97 |

Contatori da zero. Entrambi i tentativi avevano 100 richieste di riscaldamento
prima delle 1.000 deterministiche misurate e dei 1.000 frame camera: **nessun
segmento prestazionale completo, nessun frame camera trasmesso**.
Il maggiore buffer non ha risolto il timeout. In entrambi i casi la richiesta
fallita non compare tra le prenotazioni del servizio server: questo restringe
l'indagine alla consegna del messaggio completo e alla sua gestione prima
 dell'ammissione, senza identificare la causa. Non è provato un difetto di
Wi-Fi, driver, client WS o server.

[Report 1](smoke-1-report.md), [dati 1](smoke-1-summary.json),
[ripristino 1](smoke-1-recovery.json), [completamento 1](smoke-1-completion.json).
[Report 2](smoke-2-report.md), [dati 2](smoke-2-summary.json),
[ripristino 2](smoke-2-recovery.json), [completamento 2](smoke-2-completion.json).

Log, snapshot e firmware privati: `../results/B-smoke-01/`,
`../results/B-smoke-02/`; log server `../results/server-01/`.
Sono ignorati da Git perché i binari e i backup possono contenere credenziali.
Server e processi diagnostici avviati per la prova sono stati chiusi.

## Ripresa concreta

1. Ripartire dai due snapshot installati, conservando separatamente l'ultima
   revisione compilata. Aggiungere timestamp di send completata, messaggi ricevuti
   e motivi degli eventi WS su client e server.
2. Individuare il timeout con un relay TCP locale che registri i flussi tra B e
   server, oppure con una cattura pacchetti. La cattura diretta non è stata
   possibile: tcpdump richiede privilegi e sudo non interattivo richiede password.
   Il relay può osservare il flusso TCP, ma non misura le ritrasmissioni reali.
3. Dopo una correzione dimostrata, completare prima lo smoke WS, poi i nove avvii
   ruotati HTTP close/HTTP persistente/WS e il confronto entro +5% p50/p95.
4. Completare 20 riconnessioni, 10 riavvii server, memoria/stack, traffico e smoke
   sul firmware integrato prima di impostare WebSocket come default.

Non esistono ancora risultati comparativi HTTP/WS, misura energetica, prova di
accuratezza camera o validazione del recupero entro 30 secondi. I test di guasto
e la promozione rimangono sospesi al criterio di stabilità fallito.
