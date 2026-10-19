# Quantizzazione 16×8 — confronto PC del 18 ottobre 2026

**Esito:** conversione integer-only e inferenza desktop riuscite. Sui medesimi
98 frame della prova INT8, il 16×8 cambia 18 celle a soglia 0,5 contro le 25
dell'INT8; celle oggetto perse 7 contro 11. Il riferimento ne ha 99. Il 16×8 è
più fedele in queste metriche, ma rimangono differenze e nessuna qualità è stata
approvata per l'applicazione o verificata su ESP32.

| Variante | File TFLite | Soli valori al confine | Max errore punteggi | MAE punteggi | Celle cambiate a 0,5 | Perse / introdotte |
|---|---:|---:|---:|---:|---:|---:|
| Float32 | 84.292 byte | 18.432 byte | 0,00000310 | 0,0000000296 | 0 | 0 / 0 |
| INT8 | 57.088 byte | 4.608 byte | 0,289446 | 0,00223682 | 25 | 11 / 14 |
| 16×8 | 69.056 byte | 9.216 byte | 0,285753 | 0,000776675 | 18 | 7 / 11 |

Il file 16×8 è più piccolo del 18,08% rispetto a TFLite float32, ma più grande
dell'INT8. Il 50% di riduzione al confine riguarda i soli valori INT16, non
metadati, traffico totale o picco di RAM. MAE e celle migliorano, mentre l'errore
massimo resta vicino a 0,286: più bit nelle attivazioni non recuperano
automaticamente tutte le predizioni originali.

## Metodo e limiti

- Stesso H5, preprocessing e indici della [prima prova INT8](../int8_2026-10-18/README.md).
  Calibrazione: 0–47 (48 frame). Valutazione: 48–145 (98 frame). Frame disgiunti
  ma temporalmente correlati dello stesso video; nessun dato nuovo o annotazione.
- I controlli float32 e INT8 sono gli stessi binari salvati in precedenza,
  ricaricati e rieseguiti: hash delle uscite e metriche coincidono con l'archivio.
- Solo il modello 16×8 è convertito, con
  `EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8` e ingresso/uscita
  INT16. Verificati attivazioni INT16, pesi INT8 e bias INT64 nelle convoluzioni.
  Nessun fallback float o riaddestramento. Inventario di operatori/versioni nel JSON.
- È una quantizzazione intera 16×8, distinta da float16. Il confine osservato
  nel modello intero ha scala `0.00030756735941395164` e zero point `0`.
- Metriche rispetto a Keras: celle, non oggetti distinti o accuratezza su
  annotazioni; nessun postprocessing FOMO. A soglia 0,5 l'IoU di primo piano
  è circa 0,836 contro 0,779 dell'INT8. Conservate anche soglie 0,25/0,75.
- Nessuna ricerca di parametri sul test. Nessuna causa specifica attribuita
  alle differenze residue senza una prova dedicata.
- Interprete CPU a un thread con delegati disabilitati e tutti i tensori
  conservati per ispezione. Nessuna misura di tempo, RAM o energia.
- Il modello è intero: split in due parti, protocollo SCIoT quantizzato,
  compilazione ed esecuzione Micro/ESP32 restano da verificare. Il supporto
  del nome di un operatore non garantisce il supporto della sua variante INT16.

Riferimento consultato il 18 ottobre:
[quantizzazione 16×8 nella documentazione ufficiale](https://developers.google.com/edge/litert/conversion/tensorflow/quantization/post_training_quantization#integer_only_16-bit_activations_with_8-bit_weights_experimental).

## File conservati

- [report.md](report.md), [summary.json](summary.json), [frames.csv](frames.csv):
  confronto, hash di input/sorgenti/controlli e metriche su 3 × 98 frame.
- [fomo_16x8.tflite](fomo_16x8.tflite): modello intero convertito.
- [fomo_float32.tflite](fomo_float32.tflite), [fomo_int8.tflite](fomo_int8.tflite):
  copie identiche dei controlli dell'archivio INT8.
- [verification.json](verification.json): ricaricamento dei binari e
  ricomputazione delle uscite in un percorso separato, con funzioni metriche condivise.
- [tests.txt](tests.txt): 23 test senza socket passati, inclusi quattro nuovi
  controlli sul range INT16 e sulla compatibilità della mappatura INT8.
- [snapshot-sha256.txt](snapshot-sha256.txt): integrità di questo archivio.

Gli archivi precedenti e i loro sorgenti sono conservati senza modifiche.

## Riproduzione dalla radice del repository

Usare l'ambiente già disponibile (TensorFlow 2.15.0, NumPy 1.26.4) e la cache
`results/input/` con gli hash registrati. La cache è ignorata da Git e deve essere
conservata o rigenerata identificando eventuali differenze numeriche.
Gli indici di calibrazione/valutazione sono letti dal controllo INT8.

```bash
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 \
TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 \
.venv/bin/python experiments/activation_compression/check_16x8.py \
  --input-dir experiments/activation_compression/results/input \
  --int8-archive experiments/activation_compression/int8_2026-10-18 \
  --output-dir experiments/activation_compression/results/16x8-new-run

CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 \
TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 \
.venv/bin/python experiments/activation_compression/verify_16x8.py \
  --input-dir experiments/activation_compression/results/input \
  --int8-archive experiments/activation_compression/int8_2026-10-18 \
  --result-dir experiments/activation_compression/16x8_2026-10-18 \
  --output /tmp/sciot-16x8-verification.json

cd experiments/activation_compression
../../.venv/bin/python -m unittest test_compare test_lossy test_int8 test_16x8 -v
```

Usare una directory di destinazione vuota. La verifica controlla hash esatti:
richiede i sorgenti/input e l'ambiente registrati. Per verificare una nuova
esecuzione, indicare il suo percorso in `--result-dir`.

## Prossimo passo

Verificare nel runtime Micro effettivo il supporto delle varianti INT8 e INT16
prima di scegliere il porting; poi misurare memoria e tempo sulla scheda e
verificare lo split. Ampliare calibrazione e valutazione su sequenze distinte
per controllare la robustezza, senza cercare parametri sullo stesso test.
Il beneficio della compressione temporale va misurato sulla rappresentazione
scelta: i precedenti risparmi su float32 non si trasferiscono automaticamente.
