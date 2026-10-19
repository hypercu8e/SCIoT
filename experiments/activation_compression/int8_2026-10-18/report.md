# Fattibilità INT8 del FOMO — prova PC

Conversione post-training senza riaddestramento. Modello intero, non due sottomodelli distribuiti; nessuna esecuzione ESP32 o misura di latenza/RAM.

Calibrazione: primi 48 frame. Valutazione: successivi 98 frame, disgiunti ma dallo stesso video e temporalmente correlati. Non è un dataset indipendente né una misura di accuratezza su annotazioni.

| Artefatto | Byte file TFLite | Tipo ingresso/uscita | Byte valori al confine |
|---|---:|---|---:|
| float32 | 84292 | float32/float32 | 18432 |
| int8 | 57088 | int8/int8 | 4608 |

Riduzione file INT8 rispetto a TFLite float32: 32.27%. Il confronto include anche metadati e operatori del file; non usa la dimensione H5.

## Fedeltà al modello Keras float32 sui frame di valutazione

| Versione | Max errore punteggi | MAE punteggi | Celle cambiate a 0,5 | Perse | Introdotte | Classe cambiata |
|---|---:|---:|---:|---:|---:|---:|
| float32 | 3.09944e-06 | 2.96373e-08 | 0 / 14112 | 0 | 0 | 0 |
| int8 | 0.289446 | 0.00223682 | 25 / 14112 | 11 | 14 | 0 |

Il riferimento ha 99 celle oggetto a soglia 0,5. Sono celle di griglia, non oggetti distinti o risultati del postprocessing FOMO. Accordo globale dominato dallo sfondo: leggere anche celle perse/introdotte e IoU di primo piano nel JSON. Sono conservate anche le soglie 0,25 e 0,75.

Confronto INT8 con TFLite float32, per isolare meglio la quantizzazione: max errore punteggi 0.289444.

## Rappresentazione e compatibilità

Confine osservato nel modello intero: `model_1/block_2_add/add`, forma `[1, 24, 24, 8]`, scale `[0.06843240559101105]`, zero point `[-20]`.

Valori d'ingresso effettivamente tagliati ai limiti INT8: 162 / 903168.

Operatori INT8: `ADD` v2 (3), `CONV_2D` v3 (15), `DEPTHWISE_CONV_2D` v3 (6), `PAD` v2 (2), `SOFTMAX` v2 (1).

Tipi dei tensori del modello INT8: `{'int8': 50, 'int32': 22}`. Gli int32 servono anche per bias e forme; non sono fallback float. Conversione integer-only e allocazione/inferenza desktop riuscite.

Questo inventario non certifica il supporto di operatori/versioni nel runtime Micro del firmware. Servono compilazione, allocazione e Invoke sulla scheda; ESP-NN non è stato integrato o misurato.

I 4.608 byte al confine sono i soli valori di un tensore INT8 osservato nel modello intero, non un payload SCIoT già implementato. Lo split INT8 deve ancora essere esportato e verificato con scale/zero point coerenti tra prefisso, messaggio e suffisso. Il protocollo corrente assume float32.

L'interprete conserva tutti i tensori per ispezionarli: nessun numero di RAM o tempo PC è usato per prevedere prestazioni ESP32. La qualità accettabile per l'applicazione non è stata stabilita.

## Prossima decisione

La conversione è fattibile sul PC, ma questa variante non è promossa a baseline di qualità: valutare le celle perse/introdotte e ampliare la calibrazione con input rappresentativi separati dalla valutazione, senza cercare parametri sul campione di test. Non è stata identificata la causa delle variazioni. La successiva prova minima ESP32 dovrà misurare compatibilità, memoria e tempo reali; poi confrontare compressione indipendente e temporale sulla rappresentazione scelta. I precedenti risparmi su float32 non si trasferiscono automaticamente a INT8.
