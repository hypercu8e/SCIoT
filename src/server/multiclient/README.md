# SCIoT HTTP v2: N dispositivi e worker configurabili

Il server accetta richieste concorrenti e completa un'inferenza alla volta.
Il percorso INT8 usa il prefisso ESP-NN già provato e il suffisso congelato
`block_2_add`. Il runtime TensorFlow Lite è creato, riscaldato e invocato nello
stesso thread dedicato; registri e coda appartengono al ciclo asyncio HTTP.

## Stato delle verifiche — 29 ottobre 2026

Il [report del 28 ottobre](../../../experiments/multiclient_validation/2026-10-28/README.md)
conserva dieci test, carico con client simulati e build del firmware. Le prove
fisiche dei benchmark ESP-NN e raw/zlib usano server sperimentali separati e non
validano questo servizio con una o due ESP32. Dopo la chiusura della prova di
compressione il firmware preesistente della scheda è stato ripristinato:
[verifica](../../../experiments/esp32_int8_compression_benchmark/2026-10-28/verification.json).
La prossima attività resta la procedura hardware del client v2.

## Avvio

Dalla radice, con gli artefatti del
[benchmark INT8](../../../experiments/esp32_representation_benchmark/README.md)
disponibili e l'ambiente TensorFlow 2.15:

```sh
PYTHONPATH=src .venv/bin/python -m server.edge.run_edge --http-v2 --port 8000 --output /tmp/sciot-multi-run1
```

Il launcher seleziona v2 prima di inizializzare i modelli o NTP del percorso legacy.
Equivalente: `python -m server.multiclient.run`, con lo stesso `PYTHONPATH=src`.
Usare una directory di output nuova: vi finiscono configurazione, manifest e
metriche `server.jsonl`. Non avviare più processi Uvicorn per questa modalità.

Opzioni: `--inference-workers 1`, `--inference-threads 1`, `--max-clients 32`, `--queue-size 8`, `--max-receiving 8`,
`--timeout 10`, `--idle 60`, `--host`, `--port`, `--artifacts`, `--output`.
Il logger scrive record brevi in ordine, senza dump dei tensori. Le scritture
sincrone delle metriche contribuiscono al costo complessivo del servizio.

## Contratto HTTP

`POST /api/v2/registration`, JSON fino a 512 byte:

```json
{"client_id":"eye-24ec4a0eb76c","model_sha256":"HASH_DEL_PREFISSO_INT8"}
```

Risposta: `client_id`, `session_id`, `model_sha256`, `split`, `dtype`,
`activation_bytes`, `request_deadline_ms`. La sessione è un token di correlazione,
non una credenziale di autenticazione. Il servizio è destinato alla LAN di prova.

`POST /api/v2/infer`, header:

- `X-Client-ID`: identità stabile (MAC completo per le schede).
- `X-Session-ID`: sessione ricevuta dalla registrazione.
- `X-Request-ID`: contatore intero uint64 crescente nella sessione.
- `X-Model-SHA256`: hash del prefisso congelato.

Corpo SCB1 originale: 32 byte `<8I` + 4.608 byte INT8. Dtype 1, immagine assente,
CRC32 obbligatorio. `frame` e `iteration` descrivono il campione; non identificano
la richiesta. Risposta SCR1: 32 byte + 432 punteggi float32 little endian.
I tre header di correlazione sono restituiti anche sugli errori, quando presenti
e di lunghezza valida. Il client deve confrontarli prima di accettare il risultato.

## Ammissione, scadenze e riconnessioni

Massimo una richiesta pendente per dispositivo, anche attraverso il cambio di
sessione. La FIFO contiene al massimo 8 lavori in attesa, oltre ai lavori in esecuzione (al massimo `--inference-workers`).
Al massimo 8 corpi vengono ricevuti contemporaneamente (registrazioni incluse).
I corpi hanno dimensione limitata anche senza Content-Length. Ricezione massima
3 secondi; scadenza inferenza 10 secondi dall'ingresso nel gestore HTTP. Il firmware
usa timeout HTTP di 15 secondi: il margine non garantisce il tempo della rete.

- `400`: intestazione, registrazione, dimensioni/CRC o messaggio non validi.
- `408`: ricezione del corpo scaduta; `413`: corpo troppo grande.
- `409`: dispositivo occupato o contatore già consumato.
- `410`: sessione sconosciuta, scaduta o sostituita; registrarsi nuovamente.
- `422`: modello diverso; correggere configurazione/modello.
- `429`: registro, ricezioni o coda pieni; il lavoro non viene eseguito.
- `500`: inferenza fallita; il worker resta disponibile per il prossimo lavoro.
- `503`: server in arresto; `504`: scadenza applicativa del lavoro.
- `499`: solo nei log per abbandono/cancellazione del client.

Il contatore è consumato alla prenotazione, anche se poi il corpo risulta invalido.
Non ritentare automaticamente lo stesso frame. Dopo 429 il firmware attende
250–500 ms e procede al successivo; dopo timeout rinnova la sessione.

Un lavoro scaduto/abbandonato ancora in coda viene eliminato. `Invoke` già iniziata
non è interrompibile: il risultato tardivo viene scartato e il dispositivo resta
occupato fino al ritorno del motore. Una nuova sessione non libera quel posto.
Il completamento controlla l'identità del lavoro prima di liberare lo stato;
non può completare o liberare una richiesta successiva.

Le sessioni inattive senza lavori scadono dopo 60 secondi e non lasciano storico
in memoria. L'arresto annulla i lavori pendenti e attende l'eventuale Invoke attiva.
Una chiamata del motore che non ritorna richiede intervento sul processo: questa
versione non implementa l'interruzione forzata di un thread TensorFlow.

## Firmware

[Client ESP32-S3-EYE](../../client/esp32-s3-eye-multiclient/README.md): una sola arena
INT8, identità dal MAC, registrazione, verifica delle risposte, ESP-NN verificato
tramite wrapper dei kernel. Il preprocessing e i timer derivano dal benchmark.
Le sue misure non vanno interpretate come già validate su hardware.

## Test e prove PC

```sh
PYTHONPATH=src TF_CPP_MIN_LOG_LEVEL=3 CUDA_VISIBLE_DEVICES=-1 .venv/bin/python -m unittest discover -s tests/multiclient -v
PYTHONPATH=src TF_CPP_MIN_LOG_LEVEL=3 CUDA_VISIBLE_DEVICES=-1 .venv/bin/python tools/multiclient/load.py --clients 2 --requests 1000 --output /tmp/sciot-load2
PYTHONPATH=src TF_CPP_MIN_LOG_LEVEL=3 CUDA_VISIBLE_DEVICES=-1 .venv/bin/python tools/multiclient/load.py --clients 32 --requests 100 --output /tmp/sciot-load32
PYTHONPATH=src TF_CPP_MIN_LOG_LEVEL=3 CUDA_VISIBLE_DEVICES=-1 .venv/bin/python tools/multiclient/load.py --clients 2 --duration 3600 --rate 20 --output /tmp/sciot-hour
.venv/bin/python tools/multiclient/analyze.py /tmp/sciot-multi-run1/server.jsonl --output /tmp/sciot-server-summary.json
```

Il simulatore ricava tre attivazioni valide dagli input congelati, calcola le uscite
attese e confronta esattamente i byte di ogni risposta riuscita, oltre agli header.
Usa identità `sim-N`: non eseguire più prove simultanee con gli stessi ID.
Una sola richiesta è pendente per client. Con `--rate`, conta gli slot persi durante
l'attesa: il rallentamento degli invii non deve nascondere la saturazione.

Metriche: tentativi, ammissioni, completamenti, rifiuti, errori e tempo completo
per client; attesa FIFO, occupazione worker e latenza server p50/p95/p99;
RSS Linux, sessioni, coda e ricezioni campionati ogni secondo.
Il throughput è complessivo: 32 client simulati non dimostrano 32 flussi video
reali né riproducono contesa Wi-Fi o costo del prefisso su 32 schede.

## Parallelismo CPU

`--inference-workers W` crea W interpreti indipendenti, ciascuno costruito ed
eseguito su un thread dedicato. `--inference-threads T` passa T al parametro
`num_threads` di TFLite; il parallelismo effettivo dipende dai kernel. Entrambi
richiedono interi positivi e valgono 1 per impostazione predefinita. Il processo
HTTP resta unico: i worker di inferenza non sono processi Uvicorn.

La coda FIFO è condivisa. L'assegnazione rispetta l'ordine di ammissione, ma le
risposte possono completarsi in ordine diverso. I limiti di sessione, la singola
richiesta pendente per client e le scadenze restano applicati a ogni lavoro.
Il timeout di un lavoro in esecuzione non libera anticipatamente il suo worker.

Esempio: `PYTHONPATH=src .venv/bin/python -m server.multiclient.run
--output /tmp/sciot-w4-t1 --inference-workers 4 --inference-threads 1`
(eseguire il comando su una sola riga).

Le metriche aggiungono `worker_started`, `worker_id`, `active_workers` e
`cpu_cores`: tempo CPU del processo diviso tempo reale fra campioni, quindi
1.0 indica l'equivalente di un core occupato. Comprende tutti i thread del
processo, anche HTTP e logging. `running` resta disponibile come booleano nei
campioni per compatibilità. L'analizzatore legge anche i log precedenti.

La campagna riproducibile è descritta in
[server_parallelism](../../../experiments/server_parallelism/2026-11-01/README.md).

Campagna completata: [risultati del parallelismo](../../../experiments/server_parallelism/2026-11-01/ac/README.md). 144 prove HTTP, 30 prove del motore, condizioni energetiche separate.
