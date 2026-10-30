# Prima verifica SCIoT HTTP v2 — 28 ottobre 2026

Implementazione e comandi nel [README del server](../../../src/server/multiclient/README.md),
istruzioni nel [README firmware](../../../src/client/esp32-s3-eye-multiclient/README.md).

## Evidenza ottenuta

- 10 test passati: FIFO e limiti, duplicati, sessione sostituita mentre il worker
  calcola, scadenze in coda/esecuzione, cancellazione, pulizia delle sessioni,
  recupero dopo errore, POST concorrenti, CRC e suffisso numericamente identico.
- Build ESP-IDF/PlatformIO riuscita per il firmware con una sola arena INT8.
  RAM statica 51.540 byte e flash 1.196.518 byte: **non sono picchi RAM misurati**.
  La configurazione di rete della build contiene i valori fittizi del template.
- Matrice HTTP con processi client/server separati sul loopback. Ogni risposta
  riuscita verificata byte per byte rispetto al suffisso congelato e controllata
  tramite client, sessione, contatore, frame e iterazione.

| Client simulati | Tentativi | Completamenti corretti | Rifiuti 429 | Altri errori |
|---:|---:|---:|---:|---:|
| 1 | 30 | 30 | 0 | 0 |
| 2 | 60 | 60 | 0 | 0 |
| 4 | 120 | 120 | 0 | 0 |
| 8 | 240 | 240 | 0 | 0 |
| 16 | 480 | 455 | 25 | 0 |
| 32 | 960 | 838 | 122 | 0 |

La coda era limitata a 8 richieste in attesa, con un worker e 8 ricezioni massime.
I rifiuti sono una risposta del controllo di ammissione, non inferenze completate.
Queste prove brevi verificano il funzionamento; non sono una stima stabile della
capacità massima né dimostrano 32 flussi video su Wi-Fi.

Prova breve aggiuntiva: due client a 20 tentativi/s ciascuno per circa 60 secondi,
**2.402 completamenti corretti, nessun rifiuto o altro errore**. I tempi e gli slot
persi sono nel [riepilogo JSON](summary.json), separati per dispositivo simulato.
Il [riepilogo server](server-summary.json) include attesa in coda, occupazione del
worker e RSS campionato; comprende anche inattività e matrice sullo stesso server.
L'intervallo RSS osservato è circa 525,8–526,7 MB: non è una verifica di assenza di
perdite su un'ora, né memoria richiesta dal solo modello.

I controlli con thread e asyncio sono stati eseguiti fuori dal sandbox: nel sandbox
le notifiche di completamento del thread venivano ritardate fino ai timeout,
producendo falsi fallimenti; la suite fuori sandbox passa senza tali ritardi.

## Verifiche ancora aperte

La ESP32 è presente sulla macchina host, ma **riservata alla prova di compressione
in un'altra sessione**, come richiesto dall'utente. Non sono state eseguite letture,
reset o scritture della flash da questa attività. Nessuna prova hardware del nuovo
firmware è stata eseguita. Sono ancora necessarie:

1. Una ESP32 con client simulati, verifica dei tre input fissi e della camera.
2. Due ESP32 insieme, almeno 1.000 richieste per scheda e prova di riavvio di A
   mentre B continua.
3. Prova di stabilità di un'ora con riconnessioni e controllo della memoria.

[Hash dei sorgenti](source-sha256.txt) e [log del build](firmware-build.log) conservano
la versione verificata. Gli hash non costituiscono una verifica hardware.
