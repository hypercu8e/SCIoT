# Due ESP32-S3-EYE sul fisso: campagna completa — 9 novembre 2026

**Campagna completata e verificata**, dopo la correzione della registrazione
fra fasi. Due schede fisiche, HTTP v2, INT8 raw, ESP-NN, split `block_2_add`,
un worker e un thread CPU per il suffisso. Rete: hotspot Pixel 9a e inoltro
`adb reverse tcp:8000 tcp:8000` verso il server sul fisso.

## Risultato

- Prove individuali: 60 input incorporati + 20 frame camera per scheda.
- A con un client PC simulato a 10 richieste/s per 150 s: 1.000 frame camera
  completati da A. La fase include anche il tratto dopo la fine del carico PC.
- Due schede insieme: 1.000/1.000 frame camera ciascuna.
- Riavvio di A mentre B continua: B completa 35
  richieste durante il riavvio. A torna a inviare correttamente.
- Un’ora: A **14137** frame in **3600.103 s**;
  B **14162** frame in **3600.148 s**.
- **34296 richieste archiviate** con punteggi del suffisso
  ricalcolati e identici byte per byte; attivazioni dei tre input incorporati
  identiche tra schede e fasi. Stati terminali HTTP del server: `{'200': 34296}`.
- Nessun evento dispositivo `error` o `rejected` nella campagna riuscita.
- Entrambe le flash originali da 8 MiB ripristinate e verificate prima del boot;
  avvio originale confermato dai log. Nessuna scheda lasciata sul firmware
  sperimentale.

[Verifica completa e statistiche](summary.json) · [latenze CSV](latency.csv) ·
[ambiente server](server-environment.json) · [rete](network-preflight.json).

## Tempi osservati

Il ciclo include acquisizione/preprocessing, prefisso sulla scheda e scambio
HTTP completo. Il trasporto ADB e l’archiviazione sul server sono inclusi.
Valori descrittivi del campione; non sono una stima della capacità massima.

| Fase | Scheda | Frame camera | Ciclo p50 ms | Ciclo p95 ms | Coda server p95 ms |
|---|---|---:|---:|---:|---:|
| Individuale A | A | 20 | 245.71 | 306.49 | 0.090 |
| Individuale B | B | 20 | 247.01 | 294.92 | 0.089 |
| A + client PC | A | 1000 | 244.81 | 279.46 | 0.093 |
| Due schede, 1.000 frame | A | 1000 | 246.01 | 360.12 | 0.101 |
| Due schede, 1.000 frame | B | 1000 | 248.07 | 365.59 | 0.098 |
| Riavvio A, B continua | A | 152 | 245.36 | 267.46 | 0.109 |
| Riavvio A, B continua | B | 704 | 246.96 | 276.89 | 0.108 |
| Due schede, un’ora | A | 14137 | 244.92 | 272.18 | 0.100 |
| Due schede, un’ora | B | 14162 | 246.77 | 274.76 | 0.095 |

Le prove individuali contengono solo 20 frame camera: il confronto con quelle
lunghe è descrittivo, senza attribuire ogni differenza alla concorrenza.
Le due schede producono richieste concorrenti, ma il singolo worker esegue
le inferenze del suffisso in sequenza. Il client PC simulato usa il percorso
locale del fisso e non equivale a una terza ESP32 sul Wi-Fi.

## Memoria durante l’ora

Byte di heap libero dalle API ESP-IDF; il minimo è dalla partenza della scheda,
non necessariamente dall’inizio dell’ora. A viene riavviata nella fase precedente.

| Scheda | Interna libera, inizio | Interna libera, fine | Minimo interno | PSRAM libera, inizio | PSRAM libera, fine |
|---|---:|---:|---:|---:|---:|
| A | 217263 | 249839 | 194091 | 7276272 | 7295872 |
| B | 217243 | 250139 | 195343 | 7276272 | 7295872 |

RSS massimo campionato del processo server: **526798848 byte**.
Heap libero e RSS non sono una misura completa del picco RAM dell’applicazione,
né una misura di energia. I campioni nel tempo restano nei log integrali.

## Tentativo interrotto e correzione

Il primo tentativo `results/2026-11-09-pixel-adb-full` completa le prove
individuali e A + PC, ma B riceve HTTP 410 all’avvio della fase simultanea.
La scheda conservava una sessione scaduta durante l’attesa (idle server: 60 s).
Il tentativo viene fermato, conservato e seguito da ripristini verificati:
[riepilogo del tentativo interrotto](interrupted-attempt.json).

Il firmware ora registra una nuova sessione all’inizio di ogni comando di prova,
prima del primo campione. Non aumenta i timeout e non nasconde errori durante
le inferenze. Il nuovo tentativo ripete tutte le fasi, inclusa l’attesa di B,
con il binario corretto; i campioni dei due tentativi non sono aggregati.
Build riuscita e **21 test server superati**, incluso il controllo di sessione
scaduta e successiva ri-registrazione con contatore ripartito da zero.
[Verifiche della correzione](renewal-fix-validation.json).

## Evidenze e riproduzione

Log seriali, eventi per dispositivo/server, archivio delle richieste e risposte,
backup, snapshot dei sorgenti e hash sono nel percorso locale ignorato:
`experiments/multiclient_hardware/results/2026-11-09-pixel-adb-full-renewal/`.
Credenziali e firmware compilato restano esclusi da Git.

```sh
PYTHONPATH=src TF_CPP_MIN_LOG_LEVEL=3 CUDA_VISIBLE_DEVICES=-1 .venv/bin/python experiments/multiclient_hardware/analyze.py --run experiments/multiclient_hardware/results/2026-11-09-pixel-adb-full-renewal --output experiments/multiclient_hardware/2026-11-09-pixel-adb-full/summary.json
```

Il collegamento fra campioni dispositivo e archivio usa FNV32; CRC32 controlla
il corpo della richiesta, mentre il replay dei punteggi è byte per byte.
FNV32 non costituisce una prova crittografica di uguaglianza dei dati della scheda.

## Conclusione e limiti

Validato il servizio multi-client sperimentale HTTP v2 con due ESP32-S3-EYE
fisiche nella configurazione provata: richieste e risposte correlate, avanzamento
di entrambe, riavvio isolato e un’ora di camera continua. Questa prova non misura
accuratezza su immagini annotate, vantaggio dello split rispetto ad altre
soluzioni, comportamento con molti più dispositivi o contesa Wi-Fi di altre reti.
Il percorso Pixel + ADB fa parte delle condizioni sperimentali.
