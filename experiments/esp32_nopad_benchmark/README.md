# Prefisso senza nodo PAD

**11 novembre 2026:** stessi byte; picco attivazioni 225.840 → 178.688 byte,
sopra il limite di capienza (161.323). Tempo −1,7 ms in PSRAM, invariato in
RAM interna. [Report](2026-11-11/report.md).

Domanda: togliere il nodo PAD dal grafo, facendo il bordo nella depthwise
successiva con padding SAME, dà gli stessi byte, quanta RAM interna serve
alle attivazioni e quanto tempo cambia?

Contesto: con le [attivazioni in RAM interna](../esp32_memory_benchmark/2026-11-11/report.md)
il prefisso scende da 84,7 a 62,3 ms, ma il picco di 225.840 byte (al PAD)
non entra nel client con Wi-Fi e camera (minimo libero 194 KB).

## Il modello riscritto

`make_nopad.py` parte dal prefisso congelato (SHA-256 `d41048c7…b30c`),
controlla la struttura attesa e si ferma se è diversa: PAD su `1×48×48×48`
con paddings `[[0,0],[0,1],[0,1],[0,0]]`, zero point −128 condiviso con
l'uscita, depthwise 3×3 passo 2, VALID, mult 1. Su 48×48 con passo 2 il
padding SAME di TFLite aggiunge 0 sopra/sinistra e 1 sotto/destra, come il PAD.

Riscrittura: depthwise collegata all'ingresso del PAD con padding SAME, nodo
PAD e tensori dei paddings e dell'uscita PAD rimossi, opcode PAD rimosso.
Pesi, quantizzazioni e altri operatori identici. Il modello generato
(16.048 byte, SHA-256 `43419ffa…3b97`) e il suo header sono ignorati da Git:
lo script li ricrea in modo deterministico.

`test_nopad_model.py` confronta su PC (TFLite senza delegate) originale e
riscritto su 3 input canonici e 500 casuali (seme 20261111): uscite
**identiche byte per byte**. Controprova: con i pesi della depthwise
alterati, tutte le 20 uscite di prova cambiano.

## Atteso dal codice ESP-NN

Il ramo 3×3 mult 1 di `esp_nn_depthwise_conv_s8_esp32s3.c` gestisce il
padding asimmetrico. Con un ingresso padded oltre 40 KB lavora a strisce di
righe copiate in un buffer di circa 40 KB, riservato nell'arena. Stima del
picco senza PAD: 110.592 + 27.648 + ~40.400 ≈ 179 KB. Oggi invece la
depthwise legge direttamente l'uscita del PAD, senza copie: il tempo del nodo
può crescere anche se il PAD sparisce.

## Varianti

Firmware dall'esperimento memoria: due arene, PAD veloce per il modello
originale, stesse dimensioni dei buffer.

| Variante | Modello | Attivazioni |
|---|---|---|
| `pad-psram` | originale + PAD veloce | PSRAM |
| `pad-internal` | originale + PAD veloce | RAM interna |
| `nopad-psram` | senza PAD | PSRAM |
| `nopad-internal` | senza PAD | RAM interna |

All'avvio, per ciascun modello, ricerca binaria della più piccola arena delle
attivazioni che TFLM riesce a pianificare (passi di 16 byte, senza inferenze):
evento `activation_peak`. Riferimento: modello originale in PSRAM, prima di
ogni blocco misurato. Poi 3 round × 8 blocchi; nel round r l'ordine delle
varianti ruota di r−1, prima i blocchi normali in avanti, poi i profilati
all'indietro. Per blocco 3 input × (5 warmup + 30 misure): 2.160 inferenze
misurate, 360 warmup, 11.340 record operatore.

## Criteri, fissati prima della misura

- **Correttezza, obbligatoria:** PC identico su 503 input; sulla scheda ogni
  attivazione delle quattro varianti, warmup inclusi, identica al riferimento;
  canonici identici al precedente firmware ESP32; ESP-NN 6/3; PAD veloce 1
  volta per inferenza col modello originale, 0 senza PAD.
- **Capienza, decide il passo dopo:** il picco senza PAD si confronta col
  minimo libero peggiore del client il 9 novembre (194.091 byte) meno una
  riserva di 32 KB: limite **161.323 byte**.
  - entro il limite → prossima mossa: prova di capienza nel client con Wi-Fi e camera;
  - oltre → serve anche liberare RAM interna nel client (buffer Wi-Fi/lwIP in
    PSRAM), da decidere a parte per il rischio sulla rete.
  È solo un indicatore: nel client conta anche il blocco contiguo, da misurare lì.
- **Tempo, riportato:** `nopad` contro `pad` in PSRAM e in RAM interna;
  coppia PAD + depthwise contro la depthwise unica. Se `nopad` non è più
  veloce, il vantaggio è solo di memoria.

Fuori ambito: client e server. Cambiare il modello cambia il suo SHA-256, che
il client usa nella registrazione al server: andrà gestito prima del porting.

## Riproduzione

```sh
mkdir -p experiments/esp32_nopad_benchmark/idf/components
cp -a src/client/esp32-s3-eye-multiclient/components/esp-tflite-micro experiments/esp32_nopad_benchmark/idf/components/
cp -a src/client/esp32-s3-eye-multiclient/components/esp-nn experiments/esp32_nopad_benchmark/idf/components/
(cd experiments/esp32_nopad_benchmark && ../../.venv/bin/python make_nopad.py && ../../.venv/bin/python -m unittest test_nopad_model test_analysis)
IDF_COMPONENT_MANAGER=0 PLATFORMIO_CORE_DIR="$PWD/experiments/esp32_deadzone_benchmark/results/platformio-core" experiments/esp32_deadzone_benchmark/results/build-tools/bin/pio run -d experiments/esp32_nopad_benchmark/idf
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_nopad_benchmark/run.py --run experiments/esp32_nopad_benchmark/results/NUOVO_RUN --board B
.venv/bin/python experiments/esp32_nopad_benchmark/analyze.py --run experiments/esp32_nopad_benchmark/results/NUOVO_RUN --output experiments/esp32_nopad_benchmark/results/NUOVO_RUN/audit.json --legacy-archive experiments/esp32_input_camera_benchmark/results/2026-11-10-lut-hold-full-01/server/inference.bin
```

Runner con backup verificato e ripristino in `finally` come negli esperimenti
precedenti. `fast_pad.*`, `probe.h` e `kernel_probe.cpp` sono copie invariate.
