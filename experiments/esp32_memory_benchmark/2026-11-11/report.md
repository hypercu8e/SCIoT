# Attivazioni in RAM interna — 11 novembre 2026

**Esito: il filone memoria merita.** Con le attivazioni in RAM interna
`Invoke()` del prefisso scende da **84,723 a 62,289 ms**: −22,434 ms, −26,5%.
Il guadagno sugli operatori diversi dal PAD è di **17,516 ms**, oltre la
soglia di 5 ms fissata prima della misura. Risultati identici byte per byte.

È un **limite superiore** misurato senza Wi-Fi né camera. Nel client
operativo le attivazioni non ci stanno così come sono: vedere i vincoli.

## Configurazione

Scheda B `24:ec:4a:0e:c3:14`, CPU 240 MHz, PSRAM 80 MHz, modello INT8 congelato
`block_2_add`, TFLM ed ESP-NN identici al client HTTP v2, PAD veloce
dell'[esperimento precedente](../../esp32_pad_benchmark/2026-11-11/report.md).
Stessa API a due arene per entrambe le varianti: strutture fisse in PSRAM
(64 KiB), attivazioni e scratch ESP-NN in PSRAM oppure in RAM interna
(240 KiB). Occupazione totale identica, 229.836 byte. Indirizzi fissi per
tutti i blocchi; a ogni blocco il firmware ha verificato che ingresso e
uscita stessero nella memoria prevista. Metodo e regola in [README](../README.md).

## Correttezza

Zero differenze sulle 1.260 esecuzioni (warmup inclusi) rispetto al
riferimento. Attivazioni canoniche 48/96/145 identiche all'archivio del
precedente firmware ESP32. ESP-NN 6 convoluzioni e 3 depthwise e PAD veloce
una volta per inferenza, in ogni esecuzione.

## Tempi

Mediana dei p50 dei tre round.

| Misura | PSRAM | RAM interna | Guadagno |
|---|---:|---:|---:|
| `Invoke()` normale | 84,723 ms | 62,289 ms | −22,434 ms (−26,5%) |
| `Invoke()` profilato | 84,829 ms | 62,384 ms | −22,445 ms |
| Solo nodo PAD | 5,253 ms | 0,351 ms | −4,902 ms |
| Operatori diversi dal PAD | | | **−17,516 ms** |

La RAM interna è più veloce in tutti i 9 casi round × input. p50 per round:
84,715 / 84,723 / 84,729 ms (PSRAM) e 62,289 / 62,295 / 62,285 ms (interna);
p95 entro 0,03 ms dai p50.

| Nodo | Operatore | Uscita | PSRAM ms | Interna ms | Guadagno |
|---:|---|---|---:|---:|---:|
| 0 | CONV_2D 3×3 | 48×48×16 | 23,462 | 22,857 | 2,6% |
| 1 | DEPTHWISE | 48×48×16 | 8,669 | 6,067 | 30,0% |
| 2 | CONV_2D 1×1 | 48×48×8 | 3,851 | 2,833 | 26,4% |
| 3 | CONV_2D 1×1 espansione | 48×48×48 | 18,064 | 15,133 | 16,2% |
| 4 | PAD veloce | 49×49×48 | 5,253 | 0,351 | 93,3% |
| 5 | DEPTHWISE stride 2 | 24×24×48 | 9,525 | 4,323 | 54,6% |
| 6 | CONV_2D 1×1 | 24×24×8 | 1,505 | 0,875 | 41,9% |
| 7 | CONV_2D 1×1 espansione | 24×24×48 | 4,338 | 3,793 | 12,6% |
| 8 | DEPTHWISE | 24×24×48 | 7,729 | 4,412 | 42,9% |
| 9 | CONV_2D 1×1 | 24×24×8 | 1,421 | 0,878 | 38,2% |
| 10 | ADD | 24×24×8 | 0,936 | 0,814 | 13,0% |

Le depthwise guadagnano di più (30–55%): fanno poco calcolo per byte letto,
quindi pesa di più l'accesso alla memoria. La prima convoluzione cambia poco
(2,6%): il suo costo è il calcolo. [Tabella CSV](operators.csv).

La variante `psram` a due arene misura 84,723 ms contro 84,482 ms
dell'esperimento PAD ad arena unica: +0,29%. Strumentazione +0,13% e +0,15%.

## Memoria

| Momento | RAM interna libera | Blocco contiguo più grande |
|---|---:|---:|
| Avvio, senza Wi-Fi e camera | 373.443 byte | 278.528 byte |
| Dopo l'allocazione delle attivazioni interne | 127.679 byte | 33.792 byte |
| Minimo durante la prova | 127.371 byte | |

## Vincoli per il client operativo

- Il picco delle attivazioni è **225.840 byte** al nodo PAD. Il client con
  Wi-Fi e camera ha 217–250 KB liberi in RAM interna, minimo 194 KB
  (campagna del 9 novembre), e il blocco contiguo è certamente più piccolo.
  **Così com'è non ci sta.**
- Senza il nodo PAD il picco scenderebbe a circa 138 KB (nodo 5: 110.592 +
  27.648), più lo scratch ESP-NN. La depthwise con padding SAME e passo 2 su
  48×48 aggiunge da sola una riga sotto e una colonna a destra, con bordo pari
  allo zero point: in teoria il risultato resta identico. Va verificato.
- Anche con 138 KB il margine nel client sarebbe di circa 50 KB rispetto al
  minimo osservato, e serve un blocco **contiguo**: va misurato con Wi-Fi e
  camera attivi.
- Senza Wi-Fi e camera non c'è contesa DMA sulla PSRAM: nel client il
  vantaggio potrebbe essere diverso, in entrambe le direzioni.

## Prossimi passi, da approvare

1. Rimuovere il nodo PAD dal grafo (padding SAME nella depthwise), con
   verifica byte per byte su PC e scheda e misura della memoria di picco.
2. Prova di capienza nel client con Wi-Fi e camera: blocco contiguo
   disponibile, margine minimo, stabilità.
3. Solo dopo: portare LUT, PAD (o grafo senza PAD) e arena interna nel
   client operativo e misurare il ciclo completo.

## Ripristino

Backup di 8 MiB verificato (seme dal backup della prova PAD di oggi, flash
attuale comunque verificata per intero). Firmware sperimentale installato e
verificato. Flash originale ripristinata e verificata prima del boot, avvio
originale confermato. Nessun watchdog, panic o brownout nel log seriale.
Nessun server, Pixel o inoltro di rete. Dati grezzi in
`results/2026-11-11-B-01/`, ignorati da Git; audit in [summary.json](summary.json).
