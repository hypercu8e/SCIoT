# FOMO INT8 con ESP-NN: confronto fisico del 27 ottobre 2026

Due sessioni dello stesso firmware su una ESP32-S3-EYE e un PC sulla rete locale: **816 richieste complete validate**. Stesso taglio `block_2_add`, arene in PSRAM, CPU 240 MHz. Il modello è il candidato Beer/can 96×96 in grigio già usato nelle prove PC; INT8 quantizza pesi e attivazioni. Non sono prove del server originale SCIoT o di due client.

## Traffico per immagine

| Misura | FLOAT32 | INT8 | Riduzione |
|---|---:|---:|---:|
| Sole attivazioni | 18,432 B | 4,608 B | 75.00% |
| Corpo richiesta | 18,464 B | 4,640 B | 74.87% |
| HTTP completo nelle due direzioni, intestazioni incluse | 20,647 B | 6,822 B | 66.96% |

Le richieste misurate non contengono immagini diagnostiche. La risposta è uguale: 1.760 byte, con tutti i punteggi finali. Gli header HTTP sono ricostruiti dal server; TCP/IP, ritrasmissioni e tempo radio non sono misurati. Il risparmio di traffico/s vale a parità di frequenza di elaborazione.

## Tempo completo fino alla risposta

Mediana e percentile 95 in millisecondi. Il timer camera parte prima della richiesta del frame (`esp_camera_fb_get`), senza misurare età del frame o inizio esposizione. Il timer sulle immagini incorporate parte dalla preparazione dell’ingresso.

| Sessione | Ingresso | FLOAT32 p50 / p95 | INT8 p50 / p95 | Rapporto p50 FLOAT32/INT8 |
|---|---|---:|---:|---:|
| 1 | Immagini identiche | 859.9 / 907.1 | 161.8 / 178.0 | 5.32× |
| 1 | Telecamera, frame alternati | 1062.7 / 1332.7 | 275.6 / 399.9 | 3.86× |
| 2 | Immagini identiche | 862.1 / 884.2 | 159.2 / 174.8 | 5.42× |
| 2 | Telecamera, frame alternati | 908.0 / 972.2 | 181.3 / 200.3 | 5.01× |

Ogni sessione comprende 60 campioni per rappresentazione sulle immagini identiche e 20 campioni per rappresentazione nella camera alternata. I frame della camera differiscono fra esecuzioni. I tempi del server sono già compresi in HTTP e non si sommano di nuovo.

## Calcolo e sequenze continue

| Sessione | Prefisso FLOAT32, p50 ms | Prefisso INT8, p50 ms | FPS continui FLOAT32 | FPS continui INT8 |
|---|---:|---:|---:|---:|
| 1 | 813.7 | 94.6 | 1.05 / 1.12 | 4.89 / 5.01 |
| 2 | 813.4 | 94.6 | 1.12 / 1.14 | 5.49 / 5.54 |

Gli FPS sono misurati su sequenze continue da 20 frame, due sequenze per rappresentazione e sessione, ordine AB/BA. Le stampe seriali avvengono dopo la sequenza. Non sono l’inverso della latenza mediana. L’ingresso INT8 richiede ancora circa 39 ms per la quantizzazione in double del firmware; questo costo è incluso nel tempo completo.

Il controllo sul dispositivo conta **6 convoluzioni e 3 depthwise ottimizzate ESP32-S3** per prefisso INT8 e zero per FLOAT32. Le due sessioni usano lo stesso runtime ufficiale e lo stesso binario. Il confronto con la vecchia baseline Arduino non isola il solo beneficio di ESP-NN, perché cambia anche la versione del runtime.

## Qualità su 84 foto annotate

Soglia fissata a 0,5; 112 oggetti annotati dopo il ritaglio. Matching uno a uno con centro del rilevamento dentro il box annotato. **La classe è ignorata**: l’ordine beer/can dei canali del nostro H5 non è confermato.

| Versione | Oggetti trovati | Oggetti mancati | Falsi positivi | Precisione | Richiamo | F1 |
|---|---:|---:|---:|---:|---:|---:|
| float32 | 111 | 1 | 7 | 94.07% | 99.11% | 96.52% |
| int8 | 110 | 2 | 5 | 95.65% | 98.21% | 96.92% |

Le predizioni sulle immagini identiche sono esattamente ripetibili fra le due sessioni. Nel campione INT8 perde un oggetto riconosciuto da FLOAT32 e produce due falsi positivi in meno. Questa differenza non dimostra una qualità generalmente superiore o inferiore. La relazione tra queste foto pubbliche e i dati di addestramento dell’H5 esportato non è dimostrata; servono scene nuove e nomi dei canali verificati prima di concludere sull’utilizzabilità nell’applicazione.

Il decoder Python è verificato contro le funzioni C++ del SDK ufficiale su 250 mappe sintetiche. I punteggi INT8 hardware non sono identici a quelli dell’interprete desktop: errore massimo osservato 0,16796875. I conteggi qui sopra provengono dalla scheda.

## Conclusione e limiti

**In questa configurazione INT8 con ESP-NN riduce sia il traffico per immagine sia il tempo completo client-server.** Osserviamo un oggetto mancato in più sui 112 del campione, insieme a due falsi positivi in meno. È un candidato utile da validare su scene nuove.

Restano aperti qualità per classe, dati indipendenti, altri tagli, integrazione nel protocollo SCIoT originale e comportamento con due client. Le arene effettive sono 907.272 byte FLOAT32 e 229.820 byte INT8, ma sono entrambe residenti e riservate a 1 MiB: non è una misura del picco RAM di un’applicazione con un solo modello.

Dati riassunti: [summary.json](summary.json). Conteggi per foto: [quality-per-image.csv](quality-per-image.csv). Metodo e riproduzione: [README](../README.md). I log e i pacchetti originali restano nelle directory locali ignorate `results/`.
