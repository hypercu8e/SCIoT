# Buffer a strisce della depthwise più piccolo

**12 novembre 2026:** stessi byte; picco 178.688 → 150.464 byte con 5 righe
per striscia (variante scelta), sotto il limite di 161.323, costo +81 µs.
[Report](2026-11-12/report.md).

Domanda: limitando le righe per striscia della depthwise 3×3 passo 2 senza PAD,
il picco delle attivazioni del prefisso scende sotto il limite di capienza del
client? Quanto tempo costa? Le uscite restano identiche?

Contesto: [prefisso senza PAD](../esp32_nopad_benchmark/2026-11-11/report.md),
picco 178.688 byte = 110.592 (ingresso) + 27.648 (uscita) + 40.448 di buffer a
strisce, contro un limite di 161.323.

## Dal codice ESP-NN

Nodo 4 del modello senza PAD: ingresso 48×48×48, uscita 24×24×48, passo 2,
padding SAME (0 sopra/sinistra, 1 sotto/destra). Ingresso col bordo
49×49×48 = 115.248 byte, oltre la soglia di 40 KB: lavorazione a strisce.
`esp_nn_get_depthwise_conv_scratch_size_esp32s3` riserva
`filtro + righe × 2.352 + 32` byte con `righe = (40.960 − 432 − 32) / 2.352 = 17`.
Il kernel ricava le righe per striscia dalla dimensione del buffer.

| Variante | Limite righe | Righe per striscia | Strisce per inferenza | Buffer | Picco atteso |
|---|---:|---:|---:|---:|---:|
| `rows17` | nessuno (originale) | 17 | 3 | 40.448 | 178.688 |
| `rows7` | 7 | 7 | 8 | 16.928 | 155.168 |
| `rows5` | 5 | 5 | 12 | 12.224 | 150.464 |
| `rows3` | 3 | 3 | 24 | 7.520 | 145.760 |

Le altre due depthwise (bordo ≤ 40 KB o senza bordo) non usano le strisce e
restano invariate.

## La patch a ESP-NN

[`esp-nn-strip-cap.patch`](esp-nn-strip-cap.patch), applicata alla copia del
componente in `idf/components/esp-nn`; il componente del client resta intatto.

- `esp_nn_dw_strip_max_rows` (default 0 = comportamento originale) limita le
  righe nel ramo a strisce della funzione che dimensiona il buffer. La soglia
  di 40 KB tra lavorazione intera e a strisce non cambia.
- `esp_nn_dw_strip_last_rows` e `esp_nn_dw_strip_count` registrano righe per
  striscia e strisce eseguite: il firmware li controlla a ogni inferenza.

Il limite è letto sia al Prepare sia all'Invoke: il firmware lo imposta solo
prima di `AllocateTensors`. Dual-core ESP-NN spento (verificato all'avvio).

## Firmware e misura

Stesso firmware del banco senza PAD (API TFLM a due arene, PAD veloce per il
modello originale). All'avvio, per ogni variante, ricerca binaria dell'arena
minima delle attivazioni (passi di 16 byte). Riferimento: modello originale
in PSRAM. Poi 3 round × 8 blocchi, tutti col modello senza PAD e attivazioni
in RAM interna; nel round r l'ordine ruota di r−1, normali in avanti e
profilati all'indietro. Per blocco 3 input × (5 warmup + 30 misure): 2.160
inferenze misurate, 360 warmup, 10.800 record operatore.

## Criteri, fissati prima della misura

- **Correttezza, obbligatoria:** ogni attivazione di ogni variante, warmup
  inclusi, identica al modello originale; righe e strisce come in tabella a
  ogni inferenza; ESP-NN 6 convoluzioni / 3 depthwise; PAD mai eseguito.
- **Capienza:** picco misurato contro il limite di 161.323 byte (minimo libero
  peggiore del client il 9 novembre, 194.091, meno 32 KB di riserva).
- **Scelta:** fra le varianti entro il limite, la più veloce in tempo normale
  (mediana dei p50 di round); se un'altra è entro 50 µs, quella col picco
  minore. Nessuna entro il limite → serve liberare RAM nel client.
- **Tempo, riportato:** costo di ogni variante rispetto a `rows17`, sull'inferenza
  e sul nodo 4, e se è più lenta in tutti i 9 casi round × input.
- **Riproducibilità:** `rows17` contro `nopad-internal` dell'11 novembre
  (62.244 µs, nodo 4 4.697 µs, picco 178.688).

Fuori ambito: client, Wi-Fi, camera. Un esito favorevole porta alla prova di
capienza nel client, dove contano anche il blocco contiguo e la rete.

## Riproduzione

```sh
(cd experiments/esp32_nopad_benchmark && ../../.venv/bin/python make_nopad.py)
mkdir -p experiments/esp32_dwstrip_benchmark/idf/components
cp -a src/client/esp32-s3-eye-multiclient/components/esp-tflite-micro src/client/esp32-s3-eye-multiclient/components/esp-nn experiments/esp32_dwstrip_benchmark/idf/components/
(cd experiments/esp32_dwstrip_benchmark/idf/components/esp-nn && patch -p1 < ../../../esp-nn-strip-cap.patch)
(cd experiments/esp32_dwstrip_benchmark && ../../.venv/bin/python -m unittest test_analysis)
T=experiments/esp32_lossless_codec_benchmark/results/build-tools/bin  # Python 3.11, PlatformIO 6.1.18, pyserial 3.5, esptool 5.1.0
IDF_COMPONENT_MANAGER=0 $T/pio run -d experiments/esp32_dwstrip_benchmark/idf
$T/python experiments/esp32_dwstrip_benchmark/run.py --run experiments/esp32_dwstrip_benchmark/results/NUOVO_RUN --board B
.venv/bin/python experiments/esp32_dwstrip_benchmark/analyze.py --run experiments/esp32_dwstrip_benchmark/results/NUOVO_RUN --output experiments/esp32_dwstrip_benchmark/results/NUOVO_RUN/audit.json
```

Runner con backup verificato di 8 MiB e ripristino in `finally` come negli
esperimenti precedenti. `fast_pad.*`, `probe.h`, `kernel_probe.cpp` e
`describe_model.py` sono copie invariate del banco senza PAD.
