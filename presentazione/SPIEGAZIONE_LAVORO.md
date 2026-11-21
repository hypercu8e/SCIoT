# SCIoT: cosa abbiamo fatto e perché

*Documento di ripasso per la presentazione al relatore. Aggiornato al 19 novembre 2026.*
*Copre il lavoro dal 15 ottobre al 18 novembre 2026. Tutti i numeri vengono dai report del repository, linkati in ogni sezione.*

Le slide sono in [`SCIoT_presentazione.pptx`](SCIoT_presentazione.pptx) e hanno note per il relatore. Per sapere come funziona il codice, vedi [`DETTAGLI_IMPLEMENTATIVI.md`](DETTAGLI_IMPLEMENTATIVI.md). Questo file contiene la spiegazione completa: leggilo prima, poi usa le slide come traccia.

---

## 0. In trenta secondi

- **SCIoT** divide una rete neurale tra un microcontrollore (ESP32-S3-EYE con camera) e un server. La scheda esegue i primi layer (il **prefisso**), invia il risultato intermedio (le **attivazioni**) e il server completa la rete (il **suffisso**).
- Il tirocinio si chiama **Multi Device Split Computing**. Il professore aveva indicato due punti deboli: **la comunicazione** e il fatto che il sistema **gestiva bene un solo client**.
- Il percorso, in ordine:
  1. compressione delle attivazioni su PC;
  2. passaggio a **INT8 + ESP-NN** sulla scheda: **5× più veloce** e **−75% di byte**;
  3. codec lossless (**Rice**), che conviene solo con poca banda;
  4. un servizio **multi-client HTTP v2**, validato con **due ESP32 reali per un'ora**;
  5. le ottimizzazioni del **ciclo camera**: tabella LUT, che porta il ciclo a **−27%**, PAD veloce, memoria;
  6. la scoperta che il **clock della camera (XCLK) blocca il Wi-Fi**;
  7. il confronto tra i trasporti, vinto da **HTTP persistente**;
  8. il **frame skip**.
- **Il messaggio principale:** "meno byte" non vuol dire automaticamente "meno attesa". Ogni ottimizzazione va misurata sul ciclo completo e sulla scheda vera. Ogni misura è stata ripetuta, verificata byte per byte e chiusa ripristinando il firmware originale della scheda.

---

## 1. Il contesto: cos'è SCIoT e cos'è lo split computing

```text
 camera ─► [ESP32: prefisso della rete] ─► attivazioni ─► Wi-Fi ─► [server: suffisso] ─► rilevamenti
              (primi layer, INT8)            (4.608 B)               (layer rimanenti)
```

- Il **modello** è FOMO, un rilevatore di oggetti leggero di Edge Impulse. Usiamo il candidato pubblico "Beer vs. cans": ingresso 96×96 in scala di grigi, uscita su una griglia 12×12 con sfondo e due classi. **Non l'abbiamo riaddestrato.**
- Il **punto di split** decide dove ci si ferma sulla scheda. Abbiamo scelto `block_2_add` perché richiede **un solo tensore** di confine (24×24×8). Altri tagli, a causa dei rami residui della rete, ne richiedono più di uno.
- Il **compromesso fondamentale:** più layer sulla scheda significano più calcolo locale. In cambio il messaggio *può* essere più piccolo, ma non sempre: alcuni layer espandono i dati.

**Cosa abbiamo trovato leggendo il codice originale** ([spiegazione del repository](../SPIEGAZIONE_REPOSITORY.md), [analisi dei miglioramenti](../ANALISI_MIGLIORAMENTI_SCIOT.md)):
- Il codice ha già i trasporti MQTT, HTTP e WebSocket.
- Il percorso originale invia attivazioni **float32** e manda anche l'immagine originale in un messaggio a parte.
- Lo stato è **condiviso tra i client**, quindi con più dispositivi la scelta dello split e le statistiche si mescolano.
- Nei firmware c'erano tre difetti: la durata dell'interprete, la serializzazione degli identificativi e le lunghezze dei tempi inviati. **Sono stati corretti il 19 ottobre** e verificati con test nativi ([report](../experiments/firmware_fixes_2026-10-19/README.md)).

**La domanda guida:**
> Quando il risparmio di trasmissione compensa il costo di calcolo e di memoria sul dispositivo, mantenendo predizioni fedeli?

---

## 2. Il setup sperimentale

| Elemento | Scelta |
|---|---|
| Scheda | ESP32-S3-EYE (CPU 240 MHz, PSRAM 8 MB, camera OV2640). Due esemplari, **A** e **B** |
| Modello | FOMO Beer/can, 96×96×1, split `block_2_add` |
| Runtime | TensorFlow Lite Micro con **ESP-NN**, i kernel ottimizzati di Espressif per ESP32-S3 |
| Server | Python / FastAPI (Uvicorn) su PC fisso o laptop |
| Reti usate | Hotspot Pixel 9a con USB/ADB reverse (fino al 10 novembre), router domestico (dal 16 novembre) |

**Il metodo, uguale in ogni esperimento:**
- **Backup completo della flash** della scheda (8 MiB) prima di caricare il firmware sperimentale. Alla fine si **ripristina, si verifica il digest e si conferma il boot originale**.
- **Criteri fissati prima della misura**, per esempio "mediana almeno −5% e p95 non oltre +5% in tutte le coppie".
- **Ordini alternati** (A→B, B→A) e più avvii indipendenti, così le variazioni della rete non vengono scambiate per un effetto.
- **Equivalenza numerica:** attivazioni e uscite confrontate **byte per byte** con un riferimento. Le ottimizzazioni dichiarate "lossless" non cambiano nulla del risultato.
- Report, JSON e hash sono versionati in Git. I log grezzi, i firmware e i backup restano nelle cartelle `results/`, ignorate da Git.

---

## 3. Il percorso, fase per fase

### Fase A — Compressione delle attivazioni su PC (15–18 ottobre)

**Cosa.** Abbiamo estratto le attivazioni di `block_2_add` da 146 frame del video `VideoWithCan.mp4`: in float32 sono **18.432 B/frame**. Poi abbiamo provato diversi codec.
- **Lossless:** zlib, XOR tra frame consecutivi e riordino dei byte. Il migliore, XOR+shuffle+zlib, fa **−14,96%**, ma solo **5,71 punti** vengono davvero dal riferimento temporale.
- **Lossy controllato:** arrotondamento con passo 0,001. Indipendente **−40,61%**, temporale **−48,66%**. Nessuna cella cambia a soglia 0,5 nel campione.
- **Prova TCP su loopback:** il codec temporale risparmia il 13,56% di byte, ma **aumenta l'attesa** (da 0,67 a 1,48 ms/frame). Su un collegamento velocissimo il calcolo del codec costa più di quanto si risparmia.

**Perché.** La prima pista suggerita era la comunicazione. Volevamo capire quanto spazio c'era prima di toccare l'hardware.

**Lezione.** *Meno byte ≠ meno attesa.* Da qui in poi misuriamo sempre il tempo completo.
Fonti: [baseline lossless](../experiments/activation_compression/baseline_2026-10-15/README.md), [lossy](../experiments/activation_compression/lossy_2026-10-17/README.md), [TCP](../experiments/activation_compression/tcp_2026-10-18/README.md).

### Fase B — Quantizzazione del modello: INT8 e 16×8 (18–19 ottobre, PC)

**Cosa.** Abbiamo convertito il modello in **INT8** (pesi e attivazioni a 8 bit) e in **16×8** (attivazioni a 16 bit, pesi a 8). Per la calibrazione abbiamo usato 48 frame, separati dai 98 di valutazione.

| | TFLite float32 | INT8 | 16×8 |
|---|---:|---:|---:|
| Byte al confine | 18.432 | **4.608** | 9.216 |
| Celle cambiate a soglia 0,5 (su 14.112) | 0 | 25 | 18 |

Lo split INT8 coincide **byte per byte** con il modello INT8 intero su tutti i 146 frame. Il 16×8 è più fedele ma non gira sul runtime ESP32 disponibile: manca una depthwise con ingresso INT16.
Fonti: [INT8](../experiments/activation_compression/int8_2026-10-18/README.md), [16×8](../experiments/activation_compression/16x8_2026-10-18/README.md), [preparazione ESP32](../experiments/activation_compression/esp32_prep_2026-10-19/README.md).

### Fase C — FLOAT32 vs INT8 + ESP-NN sulla scheda (27 ottobre) ★

**Cosa.** È il primo confronto fisico: stessa scheda, stesso split, server HTTP sul PC, **816 richieste validate** in due sessioni.

| Misura | FLOAT32 | INT8 + ESP-NN | Variazione |
|---|---:|---:|---:|
| Attivazioni per immagine | 18.432 B | 4.608 B | **−75%** |
| Scambio HTTP completo | 20.647 B | 6.822 B | −67% |
| Prefisso sulla scheda (p50) | 813,7 ms | 94,6 ms | **8,6× più veloce** |
| Tempo completo, immagini identiche (p50) | 859,9 ms | 161,8 ms | **5,3× più veloce** |
| Camera continua | 1,05–1,14 fps | 4,89–5,54 fps | ~5× |
| Qualità su 84 foto annotate (F1, classe ignorata) | 96,52% | 96,92% | ≈ uguale |

**Perché funziona.** INT8 riduce di 4 volte i byte da inviare e permette a **ESP-NN** di usare le istruzioni vettoriali dell'ESP32-S3: sul prefisso INT8 girano 6 convoluzioni e 3 depthwise ottimizzate, sul FLOAT32 nessuna.

**Limiti.** Le classi beer/can non sono distinte, perché l'ordine dei canali non è confermato. Non sappiamo se le foto sono indipendenti dal training.
Fonte: [report del 27 ottobre](../experiments/esp32_representation_benchmark/espnn_2026-10-27/report.md).

### Fase D — Codec lossless su INT8: zlib e Rice (28 ottobre – 1 novembre)

**Cosa.** Dopo INT8, il messaggio da 4.608 B si può comprimere ancora?
- **zlib indipendente:** il payload scende a 3.949 B (−14,3%), ma la compressione costa **circa 6,8 ms** e il ciclo **peggiora** (da 157,4 a 162,7 ms) ([report](../experiments/esp32_int8_compression_benchmark/2026-10-28/report.md)).
- **Rice temporale:** in pratica, una codifica efficiente della differenza rispetto al frame precedente. Arriva a **2.534 B/frame (−45%)** e resta lossless. Abbiamo scritto un decoder C++ lato server, che porta la decodifica da ~12 a **0,4 ms**.

| Rete | Raw p50 | Rice p50 | Variazione | Criterio |
|---|---:|---:|---:|---|
| Wi-Fi ordinaria (C++) | 177,4 ms | 178,8 ms | +0,8% | non superato |
| Proxy 1000 kbit/s | 213,3 | 202,2 | −5,2% | non superato |
| Proxy 800 kbit/s | 221,7 | 207,8 | −6,3% | superato |
| Proxy 600 kbit/s | 240,1 | 219,6 | −8,6% | superato |
| Proxy 512 kbit/s | 241,9 | 221,3 | −8,5% | superato |
| Proxy 128 kbit/s | 478,1 | 349,5 | **−26,9%** | superato |

**Conclusione.** Rice conviene solo **sotto circa 800–900 kbit/s**. Su una Wi-Fi normale **raw INT8 resta la scelta**. La soglia viene da 7.008 richieste fisiche, ma è un intervallo tra punti osservati, non un intervallo di confidenza.
Fonti: [codec lossless](../experiments/esp32_lossless_codec_benchmark/report.md), [soglia Rice](../experiments/esp32_rice_threshold_benchmark/sweep_2026-11-01/report.md).

### Fase E — Multi-client: HTTP v2 (28 ottobre – 9 novembre) ★

**Cosa.** È il secondo problema indicato dal professore. Abbiamo costruito un servizio **HTTP v2** con:
- stato separato per **dispositivo / sessione / richiesta**;
- **coda limitata** (risposta 429 quando è piena);
- un numero configurabile di worker e thread.

**Parallelismo del server** (PC, loopback): passare da 1 a 4 worker triplica il motore d'inferenza (da 5.946 a 18.718 inferenze/s), ma il servizio HTTP migliora solo del **+2,9%**. Il collo di bottiglia non è il calcolo: sono la ricezione, la serializzazione e il logging. Teniamo quindi **1 worker × 1 thread** come default. Tutte le 5,78 milioni di risposte sono verificate ([report](../experiments/server_parallelism/2026-11-01/ac/README.md)).

**Validazione con due ESP32 reali** (9 novembre, hotspot Pixel + ADB):
- prove individuali, A sotto carico di un client PC simulato, A e B insieme per 1.000 frame ciascuna;
- **riavvio di A mentre B continua**: B non si ferma;
- **un'ora continua**: A 14.137 frame, B 14.162;
- **34.296 richieste**, tutte con esito 200 e punteggi identici byte per byte al replay;
- ciclo p50 di circa **245 ms** per scheda, coda server p95 circa 0,1 ms.

Fonte: [campagna multi-client](../experiments/multiclient_hardware/2026-11-09-pixel-adb-full/report.md).

### Fase F — Dove va il tempo del ciclo camera (9–12 novembre)

Prima di ottimizzare abbiamo misurato **ogni fase del ciclo** (B, condizioni di rete buone):

| Passo | p50 |
|---|---:|
| Attesa e acquisizione del frame | 75 ms |
| RGB565 → float in scala di grigi | 8,5 ms |
| float → INT8 (ingresso del modello) | **38,6 ms** |
| Inferenza del prefisso | 95 ms |
| Impacchettamento | 1,1 ms |
| Richiesta e risposta HTTP | 65 ms |
| **Ciclo** | **~284 ms** |

È il criterio usato per scegliere su cosa lavorare: **conta la quota sul ciclo**, non il guadagno isolato.
Fonte: [prova del ciclo](../experiments/esp32_cycle_benchmark/README.md).

### Fase G — Conversione dell'ingresso con tabella (LUT) (9–10 novembre) ★

**Problema.** Ogni pixel passava per un calcolo in `double`, che l'ESP32-S3 esegue **in software**: 9.216 pixel per circa 4 µs.

**Soluzione.** L'uscita INT8 dipende solo dal valore RGB565 del pixel, quindi bastano **65.536 valori possibili** precalcolati in una tabella da 64 KiB in PSRAM. Ora la conversione è una lettura di tabella per pixel.

**Risultati:**
- conversione da **47 a 1,3 ms** (poi 46,3 → 0,8 ms nella prova del ciclo);
- **zero differenze** su tutti i 65.536 colori e sui frame reali;
- ciclo completo con HTTP, 1.000 frame × 3 ripetizioni: **336 → 245 ms (−27,2%)**;
- con due schede insieme: A da 377 a 205 ms, B da 266 a 198 ms;
- freschezza del frame (età p95) migliorata.

**Variante scartata.** Il **rilascio anticipato** del framebuffer aumenta la cadenza ma peggiora l'età dei frame. L'ora di stabilità si è interrotta dopo 34 minuti per un HTTP 408: oggi sappiamo che era un problema di rete e camera (fase I), non della LUT.
Fonti: [prove locali](../experiments/esp32_input_camera_benchmark/2026-11-09/report.md), [confronto lungo](../experiments/esp32_input_camera_benchmark/2026-11-10/lut-hold-full-report.md).

### Fase H — Ottimizzare il prefisso: profilo, PAD e memoria (10–16 novembre)

**Profilo per operatore** (93,8 ms in totale): la prima convoluzione pesa il 25%, l'espansione 1×1 il 19%, il **PAD il 15,6%**. Il PAD è solo una copia del tensore con un bordo aggiunto, ma il kernel generico di TFLM visita ogni elemento ([profilo](../experiments/esp32_layer_profile/2026-11-10/report.md)).

Gli interventi, uno dopo l'altro:

| Passo | Effetto | Fonte |
|---|---|---|
| PAD veloce (copie per righe) | PAD da 14,6 a 5,2 ms; `Invoke()` da **93,9 a 84,5 ms** (−10%) | [report](../experiments/esp32_pad_benchmark/2026-11-11/report.md) |
| Attivazioni in RAM interna invece che in PSRAM | `Invoke()` da 84,7 a **62,3 ms** (−26,5%), ma è un limite superiore senza Wi-Fi e camera | [report](../experiments/esp32_memory_benchmark/2026-11-11/report.md) |
| Prefisso senza nodo PAD (padding SAME) | picco delle attivazioni da 225.840 a 178.688 B, stessi byte in uscita | [report](../experiments/esp32_nopad_benchmark/2026-11-11/report.md) |
| Buffer a strisce ESP-NN ridotto (3 righe) | picco **145.760 B** (−18,4%), costo +0,3% | [report](../experiments/esp32_scratch_benchmark/2026-11-16/report.md) |
| Allocazione anticipata (prima di Wi-Fi e camera) | l'arena entra: minimo libero ~70 KB, sopra la riserva di 32 KB | [report](../experiments/esp32_client_fit_early_benchmark/2026-11-16-early/report.md) |

**Perché la RAM interna è stata chiusa come filone principale.** Fa risparmiare ~22 ms su un ciclo di 280–580 ms, mentre la rete fragile pesava molto di più. È tecnicamente fattibile con l'allocazione anticipata, ma non è la leva più grande.

### Fase I — Rete e camera: il fattore XCLK (5–17 novembre) ★

**Il problema ricorrente.** Con la camera accesa le richieste HTTP si bloccavano: errore **HTTP 408** (timeout nella ricezione del corpo, 3 s), a volte dopo pochi frame. Con la camera spenta tutto andava bene (1.100/1.100 richieste).
- Abbiamo provato cambio di porta USB, cambio di cavo, attivazioni in PSRAM e acquisizione sospesa: **nessuno risolveva**.
- L'ipotesi è arrivata leggendo il driver congelato e la segnalazione esp32-camera #869: `cam_stop()` ferma l'acquisizione ma **lascia acceso il clock XCLK** del sensore.

**L'esperimento decisivo** (3 avvii, 1.500 ping):

| Condizione | Risposte ai ping |
|---|---:|
| Wi-Fi prima della camera | 300/300 |
| Camera inizializzata, acquisizione ferma, **XCLK ON** | **82/600** |
| Stessi buffer, **XCLK OFF** | **600/600** |

Riaccendere il clock riproduce il degrado, spegnerlo lo elimina, in tutte le 12 commutazioni.
- **Cosa resta da capire:** il meccanismo fisico (interferenza o carico elettrico) non è distinto. Servirebbe un oscilloscopio.

**La soluzione, "gated camera":** XCLK acceso solo durante l'acquisizione, spento durante inferenza e invio.
- **Risultato:** prima avevamo blocchi dopo poche decine di richieste, ora **zero timeout su migliaia di richieste**.
- **Prezzo:** a ogni ripresa il firmware attende 200 ms e scarta il primo frame, quindi **l'acquisizione sale a ~601 ms** e il ciclo totale a **~710 ms**.

Fonti: [XCLK](../experiments/esp32_websocket_benchmark/2026-11-17-xclk/report.md), [prima prova con gestione](../experiments/esp32_websocket_benchmark/2026-11-17-gated-camera/report.md), [diagnostica laptop](../experiments/esp32_websocket_benchmark/2026-11-17-laptop/report.md).

> **Attenzione nel confronto:** i ~245 ms della LUT (hotspot Pixel) e i ~710 ms di oggi non sono un peggioramento del software. Sono **due configurazioni diverse**. Oggi il ciclo è stabile ma dominato dal riavvio del sensore, e **ridurre quei ~600 ms è la leva più grande rimasta**.

### Fase J — Trasporti: HTTP persistente, WebSocket o HTTP con chiusura (16–18 novembre)

**Cosa.** Abbiamo implementato un WebSocket v2 con limiti, sullo stesso server, e reso configurabile il keep-alive HTTP. Poi un confronto rigoroso: **9 avvii, ordine ruotato, 18.900/18.900 richieste, 9.000 frame reali, zero timeout**.

| Trasporto | Ciclo camera p50 / p95 | Richiesta camera p50 | RAM interna libera minima |
|---|---:|---:|---:|
| **HTTP persistente** | **709,8 / 792,6 ms** | 40,1 ms | **48.723 B** |
| WebSocket | 711,3 / 798,2 ms | 41,5 ms | 36.535 B |
| HTTP con chiusura | 754,3 / 820,5 ms | 89,9 ms | 50.035 B |

**Scelta: HTTP persistente.**
- Ha un ciclo praticamente uguale a WebSocket (differenza sotto il 2%) e **12 KB di RAM interna in più**.
- Riusare la connessione fa risparmiare circa 45 ms rispetto a riaprirla ogni volta: l'apertura scende da 12–13 a 2 ms.

Fonte: [confronto del 18 novembre](../experiments/esp32_websocket_benchmark/2026-11-18-comparison/report.md).

### Fase K — Frame skip (18 novembre)

**Idea.** Se il frame nuovo è quasi uguale all'ultimo inviato, **non eseguiamo il prefisso e non inviamo nulla**. Il confronto è sulla differenza globale tra gli input INT8 e costa circa 0,63 ms. Un "rinnovo" forza comunque un invio ogni 1,5 s o 5 s.

| Avvio (B, 100 frame ciascuno) | Richieste camera | Ciclo p50 |
|---|---:|---:|
| Baseline | 100/100 | 725,8 ms |
| Attivo, soglia 32, rinnovo 1,5 s | 34/100 | 602,7 ms |
| Attivo, soglia 32, rinnovo 5 s | 12/100 | 602,4 ms |

- **Byte HTTP dei frame:** −66% e −88%. La connessione TCP viene riusata anche dopo gli skip.
- **Ma conta la qualità.** Nel replay sul video, soglia 32 con rinnovo 1,5 s conserva tutti gli eventi a offset 0, ma ne perde uno a offset 355 ms. Il rinnovo a 5 s perde 6–7 eventi su 9–10. Sulla camera, allo stesso numero di invii, l'**invio uniforme ha perso meno eventi** (4 contro 5 su 13).
- **Candidata da verificare:** soglia 8 con rinnovo 1,5 s, che conserva tutti gli eventi in replay e riduce gli invii di circa un terzo.

Fonte: [report frame skip](../experiments/esp32_websocket_benchmark/2026-11-18-frame-skip/report.md).

---

## 4. Riepilogo prima → dopo

| Leva | Prima | Dopo | Configurazione |
|---|---:|---:|---|
| FLOAT32 → INT8 + ESP-NN, tempo completo | 860 ms | 162 ms | 27 ottobre, immagini identiche |
| FLOAT32 → INT8, attivazioni | 18.432 B | 4.608 B | stesso |
| FLOAT32 → INT8, camera continua | ~1,1 fps | ~5 fps | stesso |
| Rice temporale, byte/frame | 4.608 B | 2.534 B | lossless; conviene sotto ~800 kbit/s |
| Conversione ingresso (LUT) | 47 ms | 1,3 ms | locale, B |
| Ciclo completo con LUT | 336 ms | 245 ms | hotspot Pixel, A, 3×1.000 frame |
| `Invoke()` prefisso, PAD veloce | 93,9 ms | 84,5 ms | senza rete/camera |
| `Invoke()` prefisso, RAM interna | 84,7 ms | 62,3 ms | limite superiore |
| Picco attivazioni (no-PAD + strisce) | 225.840 B | 145.760 B | B |
| Ping con camera inizializzata | 82/600 | 600/600 | XCLK ON → OFF |
| Apertura connessione HTTP | 12–13 ms | 2 ms | keep-alive |
| Ciclo camera, HTTP chiusura → persistente | 754 ms | 710 ms | router, XCLK gestito |
| Richieste camera con frame skip | 100 | 34 / 12 | soglia 32, rinnovo 1,5 s / 5 s |
| Multi-client | 1 client, stato condiviso | 2 ESP32 reali per 1 h, 34.296 richieste corrette | HTTP v2 |

---

## 5. Cosa è chiuso, cosa è aperto

**Chiuso / acquisito**
- INT8 + ESP-NN come rappresentazione di riferimento.
- Raw INT8 sulla rete normale; Rice solo per banda ridotta.
- Server HTTP v2 multi-client validato con due schede.
- LUT, utile e numericamente equivalente.
- Causa principale dei blocchi di rete localizzata: XCLK.
- Trasporto scelto: HTTP persistente.

**Aperto**
1. **Ridurre il costo della gestione XCLK** (~600 ms per frame): attesa più corta dopo la riaccensione, scartare meno frame, o separare fisicamente l'alimentazione e verificare l'interferenza.
2. **Portare nel client operativo** LUT, keep-alive, PAD veloce e allocazione anticipata. Finora vivono nei progetti sperimentali.
3. **Frame skip:** verificare sulla camera la soglia 8 con rinnovo 1,5 s, su scene con eventi annotati.
4. **Qualità:** scene nuove e indipendenti, conferma dell'ordine delle classi.
5. Proposte di tesi non ancora iniziate: altri split, pipeline tra inferenza e invio, frequenza adattiva sotto congestione, early exit su FOMO ([temi](../TEMI_DI_TESI_E_RICERCA.md)).

---

## 6. Glossario veloce

| Termine | Significato |
|---|---|
| **Attivazioni** | I valori intermedi prodotti da un layer: sono ciò che la scheda invia al server |
| **Prefisso / suffisso** | La parte della rete eseguita sulla scheda / sul server |
| **INT8** | Numeri interi a 8 bit al posto dei float32 a 32 bit: 4× meno memoria, calcolo più veloce |
| **ESP-NN** | Libreria di Espressif con kernel ottimizzati (istruzioni vettoriali) per ESP32-S3 |
| **PSRAM vs RAM interna** | La PSRAM è grande (8 MB) ma lenta, esterna e collegata via SPI. La RAM interna è veloce ma piccola (~300 KB, condivisa con Wi-Fi e camera) |
| **Arena** | La zona di memoria in cui TFLite Micro tiene i tensori durante l'inferenza |
| **LUT** | Look-up table: valori precalcolati al posto di un calcolo per ogni pixel |
| **PAD** | Operatore che aggiunge un bordo al tensore prima di una convoluzione |
| **XCLK** | Il clock (16 MHz) che l'ESP32 fornisce al sensore della camera |
| **Keep-alive / HTTP persistente** | Riusare la stessa connessione TCP per più richieste |
| **p50 / p95** | Mediana / valore sotto cui sta il 95% delle misure (indica la "coda" lenta) |
| **HTTP 408** | Il server non ha ricevuto il corpo della richiesta entro il timeout (3 s) |
| **Lossless / lossy** | Ricostruzione esatta / approssimata, con effetti misurati |
| **Rice** | Codifica a lunghezza variabile, efficiente per numeri piccoli come le differenze tra frame |

---

## 7. Domande probabili del relatore (con risposta breve)

**"Perché il ciclo di oggi (710 ms) è più lento di quello con la LUT (245 ms)?"**
Sono configurazioni diverse. Con la gestione di XCLK il sensore viene riavviato a ogni frame: 200 ms di attesa più un frame scartato fanno circa 600 ms. In cambio la rete è passata da blocchi dopo poche decine di richieste a 18.900/18.900 senza errori. Il prossimo lavoro è ridurre quei 600 ms.

**"La compressione allora non serve?"**
Su una Wi-Fi normale il guadagno di byte non compensa il tempo di calcolo. Sotto circa 800 kbit/s invece Rice migliora la mediana fino al −27%. Il risultato utile è la **soglia misurata**, non "comprimere sempre".

**"Il multi-client scala?"**
Il servizio è corretto con due schede reali, anche durante il riavvio di una delle due, e regge un'ora. Sul PC il motore scala con i worker, il servizio HTTP quasi no. Per sapere dove si ferma servono più schede o un banco di congestione.

**"INT8 peggiora la qualità?"**
Sulle 84 foto annotate, ignorando la classe, F1 è 96,9% contro 96,5%: praticamente uguale. Servono però scene indipendenti e la conferma delle classi.

**"Cosa è originale nel lavoro?"**
Non abbiamo inventato la compressione temporale o la quantizzazione. Il contributo è **adattarle e misurarle sul sistema concreto ESP32 + FOMO**, con criteri prefissati. In più: il servizio multi-client e la diagnosi del problema XCLK.

**"Come sapete che le ottimizzazioni non cambiano il risultato?"**
Ogni variante lossless è stata confrontata byte per byte: LUT su tutti i 65.536 colori, PAD su 3,7 milioni di byte, migliaia di risposte rigiocate sul server.

---

## 8. Rigenerare le slide

Il deck viene generato dallo script [`build_deck.js`](build_deck.js), che usa pptxgenjs. Le istruzioni sono in testa allo script.
