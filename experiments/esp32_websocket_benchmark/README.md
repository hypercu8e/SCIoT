# Migrazione WebSocket v2

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
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_websocket_benchmark/run.py --run experiments/esp32_websocket_benchmark/results/NUOVO_RUN
```

`--smoke` limita a un avvio WS. La campagna ordinaria ruota nove avvii
`w,h,c / h,c,w / c,w,h`. Ogni avvio confronta 35 input con il modello originale,
esegue 100 richieste iniziali e 1.000 richieste deterministiche, poi 1.000 frame
camera. I controlli di memoria includono i socket; il minimo deve essere 32 KiB.
Un errore arresta la campagna e avvia il ripristino. Non scollegare prima della
conferma di recupero.

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
