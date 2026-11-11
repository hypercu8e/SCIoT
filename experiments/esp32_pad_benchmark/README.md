# PAD veloce sul prefisso ESP32-S3-EYE

**11 novembre 2026: criteri superati.** PAD 14,647 → 5,209 ms, `Invoke()`
93,913 → 84,482 ms (−10,0%), zero byte diversi. [Report](2026-11-11/report.md).

La [profilazione del 10 novembre](../esp32_layer_profile/2026-11-10/report.md)
attribuisce al nodo 4, PAD, circa 14,6 ms su 93,8 ms di `Invoke()`. Il kernel
TFLM (`reference_ops::PadImpl`) scrive un byte alla volta con controlli dei
limiti su ogni elemento. Qui lo si sostituisce con copie per righe e
riempimento del bordo, senza modificare modello, split o componenti.

## Il PAD del modello

Ingresso `1×48×48×48` INT8, uscita `1×49×49×48`, paddings
`[[0,0],[0,1],[0,1],[0,0]]`: una riga in basso e una colonna a destra.
Nessun `constant_values`: il bordo è lo zero point dell'uscita, −128, ottenuto
con la stessa espressione del kernel TFLM.

## Implementazione

- `idf/src/fast_pad.h`: funzione pura `fastPadHW`, per ogni riga `memset`
  del bordo sinistro, `memcpy` della riga di ingresso, `memset` del bordo destro.
- `idf/src/fast_pad.cpp`: registrazione `RegisterOp(PadInit, PadPrepare,
  FastPadEval)`. Preparazione, parametri e valore del bordo sono quelli TFLM;
  cambia solo l'esecuzione. Percorso veloce solo per INT8 4D senza padding su
  batch e canali, altrimenti ricade sul kernel TFLM originale.
- Il firmware contiene due resolver: `original` con `AddPad()` invariato e
  `fast` con `AddPad(RegisterFastPad())`. Stessa arena in PSRAM per entrambi.

## Protocollo

Una scheda (B), CPU 240 MHz, PSRAM 80 MHz, ESP-NN. Camera, Wi-Fi e HTTP non
inizializzati.

1. **Verifica.** 32 input: i tre canonici 48/96/145 e 29 pseudo-casuali
   (xorshift32, seme 20261111). Il kernel originale produce le attivazioni di
   riferimento. Il kernel veloce viene poi eseguito in modalità controllo:
   dentro lo stesso nodo calcola anche il PAD TFLM su un buffer separato e
   confronta tutti i 115.248 byte. Si confrontano anche le 4.608 attivazioni finali.
2. **Calibrazione, descrittiva.** Fuori da TFLM, su buffer in PSRAM e, se
   disponibili, in RAM interna: 30 misure di `memcpy` dei 110.592 byte, del
   PAD veloce e del PAD di riferimento. Serve a stimare quanto del tempo sia
   costo di accesso alla memoria. Non è un criterio.
3. **Misura.** Tre round, quattro blocchi ciascuno (variante × normale/profilato).
   Ordine: round 1 O-n, V-n, V-p, O-p; round 2 V-p, O-p, O-n, V-n;
   round 3 V-n, O-n, O-p, V-p (O originale, V veloce, n normale, p profilato).
   Per blocco 3 input × (5 warmup + 30 misure): 1.080 inferenze misurate,
   180 warmup, 5.940 record operatore. Ogni attivazione, warmup inclusi, è
   confrontata integralmente con quella del kernel originale.

## Criteri, fissati prima della misura

**Correttezza, obbligatoria.** Zero byte diversi nel tensore del PAD e
nell'attivazione per tutti i 32 input; zero differenze sulle 1.260 esecuzioni
della misura; attivazioni canoniche identiche all'archivio del firmware ESP32
precedente; conteggi ESP-NN 6 convoluzioni e 3 depthwise invariati; il
contatore del kernel veloce conferma quale PAD è stato eseguito. Una sola
differenza invalida la variante.

**Beneficio.** Tutti e tre devono valere:

- tempo del nodo PAD (p50) minore con la variante veloce in ogni round e per ogni input;
- `Invoke()` normale, mediana dei p50 dei round, ridotto di almeno **2 ms**;
- riduzione di `Invoke()` coerente con quella del nodo PAD: scarto entro
  `max(1 ms, 25% della riduzione del PAD)`.

**Riportati senza soglia.** Scostamento del PAD originale dai 14,628 ms del
10 novembre, tempi degli altri dieci operatori, arena, memoria interna minima,
calibrazione.

Se il beneficio non è raggiunto, l'esito è "non conveniente" e il passo
successivo è il filone memoria (RAM interna/PSRAM). Nessuna promozione
automatica nel client operativo.

## Riproduzione

```sh
mkdir -p experiments/esp32_pad_benchmark/idf/components
cp -a src/client/esp32-s3-eye-multiclient/components/esp-tflite-micro experiments/esp32_pad_benchmark/idf/components/
cp -a src/client/esp32-s3-eye-multiclient/components/esp-nn experiments/esp32_pad_benchmark/idf/components/
(cd experiments/esp32_pad_benchmark && ../../.venv/bin/python -m unittest test_fast_pad test_analysis)
IDF_COMPONENT_MANAGER=0 PLATFORMIO_CORE_DIR="$PWD/experiments/esp32_deadzone_benchmark/results/platformio-core" experiments/esp32_deadzone_benchmark/results/build-tools/bin/pio run -d experiments/esp32_pad_benchmark/idf
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_pad_benchmark/run.py --run experiments/esp32_pad_benchmark/results/NUOVO_RUN --board B
.venv/bin/python experiments/esp32_pad_benchmark/analyze.py --run experiments/esp32_pad_benchmark/results/NUOVO_RUN --output experiments/esp32_pad_benchmark/results/NUOVO_RUN/audit.json --legacy-archive experiments/esp32_input_camera_benchmark/results/2026-11-10-lut-hold-full-01/server/inference.bin
```

`test_fast_pad` compila con `g++` un confronto fra `fastPadHW` e il kernel
TFLM non modificato: la forma del modello e 2.000 forme e bordi casuali,
inclusi bordi sopra e a sinistra che il modello non usa.

Il runner identifica la scheda dal MAC, rifiuta seriali occupate, salva e
verifica gli 8 MiB di flash prima dell'installazione e ripristina in `finally`,
anche dopo errore o SIGINT/SIGTERM. Non scollegare durante flash o ripristino.
`--seed` riutilizza un backup verificato della stessa scheda; la flash attuale
viene comunque verificata per intero. Run, backup, binari e componenti copiati
sono ignorati da Git.
