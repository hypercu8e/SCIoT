# Prefisso senza nodo PAD — 11 novembre 2026

**Esito.** Il modello senza PAD dà **gli stessi byte** dell'originale, su PC e
sulla scheda. Il picco delle attivazioni scende da **225.840 a 178.688 byte**
(−47.152), ma resta sopra il limite di capienza fissato prima della misura
(161.323 byte). Il tempo migliora solo con le attivazioni in PSRAM (−1,7 ms);
in RAM interna resta uguale.

Prossimo passo indicato dalla regola: **liberare RAM interna nel client**
prima della prova di capienza. Da decidere, per il rischio sulla rete.

## Configurazione

Scheda B `24:ec:4a:0e:c3:14`, CPU 240 MHz, PSRAM 80 MHz, TFLM ed ESP-NN
congelati, stessa API a due arene dell'[esperimento memoria](../../esp32_memory_benchmark/2026-11-11/report.md).
Modello originale `d41048c7…b30c` con PAD veloce; modello riscritto
`43419ffa…3b97` da `make_nopad.py`. Senza Wi-Fi, camera o HTTP.
Metodo e criteri nel [README](../README.md).

## Correttezza

| Controllo | Esito |
|---|---|
| PC, TFLite senza delegate, 3 canonici + 500 casuali | uscite identiche |
| Controprova PC con pesi della depthwise alterati | 20/20 uscite diverse: il confronto vede le differenze |
| Scheda, tutte le esecuzioni delle 4 varianti (warmup inclusi) | identiche al modello originale |
| Canonici 48/96/145 contro il precedente firmware ESP32 | identici |
| ESP-NN 6 convoluzioni / 3 depthwise; PAD veloce 1 volta (originale) / 0 (senza PAD) | sempre |

## Memoria

Arena minima delle attivazioni pianificabile da TFLM (ricerca binaria a passi di 16 byte):

| Modello | Attivazioni minime | Arena totale usata |
|---|---:|---:|
| Originale | 225.840 byte | 229.836 byte |
| Senza PAD | **178.688 byte** | 182.556 byte |

Il valore senza PAD coincide con la stima dal codice ESP-NN: 110.592
(ingresso) + 27.648 (uscita) + ~40.400 di buffer per la lavorazione a
strisce della depthwise con padding.

Capienza nel client: minimo libero peggiore il 9 novembre 194.091 byte,
riserva 32 KB, limite 161.323 byte. **178.688 lo supera di 17.365 byte.**
Senza riserva il margine sarebbe 15.403 byte, troppo poco per Wi-Fi e camera,
e servirebbe comunque un blocco contiguo di quella dimensione.

## Tempi

Mediana dei p50 dei tre round, `Invoke()` normale.

| Attivazioni | Originale + PAD veloce | Senza PAD | Differenza |
|---|---:|---:|---:|
| PSRAM | 84,701 ms | 82,993 ms | −1,708 ms |
| RAM interna | 62,268 ms | 62,244 ms | −0,024 ms |

Il nodo PAD sparisce, ma la depthwise che fa il bordo da sola costa di più:

| Attivazioni | PAD + depthwise | Depthwise con SAME | Differenza |
|---|---:|---:|---:|
| PSRAM | 5,250 + 9,533 = 14,783 ms | 13,421 ms | −1,362 ms |
| RAM interna | 0,346 + 4,334 = 4,680 ms | 4,697 ms | +0,018 ms |

In RAM interna il PAD veloce costava già pochissimo, e la copia a strisce
della depthwise lo compensa. Gli altri operatori restano entro ±0,2 ms.
Senza PAD è comunque più veloce in tutti i 9 casi round × input, anche in RAM
interna, ma di soli 24 µs. p95 entro 0,03 ms dai p50.

Riproducibilità: le varianti col modello originale stanno entro 0,03%
dall'esperimento memoria (84,723 / 62,289 ms). [Tabella per operatore](operators.csv).

## Cosa significa

- Togliere il PAD vale per la **memoria** (−47 KB), non per il tempo quando le
  attivazioni stanno in RAM interna.
- Da solo non basta a entrare nel client. Le leve rimaste, da valutare:
  1. **liberare RAM interna nel client**: oggi i buffer Wi-Fi/lwIP stanno in
     RAM interna (`CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP` disattivo); spostarli
     in PSRAM potrebbe liberare decine di KB, ma tocca la rete, già fragile;
  2. **ridurre il buffer a strisce della depthwise** (circa 40 KB): con poche
     righe il picco scenderebbe verso 145 KB. Richiede di modificare il
     componente ESP-NN congelato e di misurare l'effetto sul tempo.
- Da gestire prima del porting: il modello senza PAD ha un altro SHA-256, che
  il client usa nella registrazione al server.

## Ripristino

Backup di 8 MiB verificato (seme dal backup dell'esperimento memoria, flash
comunque verificata per intero). Firmware sperimentale installato e
verificato; flash originale ripristinata e verificata prima del boot, avvio
originale confermato. Nessun watchdog, panic o brownout. Nessun server, Pixel
o rete. Dati grezzi in `results/2026-11-11-B-01/`, ignorati da Git; audit in
[summary.json](summary.json), mappe in [model-map.json](model-map.json) e
[model-map-nopad.json](model-map-nopad.json).
