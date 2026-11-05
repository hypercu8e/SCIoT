# HTTP v2 con due ESP32-S3-EYE reali

Campagna del 5 novembre 2026. Un solo modello INT8 congelato, split
`block_2_add`, attivazioni raw da 4.608 byte, ESP-NN, un worker e un thread
di inferenza. Il server e la coda sono quelli di
[HTTP v2](../../src/server/multiclient/README.md).

## Procedura

1. Identificare entrambe le schede dal MAC USB; verificare che le porte siano
   libere. Salvare e verificare separatamente tutti gli 8 MiB di ciascuna flash.
2. Compilare il client con la configurazione locale della LAN. Credenziali,
   binari e backup restano esclusi da Git.
3. Provare A e B separatamente, ciascuna con 60 richieste su tre input incorporati
   e 20 frame camera. Poi A con un client PC a 10 richieste/s per 150 secondi.
4. Eseguire entrambe con 1.000 frame camera ciascuna, oltre agli input incorporati.
5. Eseguire B per tre minuti; avviare A e riavviarla dopo 45 secondi, mentre B
   prosegue. A riparte con una prova breve. Controllare sessioni e continuità di B.
6. Eseguire entrambe per un'ora di camera continua, misurata sulla scheda.
7. Ripristinare e verificare integralmente entrambe le flash prima del riavvio;
   conservare il log di avvio originale. Il ripristino è tentato per entrambe
   anche se una delle due operazioni fallisce.

La prova A con simulatore può proseguire dopo i 150 secondi di traffico PC:
il relativo riepilogo di fase include anche quel tratto. I log mantengono gli
istanti delle singole richieste; non si attribuisce tutta la fase al carico misto.

## Strumenti

- [prepare.py](prepare.py): backup e snapshot dei sorgenti. L'eventuale immagine
  precedente è usata solo per la stessa scheda, aggiornando i primi 64 KiB e
  riverificando tutti gli 8 MiB contro la flash attuale; al fallimento si legge
  nuovamente l'intera flash.
- [flash_board.py](flash_board.py): identificazione, scrittura e verifica nella
  stessa connessione; controllo del MAC e dei digest dei backup.
- [campaign.py](campaign.py): fasi automatiche, seriali separate, monitoraggio
  sintetico ogni 30 secondi e ripristino in `finally`.
- [audit_server.py](audit_server.py): avvia il servizio con un archivio binario
  delle richieste e risposte. Questo I/O aggiuntivo è incluso nei tempi misurati.
- [analyze.py](analyze.py): ricalcola il suffisso su ogni attivazione ricevuta,
  verifica esattamente i byte dei punteggi, CRC, correlazioni client/sessione/
  richiesta, continuità degli input incorporati e durata delle fasi.

Gli hash FNV32 emessi dal dispositivo collegano ogni campione all'archivio del
server, comprese le intestazioni temporali della risposta. Sono controlli a
32 bit, non una prova crittografica di uguaglianza. Il replay dei punteggi sul
server è invece confrontato byte per byte. Gli input camera non sono annotati:
questa prova non misura accuratezza, classi corrette o qualità delle rilevazioni.

Il client accetta `s` (prova breve), `g` (1.000 frame), `i` (tre minuti), `h`
(un'ora); dopo ciascuna esecuzione torna in attesa. I campioni `memory`
riportano heap libero corrente e minimo dalla partenza, separando RAM interna
e PSRAM; non rappresentano una misura completa di tutta la RAM occupata.

I [tentativi del 5 novembre](2026-11-05/report.md) si sono fermati durante la
prova individuale di A. Il [punto di ripresa](../../RIPRESA_MULTICLIENT_LAPTOP.md)
descrive il passaggio al laptop; nessuna prova simultanea o di un'ora è conclusa.
Per un trasferimento tramite Git, `restore_runtime.py` ripristina i cinque
artefatti congelati dal piccolo archivio versionato e rifiuta file locali diversi.

## Riproduzione

Usare una nuova directory di output. `BOARDS` associa i ruoli ai MAC tramite
percorsi USB `by-id`; adattare i MAC prima di agire su altre schede.
Impostare SSID/password e `SERVER_BASE_URL`
in `src/client/esp32-s3-eye-multiclient/include/network.local.h`.
Compilare secondo il [README del client](../../src/client/esp32-s3-eye-multiclient/README.md).

L'interprete degli strumenti deve avere `pyserial` ed `esptool` 5; il server e
l'analisi usano `.venv/bin/python` con TensorFlow 2.15. Nel checkout della prova:

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python -u experiments/multiclient_hardware/prepare.py --run experiments/multiclient_hardware/results/NUOVA_PROVA
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python -u experiments/multiclient_hardware/campaign.py --run experiments/multiclient_hardware/results/NUOVA_PROVA
PYTHONPATH=src TF_CPP_MIN_LOG_LEVEL=3 CUDA_VISIBLE_DEVICES=-1 .venv/bin/python experiments/multiclient_hardware/analyze.py --run experiments/multiclient_hardware/results/NUOVA_PROVA --output experiments/multiclient_hardware/NUOVA_PROVA/summary.json
```

Le prime due operazioni richiedono accesso USB e rete LAN. Il runner rifiuta
porte occupate, backup mancanti, una porta server già usata e output preesistenti.
I log e le attivazioni integrali sono in `results/`, ignorato da Git; i risultati
pubblicabili devono indicare esplicitamente tentativi falliti e limiti.

## Prima prova interrotta

In `results/2026-11-05/`, A completa i 60 input incorporati, ma il primo invio
camera va in timeout senza raggiungere il gestore HTTP. La campagna si ferma;
le due flash vengono ripristinate e verificate. Non è una prova multi-client
riuscita e i suoi tempi non vanno uniti a campagne successive.

Nel client il frame camera veniva restituito prima dell'inferenza e dell'invio;
la campagna successiva trattiene il singolo buffer fino alla fine, come nel
benchmark di rappresentazione già validato. Sono inoltre registrate e gestite
le disconnessioni Wi-Fi. La modifica è un'ipotesi di intervento da verificare
sulla scheda, non una causa dimostrata del primo timeout.
