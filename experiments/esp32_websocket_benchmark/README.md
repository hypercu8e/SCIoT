# Migrazione WebSocket v2

**Confronto del 18 novembre completato sulla B.** Tre avvii per modalità
con `--gate-camera`, 18.900 richieste e 9.000 frame riusciti. HTTP persistente
e WebSocket hanno latenze di ciclo simili. Il primo conserva circa 12 KB in
più di RAM interna al minimo. [Report dei nove avvii](2026-11-18-comparison/report.md).

**Correzione verificata sulla B:** HTTP persistente e WebSocket hanno completato
2.100 richieste ciascuno con `--gate-camera`, inclusi 1.000 frame reali per avvio.
[Report dei due avvii](2026-11-17-gated-camera/report.md).

`--gate-camera`
abilita XCLK solo durante l'acquisizione, trattenendo il singolo framebuffer
mentre il clock è spento durante inferenza e rete. Il driver congelato resta
invariato: nessuno stop a metà DMA, nessun rilascio del buffer con clock spento.
Timestamp strettamente crescenti e successivi alla ripresa, dimensioni/formato e
hash prima/dopo invio intercettano frame vecchi, troncati o buffer modificati.
La ripresa attende 200 ms e scarta un frame completo: questi parametri richiedono
validazione ottica sul sensore e non garantiscono da soli esposizione corretta.
Build ESP-IDF, 17 test host e prove di stabilità sulla B superati.

Per ripetere lo smoke con il server avviato come indicato sotto:

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_websocket_benchmark/run.py --smoke --smoke-transport http-persistent --gate-camera --run experiments/esp32_websocket_benchmark/results/NUOVO_HTTP_GATED_RUN
```

Usare una directory nuova. Restano attivi backup, verifica e ripristino integrali.
Il boot esegue 1.100 richieste deterministiche e 1.000 acquisizioni/invii camera;
si interrompe al primo errore. Successivamente ripetere con `--smoke-transport ws`
e un'altra directory. Per i nove avvii mantenere `--gate-camera` su tutti i
trasporti; il comando è registrato in `configuration.json` e nel log seriale.
I 200 ms per ciascun cambio clock e il frame scartato fanno parte del costo del
ciclo completo: non confonderlo con la sola latenza richiesta/risposta.
Il risultato riguarda il firmware sperimentale sulla B. Il confronto sui nove avvii è riportato sopra. Le verifiche di recupero dopo guasto e di traffico restano distinte.

**Diagnostica XCLK completata:** tre avvii e 1.500 ping, baseline 300/300 risposte,
XCLK ON 82/600 e XCLK OFF 600/600 con camera inizializzata, acquisizione ferma
e buffer trattenuti. Fattore riprodotto su router e laptop; meccanismo fisico
non distinto. Flash originale ripristinata.
[Report XCLK del 17 novembre](2026-11-17-xclk/report.md).

**Controlli precedenti sul laptop, 17 novembre:** cambio USB `1-2` → `1-1`, attivazioni in
PSRAM e stop acquisizione non risolvono il guasto. Anche il client HTTP di
riferimento fallisce con camera (60 input e 3 frame riusciti, 408 sul quarto).
Queste prove hanno preceduto la diagnostica XCLK e la correzione.
[Report e provenienza](2026-11-17-laptop/report.md).

**Controllo storico del 17 novembre:** HTTP persistente senza camera 1.100/1.100 richieste;
stesso firmware con camera attiva fallisce alla prima inferenza (408). WS con
camera attiva fallisce alla registrazione. Ripristini integrali e boot originali
verificati e server chiuso.
[Report e limiti della diagnosi](2026-11-17-laptop/report.md).

**Passaggio al laptop:** [procedura con una sola B](../../RIPRESA_WEBSOCKET_LAPTOP.md). Dopo il pull eseguire `python3 experiments/multiclient_hardware/restore_runtime.py` e `python3 experiments/esp32_websocket_benchmark/restore_components.py` prima di `prepare.py`. I sorgenti pubblici congelati sono versionati in un archivio con hash; file locali diversi non vengono sovrascritti.


**Stato 16 novembre:** server e firmware sperimentale implementati, 27 test server/socket superati e build ESP-IDF riuscita. Due prove sulla B interrotte dopo 78 e 97 richieste riuscite: timeout, causa non identificata. Flash originale ripristinata e boot verificato in entrambi i tentativi. **WebSocket non promosso a default operativo.** [Report](2026-11-16/README.md).

Implementazione sperimentale sul servizio multiclient condiviso e sul firmware
ESP-IDF ottimizzato. La promozione a default operativo è subordinata alle prove
fisiche e al confronto con HTTP persistente; i dati parziali non autorizzano
una conclusione sulle prestazioni.

## Server

Il launcher `python -m server.multiclient.run --output NUOVA_DIRECTORY` espone
HTTP v2 e `/api/v2/ws` sullo stesso registro, coda e interprete. Sono accettati
anche `--http-v2` e `--multiclient-v2` tramite `server.edge.run_edge`.
Per il prefisso senza PAD aggiungere
`--model-registry experiments/esp32_websocket_benchmark/artifacts/model-registry.json`.
Preparazione e server richiedono l'ambiente `.venv`, `PYTHONPATH=src`.

Registrazione WS: JSON entro 3 secondi, massimo 512 byte, campi `version: 1`,
`client_id`, `model_sha256`. La risposta contiene sessione, modello, split,
dtype, dimensione attivazioni e deadline. Identità/modello/sessione sono legati
alla connessione. La sessione non è autenticazione; la configurazione è LAN `ws://`.

Messaggio binario: intestazione `<4sBBHQ`, 16 byte little endian:
magic `SCW1`, versione 1, tipo 1 richiesta o 2 risposta, riservato 0, request ID
uint64 crescente. Seguono SCB1 (4.640 byte) oppure SCR1 (1.760 byte) invariati.
Dimensioni totali 4.656/1.776 byte. Errori JSON: `status`, `error`, `session_id`,
`request_id` stringa decimale o null. Una sola richiesta pendente, anche tra
trasporti o dopo sostituzione della sessione. Due sovrapposizioni consecutive
chiudono il socket. Il server rileva disconnessioni mentre il worker elabora;
una Invoke già partita mantiene il posto fino al ritorno e il risultato viene
scartato. Invii delle risposte limitati a 3 secondi.

32 connessioni WS, registrazioni incluse; i limiti del servizio restano condivisi.
Backend Uvicorn esplicito `websockets`, messaggi 4.656 byte, coda di ricezione 1,
compressione disabilitata, ping/pong 20/10 secondi. La deadline del servizio WS
parte dal messaggio completo: non equivale al tempo di upload HTTP. Il timer
ESP32 misura invece invio e ricezione completi. L'inattività applicativa scade
anche se il ping/pong funziona.

Il registro modelli verifica hash effettivi del suffisso e dei prefissi
esplicitamente elencati, più forma/dtype/quantizzazione dell'interfaccia.
La sessione conserva l'hash selezionato; un modello non elencato viene rifiutato.

## Firmware e acquisizione

`prepare.py` verifica e copia in privato i componenti congelati dei benchmark
precedenti. Il componente ufficiale Espressif 1.8.0 è conservato con licenza
in `vendor/`; il suo archivio di origine e digest sono nel manifest.
Configurare solo `include/network.local.h` (ignorato, permessi 0600), con SSID,
password e `SERVER_BASE_URL`, ad esempio `http://192.168.1.152:8000`.
I valori e i binari non vanno pubblicati.

CPU/PSRAM 240/80 MHz, arena interna 145.760 byte più sentinelle, scratch 3 righe,
persistente PSRAM, camera RGB565 96x96 e LUT: identici nei tre trasporti.
Il comando seriale `w` seleziona WS, `h` HTTP persistente, `c` HTTP close.
Il runner ricompila, verifica backup e identità B, conserva snapshot e digest,
installa, acquisisce e ripristina in `finally`, verificando flash e boot originale.

Esecuzione, usando il Python con pyserial/esptool del progetto:

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_websocket_benchmark/run.py --gate-camera --run experiments/esp32_websocket_benchmark/results/NUOVO_RUN
```

`--smoke` limita a un avvio WS. Per verificare prima alimentazione e HTTP con
camera accesa, usare `--smoke --smoke-transport http-persistent`; è disponibile
anche `http-close`. Il trasporto scelto viene registrato in `configuration.json`.
Per isolare l'effetto della camera, aggiungere `--camera-off`: lo stesso firmware
salta l'inizializzazione della camera e completa le 1.100 richieste canoniche,
senza acquisire frame camera. Questa prova diagnostica non conta come avvio
completo del confronto. I comandi seriali maiuscoli `W/H/C` selezionano tale
modalità; i minuscoli mantengono la camera attiva. RSSI, canale e risultato della
registrazione HTTP sono conservati negli eventi seriali.
Altri controlli ammessi solo con `--smoke --smoke-transport http-persistent`:
`--activation-memory psram` mantiene la camera attiva e sposta soltanto l'arena
delle attivazioni; `--camera-paused` inizializza la camera, poi ferma acquisizione
e interrupt VSYNC mantenendo i buffer e senza disabilitare il clock sensore.
Quest'ultimo esclude i frame camera e non conta come avvio completo. I comandi
seriali sono rispettivamente `r` e `p`; i due controlli non si combinano fra loro
né con `--camera-off`. La campagna ordinaria mantiene l'arena interna.
La campagna ordinaria ruota nove avvii
`w,h,c / h,c,w / c,w,h`, mappati a `1,2,3 / 2,3,1 / 3,1,2` con
`--gate-camera`. Ogni avvio confronta 35 input con il modello originale,
esegue 100 richieste iniziali e 1.000 richieste deterministiche, poi 1.000 frame
camera. I controlli di memoria includono i socket; il minimo deve essere 32 KiB.
Un errore arresta la campagna e avvia il ripristino. Non scollegare prima della
conferma di recupero.

## Diagnostica XCLK, comando `x`

Segnalazione di partenza: [esp32-camera #869](https://github.com/espressif/esp32-camera/issues/869).
Il driver S3 congelato lascia XCLK attivo dopo `cam_stop()`. Questo esperimento
verifica l'effetto sulla B, senza attribuire automaticamente la causa alla USB.

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_websocket_benchmark/run.py --xclk-diagnostic --run experiments/esp32_websocket_benchmark/results/NUOVO_XCLK_RUN
.venv/bin/python experiments/esp32_websocket_benchmark/analyze_xclk.py experiments/esp32_websocket_benchmark/results/NUOVO_XCLK_RUN --output experiments/esp32_websocket_benchmark/results/NUOVO_XCLK_RUN/report
```

Non serve un server HTTP. Il laptop indicato dall'header locale deve rispondere
ai ping. Gateway ricavato dal DHCP, laptop dall'IPv4 di `SERVER_BASE_URL`.
Tre avvii indipendenti, stesso binario: baseline Wi-Fi senza camera, poi camera
inizializzata e acquisizione ferma con buffer trattenuti; XCLK ON/OFF/ON/OFF.
Ogni fase invia 50 ping al gateway e 50 al laptop, intervallo 200 ms e timeout
1.000 ms: 500 tentativi per avvio, 1.500 totali. Le due sessioni sono allocate
prima della baseline e riutilizzate; le righe dei singoli ping sono emesse dopo
ogni sessione per non introdurre attese seriali durante la misura.

GPIO15 viene collegato a `CAM_CLK_IDX` per ON e a `SIG_GPIO_OUT_IDX`, latch basso,
per OFF. Divisore 16 MHz, camera, modello, arene, rete e alimentazione invariati.
Il routing è letto dai registri; non è una misura con oscilloscopio. Prima di
ogni fase si attende 200 ms. Il comando non si combina con gli altri smoke e
non modifica i nove avvii del confronto ordinario. I timeout ICMP sono dati,
non errori da nascondere con ritentativi; panic, riserva RAM e contatori incoerenti
arrestano la prova. Backup/ripristino integrali e boot originale verificati.

Regola fissata prima delle misure: ogni destinazione deve avere baseline almeno
49/50; ciascuna fase OFF deve avere almeno 49/50 risposte e p95 entro
`max(100 ms, 2 × p95 baseline)`. Entrambe le fasi ON devono peggiorare rispetto
alla OFF abbinata di almeno 10 punti percentuali di perdita, oppure avere p50
almeno `max(20 ms, 3 × max(1 ms, p50 OFF))`. L'effetto è dichiarato riprodotto solo
con dati completi e reversibili per entrambe le destinazioni in tutti e tre gli
avvii; altrimenti l'esito è inconcludente. Errori locali di invio sono conservati
separatamente dai timeout; le latenze escludono i ping senza risposta.

Il risultato non distingue interferenza elettromagnetica e alimentazione, non
dimostra stabilità del ciclo camera e non promuove WebSocket.

## Validazione PC

Test servizio e protocollo:

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests/multiclient -v
PYTHONPATH=src .venv/bin/python tools/multiclient/ws_load.py --clients 2 --requests 100 --output /tmp/ws-load2
```

Il generatore WS usa socket reali, tre frammenti RFC per richiesta e confronto
integrale dei punteggi con il suffisso locale. Client simulati e input sintetici
non dimostrano prestazioni Wi-Fi o accuratezza della camera.

## Criteri per la promozione

Tutti i round completi, zero errori e differenze nei confronti previsti, minimo
interno >=32 KiB, sentinelle/heap integri, stack con >=512 byte di margine.
WebSocket p50/p95 del ciclo completo entro +5% da HTTP persistente in ciascun
round. Occorrono inoltre 20 riconnessioni e 10 riavvii del server, recupero entro
30 secondi e perdita di heap a riposo <=2 KiB. Le prove di guasto, cattura del
traffico e promozione restano passaggi distinti da registrare con evidenza.

Il buffer WS iniziale di 2.048 byte è stato portato a 4.656 nel secondo tentativo. Il timeout si è ripresentato: il cambio non dimostra una soluzione. Il codice successivo aggiunge backoff di connessione e confronto integrale dei punteggi canonici con un riferimento congelato; questa ultima revisione è compilata ma non ancora provata sulla B. Il benchmark arresta il run al primo scambio fallito, senza mascherarlo con retry.
## Skip selettivo su HTTP persistente

[Risultati del replay e della prova sulla B](2026-11-18-frame-skip/report.md).

Il benchmark decide dopo l’acquisizione RGB565 e la conversione INT8 a
96×96. La soglia si applica alla differenza assoluta media globale
(`global`) o alla maggiore delle medie nei blocchi 8×8 (`local`).
Il confronto usa l’ultimo input selezionato con risposta valida. Il
primo frame e il primo disponibile oltre il limite di rinnovo sono
elaborati anche a scena ferma. Il rinnovo è controllato a ogni acquisizione.
Il costo della camera e del riavvio XCLK si paga per tutti i frame acquisiti.

I comandi partono dalla root del repo con gli artefatti INT8 già preparati.

```sh
bench=experiments/esp32_websocket_benchmark
.venv/bin/python "$bench/frame_skip_replay.py" --output "$bench/results/skip-replay"
.venv/bin/python "$bench/frame_skip_replay.py" --offset-ms 355 --output "$bench/results/skip-replay-offset355"
```

Il replay usa i timestamp di `VideoWithCan.mp4` e, per default, campiona
ogni 710 ms. Il report confronta skip, latenza degli eventi e disaccordo della
griglia con l’inferenza completa e con invii distribuiti uniformemente
allo stesso budget. Gli intervalli di presenza sono quelli rilevati dal
FOMO a soglia 0,5. Cambiare offset verifica quanto il risultato dipende
dalla fase di campionamento sullo stesso video.

Avviare il server sperimentale in un terminale.

```sh
bench=experiments/esp32_websocket_benchmark
PYTHONPATH=src .venv/bin/python "$bench/serve.py" --http-v2 --http-keep-alive 10 \
  --model-registry "$bench/artifacts/model-registry.json" --output "$bench/results/skip-server"
```

I 10 secondi di keep-alive lasciano margine al rinnovo da 5 s, perché
l’età viene verificata sul frame successivo. In un altro terminale, con
la B collegata e la rete locale configurata, avviare la prova e l’audit.

```sh
bench=experiments/esp32_websocket_benchmark
tool_python=experiments/esp32_deadzone_benchmark/results/build-tools/bin/python
"$tool_python" "$bench/run.py" --frame-skip-replay "$bench/results/skip-replay/summary.json" \
  --skip-camera-frames 100 --run "$bench/results/skip-board"
.venv/bin/python "$bench/frame_skip_audit.py" "$bench/results/skip-board" \
  --server-events "$bench/results/skip-server/server.jsonl" \
  --output "$bench/results/skip-board/frame-skip-summary.json"
```

Il runner seleziona HTTP persistente con XCLK gestito e fa un avvio
baseline, seguito da shadow e attivo per ogni candidato distinto del
replay. In shadow salva le decisioni simulate e riceve comunque il
risultato FOMO per ogni frame. In modalità attiva omette inferenza e
richiesta per i frame simili. Per un singolo avvio usare ad esempio
`--frame-skip shadow --skip-metric global --skip-threshold 8 --skip-refresh-ms 1500`.
Senza `--skip-camera-frames`, ogni avvio acquisisce 1.000 frame.
Ripetere la stessa sequenza di scena per ogni avvio se si vogliono
confrontare direttamente i tempi tra modalità. I log shadow confrontano
le rilevazioni sugli stessi frame senza richiedere una replica della scena.
L’audit incrocia gli identificativi delle richieste con il server e conta
quanti invii dopo una pausa riusano la connessione TCP.

Il runner accetta `PLATFORMIO_PACKAGES_DIR` per indicare i pacchetti del
toolchain. Sulla postazione del benchmark il build usa
`$HOME/.platformio/packages` per allineare i percorsi di ESP-IDF e PlatformIO.
