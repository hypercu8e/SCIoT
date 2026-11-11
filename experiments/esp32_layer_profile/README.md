# Profilazione locale del prefisso ESP32-S3-EYE

[Risultati fisici, operatori e limiti del 10 novembre](2026-11-10/report.md).

Stesso modello INT8 congelato `block_2_add`, TFLite Micro e ESP-NN dei
benchmark precedenti. Una scheda, CPU 240 MHz, PSRAM 80 MHz, arena da 1 MiB
in PSRAM. Camera, Wi-Fi, HTTP e LUT non vengono inizializzati: si misura
soltanto `Invoke()` con i tre input canonici 48/96/145.

## Misura e controlli

Tre round, modalità normale/profilata in ordine 0-1, 1-0, 0-1. Stesso indirizzo
dell'arena, interprete ricostruito fra blocchi; 5 warmup e 30 misure per input
e modalità: 540 inferenze misurate, 90 warmup e 2.970 record operatore.

Il profiler usa l'interfaccia TFLM `MicroProfilerInterface`; la sequenza è
verificata contro gli 11 nodi del FlatBuffer. Il tempo operatore include il
kernel TFLM e il reset delle allocazioni temporanee nel suo scope. I wrapper
misurano separatamente il tempo nelle entrypoint ottimizzate ESP-NN di
convoluzione e depthwise. La differenza normale/profilato stima l'effetto
complessivo della strumentazione, non il solo costo di un timer.

Input copy, confronto delle attivazioni, stampa e pausa al task idle sono
esterni al tempo `Invoke()`. Il watchdog resta attivo. I risultati non sono
FPS camera, latenza HTTP o una nuova misura di accuratezza.

Ogni attivazione, warmup inclusi, viene confrontata integralmente con quella
della prima esecuzione normale sullo stesso input. I tre input e output
integrali vengono confrontati anche con il prefisso TFLite sul PC; eventuali
differenze numeriche fra backend sono pubblicate, senza chiamarle equivalenza.
`analyze.py --legacy-archive PERCORSO/server/inference.bin` verifica inoltre i
byte contro un archivio del firmware ESP32 precedente con lo stesso modello.
Il report
richiede matrice completa, kernel ottimizzati effettivamente chiamati, stessa
arena e ripristino integrale verificato della flash, con boot originale.

## Build e acquisizione

Componenti locali identici a quelli congelati del client HTTP v2, senza
modifiche ai sorgenti dei componenti. La dipendenza ESP-NN di TFLM è esplicita
nel CMake del progetto per consentire la build senza component registry.

```sh
mkdir -p experiments/esp32_layer_profile/idf/components
cp -a src/client/esp32-s3-eye-multiclient/components/esp-tflite-micro experiments/esp32_layer_profile/idf/components/
cp -a src/client/esp32-s3-eye-multiclient/components/esp-nn experiments/esp32_layer_profile/idf/components/
IDF_COMPONENT_MANAGER=0 PLATFORMIO_CORE_DIR="$PWD/experiments/esp32_deadzone_benchmark/results/platformio-core" experiments/esp32_deadzone_benchmark/results/build-tools/bin/pio run -d experiments/esp32_layer_profile/idf
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_layer_profile/run.py --run experiments/esp32_layer_profile/results/NUOVO_RUN --board B
.venv/bin/python experiments/esp32_layer_profile/analyze.py --run experiments/esp32_layer_profile/results/NUOVO_RUN --output experiments/esp32_layer_profile/results/NUOVO_RUN/audit.json
```

Il runner identifica il MAC, rifiuta seriali occupate, salva e verifica tutti
gli 8 MiB prima dell'installazione e ripristina in `finally`, anche dopo errore
o SIGINT/SIGTERM. Non scollegare durante flash/ripristino. `--seed` opzionale
riutilizza un backup verificato della stessa scheda, ma aggiorna i primi 64 KiB
e verifica comunque l'intera flash attuale; al mancato confronto rilegge tutto.
Run, backup e binari sono ignorati. Snapshot dei sorgenti, hash dei componenti,
binari installati, eventi e log seriali restano nel run.

Per la verifica aggiuntiva contro il firmware ESP32 precedente, aggiungere
all'analisi `--legacy-archive experiments/esp32_input_camera_benchmark/results/2026-11-10-lut-hold-full-01/server/inference.bin`.
Il confronto PC dei dati attuali non è bit-exact: vedere il report.
