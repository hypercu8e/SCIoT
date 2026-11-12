# Buffer a strisce della depthwise più piccolo — 12 novembre 2026

**Esito.** Limitare le righe per striscia della depthwise porta il picco delle
attivazioni da **178.688 a 145.760–155.168 byte**, sotto il limite di
capienza (161.323), con **gli stessi byte** del modello originale in ogni
inferenza. Il costo in tempo è piccolo: da +44 a +187 µs su 62,3 ms.

La regola fissata prima della misura sceglie **`rows5`**. È entro 50 µs dalla
più veloce che entra nel limite (`rows7`) e ha un picco minore. Picco 150.464
byte (margine 10.859), costo +81 µs. Prossimo passo indicato: **prova di
capienza nel client** con Wi-Fi e camera.

## Configurazione

Scheda B `24:ec:4a:0e:c3:14`, CPU 240 MHz, PSRAM 80 MHz, dual-core ESP-NN
spento. TFLM congelato, ESP-NN congelato più la
[patch del limite di righe](../esp-nn-strip-cap.patch), solo nella copia
dell'esperimento. Modello senza PAD `43419ffa…3b97`, riferimento col modello
originale `d41048c7…b30c` in PSRAM. Attivazioni in RAM interna. Senza Wi-Fi,
camera o HTTP. Metodo e criteri nel [README](../README.md).

## Correttezza

| Controllo | Esito |
|---|---|
| Ogni inferenza delle 4 varianti (warmup inclusi) contro il modello originale | identica |
| Righe e strisce a ogni inferenza (17/3, 7/8, 5/12, 3/24) | sempre come atteso |
| ESP-NN 6 convoluzioni / 3 depthwise; PAD eseguito | sempre; mai |
| Canonici 48/96/145 contro l'11 novembre (già verificati sul firmware ESP32 precedente) | SHA-256 identici |
| Patch applicata al componente del client riproduce la copia compilata | identica |

L'archivio del firmware precedente non è più sul disco: il confronto con
quel firmware passa per gli hash dell'11 novembre.

## Memoria

| Variante | Righe | Picco misurato | Atteso dal codice | Margine sul limite |
|---|---:|---:|---:|---:|
| `rows17` (originale) | 17 | 178.688 | 178.688 | −17.365 |
| `rows7` | 7 | 155.168 | 155.168 | +6.155 |
| `rows5` | 5 | 150.464 | 150.464 | +10.859 |
| `rows3` | 3 | 145.760 | 145.760 | +15.563 |

I picchi coincidono al byte con il calcolo dal codice ESP-NN. Indicatore solo
di capienza: nel client contano anche il blocco contiguo e la rete.

## Tempi

Tempo normale, mediana dei p50 di round. Nodo 4 dal passaggio profilato.

| Variante | Inferenza | Costo | Nodo 4 | Costo nodo 4 |
|---|---:|---:|---:|---:|
| `rows17` | 62,295 ms | — | 4,694 ms | — |
| `rows7` | 62,339 ms | +44 µs | 4,740 ms | +46 µs |
| `rows5` | 62,376 ms | +81 µs | 4,775 ms | +81 µs |
| `rows3` | 62,482 ms | +187 µs | 4,883 ms | +189 µs |

Il costo sta tutto nel nodo 4. Gli altri operatori restano entro 2 µs
([tabella per operatore](operators.csv)). Ogni variante limitata è più lenta
di `rows17` in tutti i 9 casi round × input. I p95 sono entro 25 µs dai p50
e l'instrumentazione pesa lo 0,1%.

Riproducibilità: `rows17` sta entro +0,08% dall'11 novembre (62,244 ms) e
−0,06% sul nodo 4 (4,697 ms), con lo stesso picco.

## Cosa significa

- Il buffer a strisce era l'ultimo ostacolo nel banco di prova. Con 5 righe il
  prefisso senza PAD sta in RAM interna con circa 10 KB di margine sul limite,
  e perde 81 µs dei ~22 ms guadagnati rispetto alla PSRAM.
- La patch a ESP-NN è di poche righe. Senza impostare il limite il
  comportamento resta quello originale. Portarla nel client vuol dire
  modificare il componente congelato: da decidere esplicitamente.
- Prossimo passo: prova di capienza nel client con Wi-Fi e camera, con il
  blocco contiguo misurato lì. Va anche gestito lo SHA-256 del modello senza
  PAD usato nella registrazione al server.

## Ripristino

Backup completo di 8 MiB letto e verificato (nessun seme: i backup precedenti
non sono più sul disco). Firmware sperimentale installato e verificato.
Flash originale riscritta e verificata, avvio del client confermato.
