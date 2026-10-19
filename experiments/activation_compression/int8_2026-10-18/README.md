# Verifica INT8 del modello — 18 ottobre 2026

**Esito:** conversione integer-only ed esecuzione TFLite sul PC riuscite.
Il file passa da 84.292 a 57.088 byte (-32,27%); i soli valori a `block_2_add`
da 18.432 a 4.608 byte (-75%). La fedeltà non è ancora approvata: sui 98 frame
di valutazione cambiano 25 celle a soglia 0,5, con 11 celle oggetto perse sulle
99 del riferimento e 14 introdotte. Non sono oggetti distinti o errori su annotazioni.

La versione TFLite float32 di controllo non cambia celle e differisce al massimo
di circa 0,00000310 nei punteggi; INT8 arriva a 0,289446. Non usare il solo accordo
globale del 99,82%, dominato dallo sfondo, per dichiarare la qualità accettabile.

## Metodo e limiti

- FOMO candidato già disponibile, stesso H5 e preprocessing degli esperimenti.
  Nessun addestramento o modifica dell'architettura.
- Primi 48 frame, indici 0–47, per calibrare; successivi 98, indici 48–145, per
  valutare. Disgiunti ma temporalmente correlati nello stesso video di 29,26 s.
  Non sono dati indipendenti o rappresentativi di tutti gli scenari.
- Conversione con `TFLITE_BUILTINS_INT8`, ingresso/uscita int8; nessun tensore
  float o operatore di dequantizzazione nel modello INT8. Gli int32 servono
  anche per bias e forme. Operatori/versioni nel JSON e nel report.
- Interprete desktop CPU a un thread, delegati predefiniti disabilitati e tutti
  i tensori conservati per ispezione. Nessun benchmark di tempo o picco di memoria.
- Il confine è osservato dentro il modello intero. Due sottomodelli INT8
  separati e il trasporto con scala/zero point coerenti restano da verificare.
  Il protocollo SCIoT esistente continua a usare float32.
- Allocazione/Invoke desktop non certificano compatibilità Micro o ESP32;
  nessuna build/flash, integrazione ESP-NN, misura di energia o prova di rete.
- Senza annotazioni misuriamo fedeltà alle predizioni originali, non accuratezza.
  Le metriche sono proxy di celle, senza postprocessing FOMO.

La conversione segue la [documentazione ufficiale sulla quantizzazione post-training](https://developers.google.com/edge/litert/conversion/tensorflow/quantization/post_training_quantization).
La [integrazione ESP-NN di Espressif](https://github.com/espressif/esp-tflite-micro#esp-nn-integration)
è un possibile percorso successivo; non è la libreria Arduino attualmente dichiarata
nel progetto e non ne abbiamo verificato l'integrazione. Fonti consultate il 18 ottobre.

## Artefatti conservati

- [report.md](report.md): risultati e interpretazione.
- [summary.json](summary.json): input/source hash, ambiente, indici,
  tipi, scale/zero point, operatori/versioni e metriche a soglie 0,25/0,5/0,75.
- [frames.csv](frames.csv): due versioni × 98 frame di valutazione.
- [fomo_float32.tflite](fomo_float32.tflite) e
  [fomo_int8.tflite](fomo_int8.tflite): modelli interi convertiti.
- [verification.json](verification.json): ricaricamento dei binari salvati in
  un percorso di valutazione separato, hash delle uscite, metriche e conteggi CSV.
  Le funzioni delle metriche sono condivise; non è una seconda valutazione su annotazioni.
- [tests.txt](tests.txt): 19 test passati (15 precedenti e 4 nuovi INT8), senza socket.
- [snapshot-sha256.txt](snapshot-sha256.txt): integrità degli artefatti.

Le baseline del 15/17 ottobre e la prova TCP sono esperimenti distinti, conservati.

## Riproduzione dalla radice del repository

Usare l'ambiente TensorFlow 2.15.0 / NumPy 1.26.4 già disponibile. I dati originali
restano sotto `results/input/`, ignorati da Git: conservare video, ZIP e cache per
ottenere esattamente gli hash indicati. Per rigenerarli, seguire il
[README degli esperimenti](../README.md). Differenze numeriche durante la
rigenerazione possono cambiare gli hash; identificare sempre i nuovi input.

```bash
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 \
TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 \
.venv/bin/python experiments/activation_compression/check_int8.py \
  --input-dir experiments/activation_compression/results/input \
  --output-dir experiments/activation_compression/results/int8-new-run \
  --calibration-frames 48

CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 \
TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 \
.venv/bin/python experiments/activation_compression/verify_int8.py \
  --input-dir experiments/activation_compression/results/input \
  --result-dir experiments/activation_compression/int8_2026-10-18 \
  --output /tmp/sciot-int8-verification.json

cd experiments/activation_compression
../../.venv/bin/python -m unittest test_compare test_lossy test_int8 -v
```

Il convertitore richiede una directory di destinazione vuota. Per verificare una
nuova esecuzione, usare il suo percorso in `--result-dir`. La verifica confronta
hash esatti: richiede input/sorgenti originali e l'ambiente numerico registrato.
Non sovrascrivere gli artefatti storici con quelli di un nuovo ambiente.

## Prossimo passo

Conservare float32 come controllo e verificare la calibrazione su input più
rappresentativi, mantenendo la valutazione separata e senza cercare parametri
sul test. Non è stata identificata la causa degli scostamenti e non si attribuiscono
automaticamente ai soli 48 frame di calibrazione.

Poi verificare runtime, split e costi sulla scheda. Il confronto dei codec dovrà
usare la rappresentazione scelta; il beneficio temporale su float32 non predice
quello su INT8. DPCM/dead-zone resta da specificare e implementare.
