# Split INT8 e preparazione hardware — 19 ottobre 2026

**Verificato sul PC: le due parti INT8 producono gli stessi byte del modello
INT8 intero su tutti i 146 frame. Compilati tre firmware ESP32-S3; nessuna prova
fisica ancora eseguita.** [Istruzioni per la scheda](../../esp32_int8_firmware/README.md).

## Metodo e risultato

Abbiamo diviso il binario INT8 già conservato il 18 ottobre, senza convertirlo
di nuovo, ricalibrarlo o riaddestrarlo. Il taglio è l'uscita di `block_2_add`.
Lo script conserva operatori, opzioni, pesi e parametri numerici, rimappando
tensori e buffer delle due parti. Rifiuta tagli con più tensori di confine,
variabili, operatori custom, controllo di flusso o più sottografi. Non è un
partizionatore generico per qualsiasi rete TFLite.

| Artefatto | Byte file | Ingresso | Uscita |
|---|---:|---|---|
| `full.tflite` | 57.088 | INT8 `1×96×96×1` | INT8 `1×12×12×3` |
| `prefix.tflite` | 16.400 | INT8 `1×96×96×1` | INT8 `1×24×24×8` |
| `suffix.tflite` | 41.168 | INT8 `1×24×24×8` | INT8 `1×12×12×3` |

Il confine contiene 4.608 byte di valori. Scala `0.06843240559101105`, zero
point `-20`, identici in modello intero, uscita della prima parte e ingresso
della seconda. Il test serializza e rilegge realmente i byte intermedi in
memoria prima di passarli alla seconda parte; non è uno scambio di rete.

I frame sono stati rigenerati dal video originale: l'hash del NPY coincide
con quello della prova INT8 precedente. Verificati tutti i 146 frame, inclusi
quelli usati storicamente per calibrare, ma senza eseguire nuova calibrazione.
Questa è una verifica di equivalenza, non una nuova stima dell'accuratezza.

Per il firmware conserviamo tre frame fissati in anticipo: 48, 96 e 145, tutti
nella partizione precedente di valutazione. `vectors.npz` contiene gli ingressi
INT8 già preparati, le attivazioni al confine e le uscite attese. Un percorso
separato ricarica i tre binari e ricontrolla questi vettori, forme, scale e hash.
I tipi dei tensori restano INT8/INT32, senza fallback float.

## Compilazione e runtime

Compilazione e collegamento riusciti per `prefix`, `full` e `suffix` usando
PlatformIO 6.1.18, espressif32 6.10.0, Arduino ESP32 2.0.17 e
TensorFlowLite_ESP32 1.0.0. Registrati soltanto i cinque operatori richiesti;
resolver e interprete hanno durata valida per l'intero programma.

Il firmware usa un'arena da 512 KiB in PSRAM, input fissi, controllo degli
ingressi/uscite e log JSON. Non usa camera, display, Wi-Fi o ESP-NN. La compilazione
non esegue `AllocateTensors` o `Invoke`: questi controlli sono ancora da fare
sulla scheda. Il firmware non è integrato nel server originale SCIoT.

La libreria scaricata contiene il percorso INT8 delle operazioni richieste;
la depthwise convolution non ha però il ramo di esecuzione con ingresso INT16.
Il modello 16×8 conservato ha sei nodi con quel tipo d'ingresso: quel modello
non può essere eseguito con questa implementazione invariata. Nessuna conclusione
generale sull'impossibilità di INT16 sull'hardware S3.

I cinque test socket precedenti sono stati rieseguiti: **31 test degli esperimenti
passati**, inclusi tre nuovi test sul taglio; **4 test del verificatore dei log
passati**. I log usati da questi ultimi sono sintetici e non misure hardware.

## Riproduzione

Comandi dalla radice, nell'ambiente Python principale già configurato:

```bash
# Nuova cartella vuota; non sovrascrivere questo archivio:
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 .venv/bin/python \
  experiments/activation_compression/prepare_esp32_int8.py \
  --output-dir experiments/activation_compression/results/esp32-prep-reproduction

.venv/bin/python experiments/activation_compression/verify_esp32_int8.py \
  --output experiments/activation_compression/results/esp32-prep-verification.json

.venv/bin/python -m unittest discover -s experiments/activation_compression -p 'test_*.py'
.venv/bin/python -m unittest discover -s experiments/esp32_int8_firmware -p 'test_*.py'
```

Il primo comando richiede `ffmpeg`/`ffprobe`, il video e il binario INT8 con gli
hash attesi. La verifica separata usa gli artefatti di questo archivio per default;
aggiungere `--artifacts` per una nuova riproduzione.

## Evidenze conservate

- `manifest.json`: input, sorgenti, hash, operatori e parametri delle tre reti;
  equivalenza esatta su 146 frame nel percorso di preparazione.
- `verification.json`: ricaricamento indipendente dei binari sui tre vettori.
- `build-verification.json`: versioni, hash dei sorgenti firmware e dei `.bin`,
  dimensioni della compilazione. I `.bin` restano nella directory `.pio` ignorata.
  I byte di RAM statica non includono l'arena dinamica e non sono picchi misurati.
- `build-packages.txt`, `runtime-audit.json`: pacchetti risolti e hash dei sorgenti
  del runtime effettivamente esaminati.
- `tests.txt`: risultati dei due gruppi di test.

Restano da fare: allocazione e inferenza hardware, confronto dei log coi vettori,
tempi/memoria reali, eventuali ottimizzazioni, acquisizione e integrazione di rete.
Restano aperti ordine delle etichette del candidato, accuratezza su annotazioni
e fedeltà della preparazione immagini rispetto a Edge Impulse Studio.
