# Prima prova con perdita controllata

Eseguita il 2026-10-17T14:35:00.013814+00:00 su CPU PC; nessuna emulazione ESP32.

## Metodo

`q = rint(attivazione / passo)`, interi int32 senza clipping; ricostruzione `float32(q * passo)`. Arrotondamento al più vicino, parità ai pareggi.
Indipendente: intero tensore q. Temporale: differenza intera q corrente - q precedente.
Entrambi usano byte shuffle e zlib livello 1 e ricostruiscono gli stessi float32 a ogni passo.
Completo iniziale e ogni 5 secondi; tra i rinnovi scelta del payload minore tra completo e differenza. Fallback raw se comprimere il completo espande i dati.
Sono conteggiati sessione AQST, 24 byte AQF1 per frame, wrapper zlib e rinnovi. CRC sugli interi ricostruiti. Il formato non è integrato in SCIoT.

Il riferimento per le metriche di uscita è il suffisso sulle attivazioni originali, eseguito con gli stessi batch delle ricostruzioni. Il suo confronto con le uscite del modello intero salvate nell'estrazione è verificato con rtol=1e-5, atol=1e-6; le piccole differenze numeriche di esecuzione sono registrate nel JSON.

## Controlli senza perdita sulla stessa macchina

Tempi nuovi, separati dalla baseline storica del 15 ottobre. Tempi lossless senza conversione iniziale float32/byte; tempi lossy includono quantizzazione e ricostruzione float32, quindi ambiti diversi.

| fps | Metodo | Byte totali | Encode ms/frame PC | Decode ms/frame PC |
|---:|---|---:|---:|---:|
| 5 | raw | 2694815 | 0.005 | 0.005 |
| 5 | full_shuffle_zlib | 2430437 | 0.202 | 0.072 |
| 5 | xor_shuffle_zlib | 2291689 | 0.381 | 0.073 |
| 1 | raw | 553918 | 0.004 | 0.005 |
| 1 | full_shuffle_zlib | 499608 | 0.202 | 0.072 |
| 1 | xor_shuffle_zlib | 485719 | 0.357 | 0.074 |

## Risultati a 5 fps

Una riga per passo: le due codifiche hanno ricostruzioni identiche. Errore uscita e celle cambiate si riferiscono al modello originale, non a etichette corrette.

| Passo | Byte indip. | Byte temp. | Risparmio temp./indip. | Risparmio temp./raw | Max errore attiv. | Max errore uscita | Celle cambiate a 0,5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.0001 | 1746434 | 1658496 | 5.04% | 38.46% | 5.00679e-05 | 5.69224e-05 | 0 |
| 0.001 | 1600578 | 1383407 | 13.57% | 48.66% | 0.000500023 | 0.000602782 | 0 |
| 0.01 | 1280164 | 1146018 | 10.48% | 57.47% | 0.005 | 0.00691694 | 1 |
| 0.1 | 1056624 | 854930 | 19.09% | 68.28% | 0.05 | 0.064764 | 2 |
| 0.5 | 867424 | 565725 | 34.78% | 79.01% | 0.249999 | 0.273986 | 49 |
| 1 | 745867 | 435343 | 41.63% | 83.85% | 0.499998 | 0.527455 | 93 |

Celle oggetto nel riferimento a soglia 0,5: **151** su 21024 celle. Sono celle di griglia, non oggetti distinti.

## Risultati a 1 fps

Una riga per passo: le due codifiche hanno ricostruzioni identiche. Errore uscita e celle cambiate si riferiscono al modello originale, non a etichette corrette.

| Passo | Byte indip. | Byte temp. | Risparmio temp./indip. | Risparmio temp./raw | Max errore attiv. | Max errore uscita | Celle cambiate a 0,5 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.0001 | 359304 | 350628 | 2.41% | 36.70% | 5.00679e-05 | 4.55379e-05 | 0 |
| 0.001 | 329276 | 303696 | 7.77% | 45.17% | 0.000499994 | 0.000453651 | 0 |
| 0.01 | 263514 | 249403 | 5.35% | 54.97% | 0.00499995 | 0.00425541 | 0 |
| 0.1 | 217508 | 197102 | 9.38% | 64.42% | 0.0499995 | 0.064764 | 0 |
| 0.5 | 178759 | 145224 | 18.76% | 73.78% | 0.249993 | 0.207534 | 6 |
| 1 | 153485 | 118373 | 22.88% | 78.63% | 0.499995 | 0.527455 | 18 |

Celle oggetto nel riferimento a soglia 0,5: **27** su 4320 celle. Sono celle di griglia, non oggetti distinti.

## Interpretazione e limiti

- Errore sulle attivazioni limitato dal passo/2, più arrotondamento numerico float32; il limite è controllato su tutti i valori. Nessuna saturazione o errore accumulato nel riferimento.
- Nessuna soglia di errore sull'uscita è stata concordata come accettabile. Le tabelle descrivono un compromesso, non selezionano una configurazione sicura.
- Le metriche di griglia scelgono la classe oggetto col punteggio maggiore tra i canali 1 e 2, se raggiunge la soglia; altrimenti sfondo. Argmax sui tre canali è riportato separatamente nel JSON. Sono proxy: non applicano il postprocessing FOMO a componenti connesse né conteggiano oggetti distinti.
- Soglia 0,5 primaria; 0,25 e 0,1 sono analisi di sensibilità, senza modificare il modello. JSON con MAE, RMSE, max errore, celle perse/introdotte e cambi di classe. IoU null se non ci sono celle oggetto nell'unione.
- Accordo con il modello originale non equivale ad accuratezza: mancano annotazioni. Molte celle di sfondo possono rendere l'accordo poco informativo.
- Un video, un modello e uno split; passi scelti per esplorare, senza insieme separato di calibrazione/validazione. Nessun riaddestramento.
- Quantizzazione del messaggio intermedio; la rete resta float32. Non è una conversione del modello in INT8.
- Tempi: mediana delle medie per frame su tre ripetizioni di default; includono selezione adattiva e CRC, escludono inferenza, verifiche contro l'originale, file e rete. Non stimano i tempi ESP32.
- Riferimento temporale int32: 18.432 byte per lato per questo split. Il dato esclude workspace zlib, tensori temporanei, modello e runtime; non è una misura del picco RAM. Nessuna misura di energia o rete reale.

## Artefatti

- `summary.json`: protocollo, parametri, hash, ambiente, misure e metriche complete.
- `frames.csv`: dimensioni, modalità scelta e diagnostica di ciascun frame; tempi della sola ultima ripetizione, mentre i riepiloghi usano la mediana delle medie.
- I tensori originali si rigenerano con `extract_activations.py`; le ricostruzioni quantizzate sono deterministiche e identificate da SHA-256.
