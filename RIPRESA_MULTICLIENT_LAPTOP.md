# Ripresa sul laptop — 5 novembre 2026

## Obiettivo e punto esatto

Validare il servizio HTTP v2 con le **due ESP32-S3-EYE fisiche**, mantenendo
INT8 raw, ESP-NN, split `block_2_add`, un worker e un thread. La validazione
multi-client hardware e la prova di un'ora **non sono completate**.

Il 5 novembre sul PC fisso sono state interrotte due prove durante il controllo
individuale di A. I 60 input incorporati riescono in entrambe; con camera attiva
si osservano un timeout iniziale e, nel secondo tentativo, un solo completamento
da circa 6,3 secondi seguito da HTTP 408. Il segnale osservato è circa −72/−76 dBm.
La posizione non poteva essere cambiata; si passa al laptop per provare vicino
al router. **La causa del rallentamento non è dimostrata.**

La seconda prova trattiene il framebuffer fino al termine dell'invio e aggiunge
log/riconnessione Wi-Fi. Non ha risolto il problema. Non presentarla come fix
hardware riuscito. Il server mantiene la scadenza di ricezione del corpo a tre
secondi; nessun timeout è stato aumentato in queste prove.

Riscontri e dati JSON pubblicabili:
[diagnostica del 5 novembre](experiments/multiclient_hardware/2026-11-05/report.md).
Strumenti e protocollo:
[campagna](experiments/multiclient_hardware/README.md).

## Stato delle schede prima del trasferimento

| Ruolo | MAC | Stato |
|---|---|---|
| A | `24:ec:4a:0e:b7:6c` | Flash originale ripristinata e verificata dopo entrambi i tentativi |
| B | `24:ec:4a:0e:c3:14` | Flash originale ripristinata e verificata dopo entrambi i tentativi |

È stata poi completata la sola preparazione `2026-11-05-B-first`: backup
aggiornati e verificati, **nessuna installazione sperimentale**. Entrambe sono
state riavviate sul firmware originale prima del passaggio. Nessuna campagna
hardware è lasciata in esecuzione sul PC fisso.

I backup integrali e le credenziali non passano da Git. Restano sul PC fisso in
`experiments/multiclient_hardware/results/`. Sul laptop fare nuovi backup delle
schede effettivamente collegate: non serve trasferire le vecchie flash per
riprendere. Il runner usa i collegamenti USB `by-id`, quindi l'ordine ACM0/ACM1
può cambiare senza scambiare A e B.

## Dopo il pull

1. Controllare modifiche locali e aggiornare il clone con `git pull --ff-only`.
   Non sovrascrivere lavoro locale sovrapposto.
2. Ripristinare gli artefatti congelati con:

   ```sh
   python3 experiments/multiclient_hardware/restore_runtime.py
   ```

   Il piccolo archivio versionato contiene modelli INT8, tre input e header
   generato. Verifica tutti gli hash e rifiuta file locali diversi: non richiede
   rigenerare input, modelli o calibrazione. Non contiene credenziali né backup.

3. Riutilizzare `.venv` se funzionante. Ambiente server verificato sul PC:
   Python 3.11.17, TensorFlow 2.15.0, NumPy 1.26.4, FastAPI 0.143.1,
   Uvicorn 0.54.0. Le versioni sono registrate nel report; evitare di copiare
   ambienti virtuali fra macchine.
4. Per strumenti USB/build, riutilizzare l'ambiente esistente oppure crearne uno
   separato in `experiments/multiclient_hardware/results/tools` con `pyserial`,
   `esptool==5.1.0` e `platformio==6.1.18`. Il runner usa il proprio interprete per
   flash e seriale, e `.venv/bin/python` per server e client simulato.
5. Configurare sul laptop il file ignorato
   `src/client/esp32-s3-eye-multiclient/include/network.local.h`: SSID 2,4 GHz,
   password e `SERVER_BASE_URL` con **l'IP LAN attuale del laptop**, porta 8000.
   Il vecchio IP del PC fisso non va riutilizzato automaticamente. Verificare
   raggiungibilità della porta dal Wi-Fi e regole firewall applicabili.
6. Preparare i componenti e compilare secondo il
   [README del client](src/client/esp32-s3-eye-multiclient/README.md).
   Se si imposta `PLATFORMIO_CORE_DIR`, usare un percorso **assoluto**: un percorso
   relativo viene risolto rispetto al progetto PlatformIO.
7. Eseguire i 20 test del server fuori da eventuali sandbox che impediscono
   socket/thread; comando nel [README server](src/server/multiclient/README.md).

## Prossimo esperimento

Ripartire da **B per prima**, per distinguere un problema specifico di A da uno
comune. Una directory nuova è obbligatoria. Esempio dalla radice del repository,
con l'ambiente USB disponibile nel percorso usato qui:

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python -u experiments/multiclient_hardware/prepare.py --run experiments/multiclient_hardware/results/LAPTOP_NUOVA_PROVA
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python -u experiments/multiclient_hardware/campaign.py --run experiments/multiclient_hardware/results/LAPTOP_NUOVA_PROVA --first-board B
```

Se l'ambiente USB è stato creato in `results/tools`, sostituire soltanto il
percorso dell'interprete. Non lanciare la campagna con una porta già occupata.
Il programma si arresta al primo errore dispositivo e tenta comunque entrambi
i ripristini. In caso di nuova instabilità, conservare il tentativo e diagnosticare
il collegamento prima di chiamare completata la campagna.

Le fasi previste sono: prove individuali, A con client simulato, 1.000 frame
per scheda insieme, riavvio di A mentre B prosegue, un'ora con entrambe.
Code, correttezza, tempi per dispositivo e memoria restano separati dalla
qualità del riconoscimento. Un Wi-Fi lento è una condizione valida; timeout,
errori e ritrasmissioni devono restare visibili nei risultati.

Per riaprire il lavoro con l'agente sul laptop:

> Leggi RIPRESA_MULTICLIENT_LAPTOP.md e riprendi la verifica delle due ESP32.
> Il lavoro precedente è già autorizzato: backup verificati, prove hardware e
> ripristino delle flash originali. Parti da B e usa aggiornamenti sintetici.
