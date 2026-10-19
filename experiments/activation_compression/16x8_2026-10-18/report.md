# Confronto float32, INT8 e 16×8 — CPU PC

Stesso H5, preprocessing e partizione della prima prova INT8: 48 frame di calibrazione e 98 di valutazione, disgiunti ma dallo stesso video. Nessun riaddestramento o ricerca dei parametri sui dati di valutazione.

| Variante | Byte TFLite | Byte valori al confine | Max errore punteggi | Celle cambiate a 0,5 | Perse | Introdotte |
|---|---:|---:|---:|---:|---:|---:|
| float32 | 84292 | 18432 | 3.09944e-06 | 0 / 14112 | 0 | 0 |
| int8 | 57088 | 4608 | 0.289446 | 25 / 14112 | 11 | 14 |
| 16x8 | 69056 | 9216 | 0.285753 | 18 / 14112 | 7 | 11 |

Il riferimento Keras ha 99 celle oggetto a soglia 0,5. Le celle non sono oggetti distinti: queste metriche misurano fedeltà al modello originale senza annotazioni o postprocessing FOMO. Leggere anche soglie 0,25/0,75 e IoU delle celle di primo piano nel JSON.

## Verifiche

Float32 e INT8 sono gli stessi binari dell'archivio precedente, ricaricati e rieseguiti; hash delle uscite e metriche coincidono. 16×8 è convertito con il solo set sperimentale integer-only, ingresso/uscita INT16. Le convoluzioni usano attivazioni INT16, pesi INT8 e bias INT64, senza fallback float.

Tipi dei tensori 16×8: `{'int16': 29, 'int64': 21, 'int8': 21, 'int32': 1}`. Valori d'ingresso tagliati: 192 / 903168.

Confine 16×8: {"index": 54, "name": "model_1/block_2_add/add", "shape": [1, 24, 24, 8], "dtype": "int16", "logical_value_bytes": 9216, "scales": [0.00030756735941395164], "zero_points": [0], "quantized_dimension": 0}.

Operatori/versioni 16×8: `ADD` v2, `CONV_2D` v3, `DEPTHWISE_CONV_2D` v3, `PAD` v2, `SOFTMAX` v2.

## Limiti e seguito

È un modello intero eseguito sul PC. Il confine viene ispezionato internamente: due sottomodelli quantizzati e il protocollo SCIoT con scale/zero point coerenti non sono ancora verificati. I byte al confine sono i soli valori, esclusi metadati e trasporto; non sono picco di RAM.

Nessuna misura di velocità, memoria o energia, né esecuzione ESP32. L'interprete conserva tutti i tensori e disabilita i delegati per ispezione. La conversione riuscita non dimostra il supporto degli operatori INT16 nel runtime Micro del firmware o l'accelerazione ESP-NN.

Confrontare la fedeltà delle due varianti prima di scegliere la rappresentazione. Verificare il runtime Micro e poi memoria/tempo sulla scheda, conservando il controllo float32. Ampliare calibrazione e valutazione su sequenze distinte per generalizzare; non ottimizzare parametri sullo stesso campione di test. Nessuna soglia di qualità accettabile per l'applicazione è stata stabilita.
