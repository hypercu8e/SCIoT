# PAD veloce sul prefisso ESP32-S3-EYE — 11 novembre 2026

**Esito: criteri superati.** Il PAD con copie per righe dà gli stessi byte del
kernel TFLM e porta il nodo 4 da **14,647 a 5,209 ms** (−64,4%). `Invoke()`
del prefisso scende da **93,913 a 84,482 ms**, cioè −9,431 ms (−10,0%).
Modello, split, componenti e arena sono invariati.

Il PAD veloce è ora limitato dalla PSRAM: in calibrazione costa quasi quanto
una semplice copia degli stessi byte (5,015 contro 4,882 ms). Un'ulteriore
riduzione richiede di cambiare dove stanno i dati, non il codice del PAD.

## Configurazione

Scheda B `24:ec:4a:0e:c3:14`, CPU 240 MHz, PSRAM 80 MHz, modello INT8 congelato
`block_2_add` (SHA-256 `d41048c7…b30c`), TFLM ed ESP-NN identici al client
HTTP v2. Arena da 1 MiB in PSRAM, stesso indirizzo e stessa occupazione,
**229.820 byte**, per entrambe le varianti. Camera, Wi-Fi e HTTP non
inizializzati. Metodo e criteri in [README](../README.md), fissati prima della misura.

## Correttezza

| Controllo | Esito |
|---|---|
| Tensore del PAD, 32 input (3 canonici + 29 pseudo-casuali), confronto nel nodo con il kernel TFLM | 3.687.936 byte confrontati, **0 diversi** |
| Attivazione finale degli stessi 32 input | 147.456 byte confrontati, **0 diversi** |
| 1.260 esecuzioni della misura (warmup inclusi), confronto integrale con il kernel originale | **0 differenze** |
| Attivazioni canoniche 48/96/145 contro l'archivio del precedente firmware ESP32 | identiche byte per byte |
| Kernel effettivamente eseguiti | 6 convoluzioni e 3 depthwise ESP-NN; PAD veloce 1 volta per inferenza solo nella variante veloce |
| Calibrazione fuori da TFLM, PSRAM e RAM interna | uscite veloce e di riferimento identiche |
| Test su PC: forma del modello + 2.000 forme e bordi casuali contro il kernel TFLM | identiche |

## Tempi

Mediana dei p50 dei tre round, 90 inferenze per round e variante.

| Misura | Originale | Veloce | Differenza |
|---|---:|---:|---:|
| `Invoke()` normale | 93,913 ms | 84,482 ms | −9,431 ms (−10,0%) |
| `Invoke()` profilato | 94,018 ms | 84,592 ms | −9,426 ms |
| Nodo 4, PAD | 14,647 ms | 5,209 ms | −9,438 ms (−64,4%) |

Il PAD veloce è più rapido in tutti i 9 casi round × input: originale fra
14,645 e 14,649 ms, veloce 5,209 ms in ogni caso. I p50 di `Invoke()` normale
per round sono 93,917 / 93,905 / 93,913 ms (originale) e 84,486 / 84,482 /
84,480 ms (veloce); i p95 restano entro 0,03 ms dai rispettivi p50.

La riduzione di `Invoke()` coincide con quella del nodo PAD (scarto 7 µs,
tolleranza 2,36 ms). Gli altri dieci operatori variano fra −9 e +17 µs.
Strumentazione: +0,111% sull'originale, +0,130% sulla veloce.

Il PAD originale misura 14,647 ms contro 14,628 ms del
[10 novembre](../../esp32_layer_profile/2026-11-10/report.md): +0,13%.

[Tabella completa per operatore](operators.csv).

## Dove va il tempo: calibrazione

Stessi 110.592 byte di ingresso, fuori da TFLM, 30 misure ciascuno (p50).

| Memoria | `memcpy` | PAD veloce | PAD TFLM |
|---|---:|---:|---:|
| PSRAM | 4,882 ms | 5,015 ms | 17,856 ms |
| RAM interna | 0,289 ms | 0,312 ms | 15,698 ms |

- Il PAD TFLM costa circa 15,7 ms anche in RAM interna: il suo limite era il
  calcolo per singolo byte, non la memoria.
- Il PAD veloce costa quasi quanto una copia: in PSRAM il limite è ora la
  banda della memoria esterna.
- In RAM interna la stessa operazione richiede circa 0,3 ms. Questo indica il
  margine di un futuro esperimento sulla collocazione dei buffer, **non** un
  risultato già ottenuto nel modello: l'arena resta in PSRAM e spostare i
  tensori richiede memoria interna libera e una nuova misura completa.

Nel grafo il PAD veloce costa 5,209 ms, circa 0,2 ms più della calibrazione:
differenza compatibile con l'overhead del nodo e con lo stato della cache,
non isolata.

## Memoria

Arena identica, memoria interna libera minima 145.623 byte e memoria interna
libera nei blocchi 373.047 byte in entrambe le varianti. Il PAD veloce non
aggiunge buffer.

## Limiti

- Tempi di `Invoke()` del solo prefisso, non FPS camera, latenza HTTP o ciclo
  completo. Il ciclo completo comprende acquisizione, conversione e rete.
- Una scheda, tre input canonici per i tempi. La correttezza vale per i 32
  input provati e per i casi del test su PC, non è una dimostrazione formale.
- Non misurati energia, temperatura o picco di RAM.
- Il PAD veloce esiste solo nel progetto sperimentale, non nel client operativo.

## Ripristino

Backup di 8 MiB verificato prima del flash (seme dal backup del 10 novembre,
flash attuale comunque verificata per intero). Firmware sperimentale
installato e verificato. A fine prova **flash originale ripristinata e
verificata prima del boot**, avvio originale confermato. Nessun watchdog,
panic o brownout nel log seriale. Nessun server, Pixel o inoltro di rete.

Run grezzo, backup e binari in `results/2026-11-11-B-01/`, ignorati da Git.
Audit completo pubblicato come [summary.json](summary.json); mappa dei tensori
in [model-map.json](model-map.json).
