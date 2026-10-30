# FOMO FLOAT32 / INT8 su ESP32-S3-EYE

Esperimento su una scheda fisica e server PC collegati via Wi-Fi/LAN. Domanda:
INT8 riduce i byte necessari e il tempo fino al risultato, e come cambiano i
rilevamenti? Il punto di divisione resta `block_2_add`: 24×24×8 valori.
Il modello è il candidato Beer/can 96×96 in grigio già usato nelle prove PC,
esportato dall'archivio H5 locale; non è identificato con il firmware SCIoT
preinstallato sulla scheda. I due modelli archiviati hanno la stessa origine;
INT8 quantizza **pesi e attivazioni**.
Bias e tensori di forma INT32 sono previsti. Non è quantizzazione dei soli pesi.

**Risultati del 27 ottobre:** [rapporto e limiti](espnn_2026-10-27/report.md),
[dati riassunti](espnn_2026-10-27/summary.json),
[conteggi per foto](espnn_2026-10-27/quality-per-image.csv).

## Due prove distinte

- Il progetto Arduino nella radice conserva la baseline con kernel di riferimento
  (`tanakamasayuki/TensorFlowLite_ESP32@1.0.0`), senza ESP-NN. La sua prova camera
  trasmetteva anche un'immagine diagnostica e non risponde al confronto finale.
- Il progetto `idf/` usa ESP-IDF 5.4.0 e componenti ufficiali Espressif alle revisioni
  in [components.json](idf/components.json). FLOAT32 e INT8 usano lo stesso runtime,
  CPU 240 MHz, arene in PSRAM, punto di divisione e server. ESP-NN ottimizzato per S3
  è abilitato; `NN_SKIP_NUDGE` resta disabilitato. Wrapper del linker contano le
  vere chiamate a convoluzione e depthwise S3: il firmware fallisce se INT8 non le usa.

Le misure iniziali di ripetibilità hanno mostrato che `Invoke` può riutilizzare
il buffer di ingresso. Ogni invocazione riceve quindi nuovamente l'immagine,
anche durante warmup. Il controllo finale confronta i byte delle attivazioni
ricevute, non soltanto gli hash stampati dal dispositivo.

## Protocollo e misure

Il nuovo endpoint sperimentale è `POST /infer`, distinto dal protocollo originale
SCIoT. Il server gestisce una richiesta alla volta e usa un thread TensorFlow.
Non è una verifica di due client concorrenti o dello split automatico SCIoT.

- Richiesta: 32 byte di intestazione applicativa più attivazioni little endian;
  18.432 byte FLOAT32 o 4.608 byte INT8. Nessuna immagine nella prova ESP-NN.
- Risposta uguale nei due casi: 32 byte più 432 punteggi finali FLOAT32 (1.760 byte).
  Si conserva questa risposta per verificare i risultati; una risposta contenente
  soltanto gli oggetti sarebbe un'altra configurazione da misurare.
- Versione, identità del modello, frame, iterazione, dimensioni e CRC sono verificati.
  Scala e zero point corrispondono ai due modelli TFLite congelati.
- Il timer completo termina dopo la lettura della risposta; per la camera inizia
  prima di `esp_camera_fb_get`. Include preprocessing, preparazione ingresso,
  inferenza locale, impacchettamento, connessione TCP, HTTP, suffisso sul PC,
  postprocessing FOMO e ritorno dei punteggi. Non sommare di nuovo i tempi server
  al round trip HTTP, che già li comprende.
- Inizializzazione, connessione Wi-Fi iniziale e warmup sono fuori dalle misure.
  I controlli hash avvengono dopo il timer per campione.
- I byte HTTP comprendono i corpi e le intestazioni ricostruite dal server per
  il formato di richiesta generato dal client. TCP/IP, ritrasmissioni e occupazione
  radio non sono catturati. Il -75% riguarda le sole attivazioni.

Il firmware ESP-NN esegue 408 richieste misurate:

1. Tre immagini fisse × 20 ripetizioni × due rappresentazioni, ordine AB/BA.
2. Tutte le 84 foto annotate pubbliche × due rappresentazioni su input identici.
3. 20 coppie camera alternate, ciascuna invocazione con un frame nuovo.
4. Quattro sequenze continue da 20 frame, ordine FLOAT32/INT8/INT8/FLOAT32.
   La seriale viene stampata dopo ogni sequenza: gli FPS sono ricavati dalla
   durata effettiva, non dall'inverso della latenza mediana.

Confrontare byte/frame a pari frequenza di elaborazione per parlare di risparmio
di traffico. Se INT8 consente più frame/s, il traffico/s può aumentare mentre
il costo di ciascun frame diminuisce. Le due arene restano residenti insieme:
la memoria della singola arena non è il picco RAM di un firmware con un solo modello.

## Qualità

[prepare_quality.py](prepare_quality.py) congela le 84 immagini già scaricate,
verifica gli hash e incorpora nel firmware gli stessi float32 usati nell'analisi.
Il preprocessing è ritaglio quadrato centrale, Lanczos 96×96, grigio BT.601 [0,1].
Le annotazioni subiscono la stessa trasformazione. Gli oggetti il cui centro
originale esce dal ritaglio sono esclusi e vengono elencati nel manifest.
Non si ricalibra il modello su queste foto.

Il postprocessing segue le funzioni FOMO della revisione SDK Edge Impulse
`c90298a297f6361a07f179173bbcd22790bb013f`, soglia fissata a 0,5. La porta Python
è verificata contro le funzioni C++ originali estratte dal file ufficiale su
250 mappe sintetiche: conteggi, coordinate e canali devono coincidere.
[Sorgente ufficiale](https://github.com/edgeimpulse/inferencing-sdk-cpp/blob/c90298a297f6361a07f179173bbcd22790bb013f/classifier/ei_fill_result_struct.h).

Il centro del rilevamento deve cadere nel box annotato; un matching bipartito
massimo assegna ogni rilevamento e annotazione al massimo una volta. Riportiamo
veri positivi, falsi positivi, oggetti mancati, precisione, richiamo e F1.
**Il matching ignora la classe**, perché il nostro H5 non documenta l'ordine
dei canali beer/can. Non è una misura dell'accuratezza di classificazione,
né una certificazione della metrica usata da Studio. La relazione fra il set
pubblico attuale e l'addestramento dell'H5 esportato non è provata.
La qualità su foto non descrive automaticamente scene nuove o mosse dalla camera.

## Riproduzione

Usare la venv TensorFlow 2.15 del repository e una venv PlatformIO separata.
I dati originali sono quelli descritti in [TEST_SU_PC.md](../../TEST_SU_PC.md).
Eseguire dalla radice del repository:

```sh
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 .venv/bin/python experiments/esp32_representation_benchmark/prepare.py
.venv/bin/python experiments/esp32_representation_benchmark/prepare_quality.py
python3 experiments/esp32_representation_benchmark/idf/fetch_components.py
```

Copiare `include/network.local.example.h` in `include/network.local.h` e impostare
SSID, password e URL del PC. Il file è ignorato da Git. Anche i firmware compilati
contengono le credenziali e restano tra gli artefatti ignorati.

```sh
pio run -d experiments/esp32_representation_benchmark/idf
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 .venv/bin/python -u experiments/esp32_representation_benchmark/server.py --port 8767 --activations-only --decode-fomo --output experiments/esp32_representation_benchmark/results/NUOVO-RUN/server
```

Conservare prima un backup integrale verificato della flash originale. In un
secondo terminale caricare il firmware e avviare subito la cattura seriale:

```sh
pio run -d experiments/esp32_representation_benchmark/idf -t upload --upload-port PORTA
python experiments/esp32_representation_benchmark/capture.py --port PORTA --log experiments/esp32_representation_benchmark/results/NUOVO-RUN/device.log --timeout 900
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 .venv/bin/python experiments/esp32_representation_benchmark/analyze_espnn.py --run experiments/esp32_representation_benchmark/results/NUOVO-RUN
.venv/bin/python -m unittest discover -s experiments/esp32_representation_benchmark -p 'test_*.py' -v
```

`capture.py` richiede pyserial e invia `g` soltanto quando il firmware annuncia
di essere pronto. `analyze_espnn.py` rifiuta run incompleti, input errati, immagini
diagnostiche, campioni mancanti, differenze fra dispositivo e server e risultati
non ripetibili sugli ingressi fissi. Per ripetere una sessione riavviare la scheda
e usare una nuova directory. Al termine ripristinare il backup originale e
verificare hash di scrittura e avvio.

Fonti runtime: [esp-tflite-micro](https://github.com/espressif/esp-tflite-micro),
[ESP-NN](https://github.com/espressif/esp-nn),
[esp32-camera](https://github.com/espressif/esp32-camera).
