# INT8 con ESP-NN: non compresso contro zlib senza perdita

Prova fisica del 28 ottobre 2026: due sessioni dello stesso firmware, **816 richieste validate**, un solo interprete INT8 e un punto di divisione fisso `block_2_add` (4.608 byte). Miniz 3.0.2, livello 1, un flusso zlib indipendente per tensore. CPU 240 MHz, arena e workspace in PSRAM.

## Byte e tempo completo

Valori mediani. I byte HTTP includono richiesta e risposta con intestazioni ricostruite dal server. La risposta è sempre di 1.760 byte; TCP/IP, ritrasmissioni e occupazione radio non sono misurati.

| Sessione | Ingresso | Payload raw / zlib, B | Risparmio payload | HTTP raw / zlib, B | Ciclo raw / zlib, ms |
|---|---|---:|---:|---:|---:|
| 1 | Immagini identiche | 4608 / 3949 | 14.3% | 6822 / 6163 | 157.39 / 162.71 |
| 1 | 84 foto annotate | 4608 / 3925 | 14.8% | 6822 / 6139 | 156.27 / 162.90 |
| 1 | Camera alternata | 4608 / 3760 | 18.4% | 6822 / 5974 | 381.08 / 402.52 |
| 2 | Immagini identiche | 4608 / 3949 | 14.3% | 6822 / 6163 | 163.10 / 166.70 |
| 2 | 84 foto annotate | 4608 / 3925 | 14.8% | 6822 / 6139 | 156.12 / 163.66 |
| 2 | Camera alternata | 4608 / 3800 | 17.5% | 6822 / 6014 | 223.18 / 209.05 |

Il ciclo include preparazione ingresso, inferenza locale, checksum, compressione/reset (quando abilitata), impacchettamento, connessione TCP, HTTP, decompressione e controllo sul PC, suffisso, postprocessing FOMO e ricezione della risposta. Per la camera include acquisizione da `esp_camera_fb_get` e preprocessing; non misura età del frame o inizio esposizione. I tempi server sono già compresi in HTTP.

## Costo del codec e variabilità

| Sessione | Ingresso | Compressione p50, ms | Decompressione + controlli p50, ms | Ciclo raw p95, ms | Ciclo zlib p95, ms |
|---|---|---:|---:|---:|---:|
| 1 | Immagini identiche | 6.783 | 0.048 | 167.51 | 172.38 |
| 1 | Camera alternata | 6.694 | 0.052 | 1897.89 | 1546.66 |
| 2 | Immagini identiche | 6.785 | 0.047 | 237.94 | 233.02 |
| 2 | Camera alternata | 6.724 | 0.046 | 446.03 | 359.95 |

## Sequenze continue dalla camera

| Sessione | Raw, immagini/s nelle due sequenze | Zlib, immagini/s nelle due sequenze |
|---|---:|---:|
| 1 | 1.34 / 2.31 | 1.23 / 3.56 |
| 2 | 3.97 / 4.06 | 2.56 / 4.42 |

Quattro sequenze da 20 frame per sessione, ordine raw/zlib/zlib/raw. Le stampe seriali sono emesse dopo la misura della sequenza. I frame camera differiscono fra modalità; il confronto a ingresso identico usa i tre frame canonici e tutte le 84 foto.

## Integrità e memoria

Per ciascuna sessione, **87 ingressi distinti** hanno attivazioni ricostruite e punteggi finali identici byte per byte tra raw e zlib (288 richieste includendo le ripetizioni). Le predizioni su tutti gli ingressi fissi coincidono anche fra le due sessioni. Ogni messaggio, inclusi quelli camera, supera controllo delle dimensioni e CRC32 del tensore originale.

Sulle 84 foto annotate entrambe le modalità trovano 110 oggetti, ne mancano 2 e producono 5 falsi positivi. Il matching ignora la classe, come nel confronto precedente; non sono nuove misure su scene indipendenti. La compressione non aggiunge perdita a quella già presente nel modello INT8.

Workspace allocato del codec: **319,296 byte**, buffer compresso 8.192 byte e buffer messaggio 8.224 byte. Queste allocazioni sono persistenti e presenti in entrambe le modalità dello stesso firmware; inizializzazione fuori misura, reset per tensore incluso. Non è una misura del picco RAM di due applicazioni separate.

La modalità zlib invia sempre il risultato del codec, senza fallback adattivo. Frame espansi osservati: 0.

## Interpretazione

Sulle immagini identiche, nelle due sessioni zlib aumenta la mediana del tempo completo. In questa configurazione la riduzione del traffico non compensa il costo della compressione. Le prove camera restano indicate separatamente.

Per parlare di riduzione del traffico al secondo confrontare le modalità alla stessa frequenza di invio. Il risultato riguarda una scheda, questa rete, questo codec e questo taglio; compressione temporale e client concorrenti sono esperimenti successivi.

Dettagli: [summary.json](summary.json). Metodo: [README](../README.md). I log seriali e i pacchetti originali sono conservati localmente sotto `results/`, ignorato da Git.

## Chiusura della prova

Il 29 ottobre il firmware preesistente è stato ripristinato: verifica del digest di tutti gli 8 MB prima dell’avvio e conferma seriale di `sciot_esp32_client 0.1.0`, modello `fomo_224`. I quattro test nativi e del protocollo passano. Evidenze e hash: [verification.json](verification.json).
