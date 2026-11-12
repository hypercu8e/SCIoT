# Prova di capienza nel client

**12 novembre 2026:** con 152 KiB tenuti in RAM interna la rete si blocca
(minimo libero 11–23 KB, HTTP 408, fasi R incomplete): **non entra** così
com'è. [Report](2026-11-12/report.md).

Domanda: con Wi-Fi, camera e HTTP v2 attivi, il client regge un blocco
contiguo in RAM interna della dimensione dell'arena delle attivazioni del
prefisso senza PAD, preso all'avvio e tenuto per tutto il tempo?

Contesto: con il [buffer a strisce a 5 righe](../esp32_dwstrip_benchmark/2026-11-12/report.md)
il picco misurato senza rete è 150.464 byte. Il limite di 161.323 veniva dal
minimo libero del client il 9 novembre (194.091) meno 32 KB di riserva: qui
lo si verifica direttamente.

## Cosa cambia nel client

Copia di `src/client/esp32-s3-eye-multiclient` (stessi componenti e
`sdkconfig.defaults`, il client non viene modificato). Unica aggiunta:
all'avvio il firmware attende dalla seriale `N` (nessuna riserva) oppure `R`
(riserva). Con `R` alloca **152 KiB (155.648 byte)** in RAM interna, cioè i
150.464 misurati più ~5 KB di margine per l'allocazione dell'arena, li scrive
e li tiene fino al riavvio. L'allocazione avviene prima di arena PSRAM,
Wi-Fi e camera, come farebbe il client portato. L'inferenza resta quella di
oggi, in PSRAM: la prova riguarda lo spazio, non la velocità. Il log
`memory` aggiunge il blocco interno contiguo più grande.

## Prova

Scheda B, rete del laboratorio (`FASTWEB`), server HTTP v2 sul PC
(`audit_server.py`, archivio delle richieste), un solo flash. Quattro fasi
**N, R, N, R**, ciascuna dopo un riavvio: 60 input incorporati + 1.000
frame camera (comando `g`). Backup verificato e ripristino in `finally`.

## Criteri, fissati prima della misura

- **Funzionamento, per ogni fase:** riserva nello stato richiesto; registrazione
  riuscita e camera avviata; 60 incorporati e 1.000 frame camera completati;
  nessun evento `error` o `rejected`; nessun panic, watchdog, brownout o riavvio;
  sul server solo stato 200, tante richieste quanti i campioni.
- **Margine, fasi R:** minimo interno libero dall'avvio ≥ **32.768 byte**, la
  stessa riserva usata per il limite di 161.323.
- **Esito:**
  - fasi N e R tutte superate → **entra**: si può passare al porting (da approvare);
  - fasi N superate, una R no → **non entra**: serve liberare RAM interna
    (buffer Wi-Fi/lwIP in PSRAM) o ridurre ancora l'arena;
  - una fase N non superata → problema dell'ambiente (rete, server), prova da
    ripetere; nessuna conclusione sulla capienza.
- **Riportati:** minimo libero e blocco contiguo più grande per fase, ciclo
  camera p50/p95, disconnessioni Wi-Fi.

Limiti: una sola scheda (il 9 novembre i minimi di A e B differivano di
1,3 KB); 1.000 frame per fase, non un'ora; la riserva non è un'arena TFLM
vera, quindi non misura il tempo né l'accesso concorrente alla RAM interna.

## Seconda prova: buffer Wi-Fi/lwIP in PSRAM

Dopo la prima prova (il blocco toglie RAM interna alla rete), stesso firmware
compilato con `CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP=y` (ambiente PlatformIO
`psramnet`, [`sdkconfig.defaults.psramnet`](idf/sdkconfig.defaults.psramnet)).
Wi-Fi e lwIP allocano prima in PSRAM, in RAM interna solo se la PSRAM manca.
Con l'opzione attiva, ESP-IDF cambia anche i suoi default Wi-Fi: 16 buffer
RX statici (prima 10), 16 buffer TX statici al posto di 32 dinamici, finestra
BA RX 16 (prima 6), nessun pbuf fuori ordine trattenuto. Si tiene la
configurazione raccomandata da Espressif per quell'opzione, senza ritocchi.

Stesse fasi N, R, N, R e stessa scheda. Criteri, fissati prima della misura:

- **Funzionamento, per ogni fase:** come sopra, ma con al massimo **10 frame
  camera persi (1%)** per errori HTTP transitori (`http_response`, stato 408
  o 410). La prima prova ha perso 3 frame in una fase N per questi errori.
  Il runner chiude la fase all'undicesimo errore.
- **Margine, fasi R:** minimo interno libero ≥ 32.768 byte, invariato.
- **Rete, fasi R:** ciclo camera p50 della fase R peggiore ≤ **1,10 ×** la
  media dei p50 delle fasi N dello stesso run.
- **Esito:** come sopra (entra / non entra / problema dell'ambiente).
- **Riportato:** costo dell'opzione sulla rete, cioè il ciclo p50 delle fasi N
  contro quelle N della prima prova (277–284 ms; giorno e ora diversi).

```sh
$T/pio run -d experiments/esp32_client_fit_benchmark/idf -e psramnet
$T/python experiments/esp32_client_fit_benchmark/run.py --env psramnet --max-errors 10 --run experiments/esp32_client_fit_benchmark/results/NUOVO_RUN --board B --seed BACKUP_VERIFICATO
.venv/bin/python experiments/esp32_client_fit_benchmark/analyze.py --criteria tolerant --run experiments/esp32_client_fit_benchmark/results/NUOVO_RUN --output experiments/esp32_client_fit_benchmark/results/NUOVO_RUN/audit.json
```

## Riproduzione

```sh
mkdir -p experiments/esp32_client_fit_benchmark/idf
C=src/client/esp32-s3-eye-multiclient
cp -a $C/components $C/managed_components $C/dependencies.lock experiments/esp32_client_fit_benchmark/idf/
cp $C/include/network.local.h experiments/esp32_client_fit_benchmark/idf/include/   # credenziali locali, ignorate da Git
(cd experiments/esp32_client_fit_benchmark && ../../.venv/bin/python -m unittest test_analysis)
T=experiments/esp32_lossless_codec_benchmark/results/build-tools/bin
$T/pio run -d experiments/esp32_client_fit_benchmark/idf     # component manager attivo: serve esp_jpeg
$T/python experiments/esp32_client_fit_benchmark/run.py --run experiments/esp32_client_fit_benchmark/results/NUOVO_RUN --board B --seed BACKUP_VERIFICATO
.venv/bin/python experiments/esp32_client_fit_benchmark/analyze.py --run experiments/esp32_client_fit_benchmark/results/NUOVO_RUN --output experiments/esp32_client_fit_benchmark/results/NUOVO_RUN/audit.json
```

Il firmware compilato e la sua copia nei risultati contengono le credenziali
Wi-Fi: restano nelle cartelle ignorate.
