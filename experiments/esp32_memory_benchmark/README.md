# Attivazioni in RAM interna sul prefisso ESP32-S3-EYE

**11 novembre 2026: il filone merita.** `Invoke()` 84,723 → 62,289 ms
(−26,5%), di cui 17,5 ms su operatori diversi dal PAD; zero differenze.
Limite superiore senza Wi-Fi/camera. [Report](2026-11-11/report.md).

Domanda: quanto dei circa 84,5 ms di `Invoke()` (con il
[PAD veloce](../esp32_pad_benchmark/2026-11-11/report.md)) è attesa sulla PSRAM?
Si misura spostando attivazioni e scratch ESP-NN in RAM interna, senza
Wi-Fi né camera. È un **limite superiore** per decidere se il filone memoria
merita lavoro, non una configurazione installabile nel client.

## Vincoli noti prima della misura

- Picco delle attivazioni: **225.840 byte** al nodo PAD (110.592 ingresso +
  115.248 uscita). Il client operativo con Wi-Fi e camera ha 217–250 KB
  liberi in RAM interna, minimo 194 KB (campagna del 9 novembre): non ci sta.
- Senza il nodo PAD il picco scenderebbe a circa 138 KB: rimuoverlo dal grafo
  è una decisione separata, fuori da questo esperimento.
- Il blocco interno contiguo disponibile non è mai stato misurato. Il firmware
  lo stampa all'avvio; se 240 KiB non sono disponibili emette
  `internal_arena_unavailable`, si ferma e il runner ripristina la flash.

## Varianti

Stessa API TFLM a due arene (`MicroAllocator::Create(persistent, …,
non_persistent, …)`), stesso PAD veloce, stessi componenti e modello:

| Variante | Strutture fisse | Attivazioni e scratch |
|---|---|---|
| `psram` | PSRAM, 64 KiB | PSRAM, 240 KiB |
| `internal` | PSRAM, 64 KiB | RAM interna, 240 KiB |

Buffer allocati una volta all'avvio, indirizzi fissi. A ogni blocco il
firmware verifica con `esp_ptr_internal`/`esp_ptr_external_ram` che i tensori
di ingresso e uscita stiano nella memoria prevista.

## Protocollo

Scheda B, CPU 240 MHz, PSRAM 80 MHz, ESP-NN. Tre input canonici 48/96/145.
Tre round da quattro blocchi (variante × normale/profilato), ordine bilanciato
come per il PAD: round 1 P-n, I-n, I-p, P-p; round 2 I-p, P-p, P-n, I-n;
round 3 I-n, P-n, P-p, I-p. Per blocco 3 input × (5 warmup + 30 misure):
1.080 inferenze misurate, 180 warmup, 5.940 record operatore. Riferimento:
prima esecuzione `psram` normale di ciascun input; ogni attivazione, warmup
inclusi, è confrontata integralmente con esso.

## Regola di decisione, fissata prima della misura

Guadagno per nodo = mediana dei p50 dei round `psram` − `internal`.

- **Somma dei guadagni sugli operatori diversi dal PAD ≥ 5 ms**: il filone
  merita. Prossimi passi da approvare a parte: rimozione del PAD dal grafo con
  verifica byte per byte, poi prova di capienza nel client con Wi-Fi e camera.
- **Sotto 5 ms**: filone chiuso per ora; PAD veloce e LUT vanno nel client.

Il guadagno sul PAD è riportato separatamente: la rimozione del nodo lo
otterrebbe comunque. Correttezza obbligatoria: zero differenze, attivazioni
canoniche identiche al precedente firmware ESP32, ESP-NN 6/3, PAD veloce una
volta per inferenza. Riportati senza soglia: confronto della variante `psram`
con gli 84,482 ms dell'11 novembre (arena unica), memoria interna e blocco
contiguo, tempi di ogni operatore.

Limiti: senza Wi-Fi e camera non c'è contesa DMA sulla PSRAM né la memoria
occupata del client reale.

## Riproduzione

```sh
mkdir -p experiments/esp32_memory_benchmark/idf/components
cp -a src/client/esp32-s3-eye-multiclient/components/esp-tflite-micro experiments/esp32_memory_benchmark/idf/components/
cp -a src/client/esp32-s3-eye-multiclient/components/esp-nn experiments/esp32_memory_benchmark/idf/components/
(cd experiments/esp32_memory_benchmark && ../../.venv/bin/python -m unittest test_analysis)
IDF_COMPONENT_MANAGER=0 PLATFORMIO_CORE_DIR="$PWD/experiments/esp32_deadzone_benchmark/results/platformio-core" experiments/esp32_deadzone_benchmark/results/build-tools/bin/pio run -d experiments/esp32_memory_benchmark/idf
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_memory_benchmark/run.py --run experiments/esp32_memory_benchmark/results/NUOVO_RUN --board B
.venv/bin/python experiments/esp32_memory_benchmark/analyze.py --run experiments/esp32_memory_benchmark/results/NUOVO_RUN --output experiments/esp32_memory_benchmark/results/NUOVO_RUN/audit.json --legacy-archive experiments/esp32_input_camera_benchmark/results/2026-11-10-lut-hold-full-01/server/inference.bin
```

Runner, backup e ripristino come negli esperimenti precedenti: identità dal
MAC, 8 MiB salvati e verificati prima del flash, ripristino in `finally`.
`fast_pad.*`, `probe.h` e `kernel_probe.cpp` sono copie invariate
dall'esperimento PAD.
