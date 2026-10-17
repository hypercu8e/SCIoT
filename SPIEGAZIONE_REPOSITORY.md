# SCIoT: spiegazione del repository e dei file

Documento salvato il 17 ottobre 2026. Riprende la spiegazione e l'analisi statica del checkout svolte il 15 ottobre 2026; non costituisce una nuova verifica di eventuali modifiche successive.

L'analisi ha riguardato i sorgenti e la struttura dei modelli presenti. Non sono state eseguite inferenze o prove sulla scheda.

## 1. A cosa serve SCIoT

**SCIoT — Split Computing on IoT** serve a distribuire l'esecuzione di una rete neurale tra una scheda ESP32 e un server.

Una rete neurale elabora un'immagine attraverso una successione di trasformazioni, chiamate *layer* o strati. Ogni strato produce risultati intermedi, detti **attivazioni**, che alimentano gli strati successivi.

SCIoT sceglie un punto in cui interrompere il lavoro sull'ESP32 e continuarlo sul server:

```mermaid
flowchart LR
    A[Telecamera ESP32] --> B[Preparazione immagine]
    B --> C[Strati da 0 a k<br/>eseguiti su ESP32]
    C -->|Attivazioni intermedie| D[Strati successivi<br/>eseguiti sul server]
    D --> E[Risultato della rete]
    D --> F[Valutazione tempi e rete]
    F -->|Nuovo punto di split k| C
```

Per esempio, con punto di split `16`:

1. L'ESP32 acquisisce l'immagine.
2. Esegue gli strati da `0` a `16`, compresi.
3. Invia al server l'uscita dello strato `16` e i tempi di esecuzione.
4. Il server esegue gli strati successivi.
5. Stima quale punto di split conviene usare nelle elaborazioni successive.

**Nei firmware esaminati viene inviata anche l'immagine catturata**, separatamente dalle attivazioni. Il server la salva per mostrarla nella dashboard.

## 2. Struttura generale

```text
SCIoT/
├── configurazione e documentazione
├── src/
│   ├── client/
│   │   ├── esp32-s3-eye-http/
│   │   ├── esp32-s3-eye-mqtt/
│   │   ├── esp32-s3-eye-websocket/
│   │   └── python/
│   └── server/
│       ├── communication/
│       ├── device/
│       ├── edge/
│       ├── evaluations/
│       ├── logger/
│       ├── models/
│       ├── mosquitto_broker/
│       ├── offloading_algo/
│       └── web/
└── tests/
```

Nei paragrafi successivi sono descritti i file del progetto. I numerosi file generati dei modelli sono raggruppati per intervalli precisi: hanno la stessa funzione, cambia lo strato della rete che contengono. Le dipendenze installate nell'ambiente virtuale e i file interni di Git sono descritti per categoria.

## 3. File nella cartella principale

| File | Cosa contiene e a cosa serve |
|---|---|
| [README.md](README.md) | Presentazione del progetto, pubblicazioni associate, preparazione dell'ambiente con `uv`, importazione del modello e comandi per avviare broker, server e dashboard. |
| [README_streamlit.md](README_streamlit.md) | Documentazione precedente, concentrata sul server MQTT e sulla dashboard. Contiene nomi, percorsi e istruzioni meno aggiornati rispetto alla struttura esaminata. |
| [pyproject.toml](pyproject.toml) | Definisce il pacchetto Python `sciot`, gli autori, le dipendenze e le impostazioni di build, test e coverage. Richiede Python `>=3.11,<3.12` e TensorFlow `2.15.0`. |
| [.python-version](.python-version) | Indica Python `3.11` agli strumenti che gestiscono la versione dell'interprete. |
| `uv.lock` | Registra le versioni risolte delle dipendenze per riprodurre l'ambiente. Era presente localmente, ma il `.gitignore` lo esclude dal versionamento. |
| [.gitignore](.gitignore) | Esclude ambiente virtuale, cache Python, file di build, metadati del pacchetto, log e altri file generati. |
| [docker-compose.yml](docker-compose.yml) | Definisce il container del broker MQTT Mosquitto: immagine da costruire, porte, rete e cartelle condivise per configurazione, dati e log. Avvia il broker; il server Python viene avviato separatamente. |
| [LICENSE](LICENSE) | Testo della licenza GNU GPL versione 3. |
| [.github/workflows/codecov.yml](.github/workflows/codecov.yml) | Workflow GitHub Actions: prepara Python 3.11, installa progetto e dipendenze di test, esegue `pytest` con coverage e invia il rapporto a Codecov. |

### File locali aggiuntivi presenti al momento dell'analisi

Questi quattro file non erano tracciati da Git al momento dell'analisi:

| File | Contenuto |
|---|---|
| [SCALETTA_TIROCINIO.md](SCALETTA_TIROCINIO.md) | Contesto del tirocinio, verifiche precedenti, questioni aperte e percorso di lavoro. Descrive l'idea di comprimere le differenze tra attivazioni di frame consecutivi. |
| [IDEE_DA_ESPLORARE.md](IDEE_DA_ESPLORARE.md) | Annotazioni su possibili sviluppi. La versione esaminata descrive la selezione dei frame, evitando inferenza e trasmissione quando l'immagine cambia poco. |
| [canCoke.jpeg](canCoke.jpeg) | Immagine locale aggiuntiva. Il percorso di input predefinito del server punta invece a `test_image.png`. |
| `ei-object-detection-with-fomo---bottles-vs.-cans-object-detection-keras-h5-model-model.5.zip` | Archivio che contiene un file `model.h5`. La sua presenza nella cartella principale non lo rende automaticamente il modello utilizzato dal server. |

## 4. Server Python: configurazione e statistiche

Il server riceve i dati, completa la rete e sceglie il punto di split.

| File | Cosa contiene e a cosa serve |
|---|---|
| [src/server/commons.py](src/server/commons.py) | Centralizza i percorsi: statistiche JSON, valutazioni CSV, configurazione YAML, modelli e immagini. Costruisce i percorsi a partire dalla posizione del file. |
| [src/server/settings.yaml](src/server/settings.yaml) | Configura protocolli, porte, endpoint HTTP, topic MQTT, server NTP e modello. La versione esaminata indica `fomo_96x96`, input `96×96` e ultimo strato `58`. |
| [src/server/device_inference_times.json](src/server/device_inference_times.json) | Tempi dei 59 strati sull'ESP32, con chiavi come `layer_0`. Viene aggiornato usando i tempi comunicati dal dispositivo. |
| [src/server/edge_inference_times.json](src/server/edge_inference_times.json) | Tempi dei 59 strati sul server, con chiavi da `"0"` a `"58"`. |
| [src/server/layer_sizes.json](src/server/layer_sizes.json) | Dimensioni in byte delle uscite dei 59 strati. Servono a stimare il costo della trasmissione al punto di split. Sono dimensioni delle **attivazioni**, non dei pesi del modello. |

I tre JSON costituiscono i dati di ingresso dell'algoritmo di scelta: quanto costa calcolare sul dispositivo, quanto costa sul server e quanti dati occorre trasmettere.

## 5. Avvio ed esecuzione sul server

| File | Cosa contiene e a cosa serve |
|---|---|
| [src/server/edge/run_edge.py](src/server/edge/run_edge.py) | Punto di ingresso del server. Legge `settings.yaml`, inizializza le statistiche del modello e costruisce il gestore di comunicazione scelto. |
| [src/server/edge/edge_initialization.py](src/server/edge/edge_initialization.py) | Contiene la classe `Edge`. `initialization()` esegue la rete su un'immagine di prova, misura i tempi e salva le dimensioni delle attivazioni. `run_inference()` riparte dalle attivazioni ricevute e completa gli strati rimanenti. |
| [src/server/device/device_initialization.py](src/server/device/device_initialization.py) | Contiene la classe `Device`. Prepara un JSON con un tempo iniziale pari a zero per ogni strato. Non esegue la rete su un ESP32: inizializza soltanto le statistiche lato server. |

In `Edge.run_inference()` il modello Keras serve anche a ricostruire le dipendenze tra gli strati; il calcolo di ciascuno strato viene poi svolto con il corrispondente sott modello TFLite.

## 6. Comunicazione

La cartella `communication/` separa la logica comune dal protocollo usato.

| File | Cosa contiene e a cosa serve |
|---|---|
| [src/server/communication/request_handler.py](src/server/communication/request_handler.py) | È il coordinatore delle richieste. Decodifica il messaggio binario, aggiorna i tempi del dispositivo, fa completare l'inferenza, salva le misure e richiama l'algoritmo di offloading. Converte e salva anche le immagini ricevute. |
| [src/server/communication/message_data.py](src/server/communication/message_data.py) | Definisce `MessageData`, contenitore dei dati di un messaggio. Include funzioni per calcolare latenza, dimensione del payload, velocità stimata e salvataggio in CSV. |
| [src/server/communication/http_server.py](src/server/communication/http_server.py) | Server FastAPI con endpoint per registrazione, ricezione immagine, ricezione attivazioni e richiesta del punto di split. Usa Uvicorn per l'esecuzione. |
| [src/server/communication/websocket_server.py](src/server/communication/websocket_server.py) | Server FastAPI con una connessione WebSocket. Riceve registrazioni in JSON e immagini/attivazioni come messaggi binari; restituisce il punto di split sulla stessa connessione. |
| [src/server/communication/mqtt_client.py](src/server/communication/mqtt_client.py) | Client MQTT del server edge. Si collega al broker, sottoscrive i topic e smista i messaggi. Usa una coda e un thread per elaborare le richieste ricevute; pubblica il nuovo punto di split. |

Il messaggio binario delle attivazioni contiene, in sequenza:

```text
timestamp
identificativo dispositivo
identificativo messaggio
indice dello strato di split
dimensione delle attivazioni
valori delle attivazioni
dimensione dei tempi
tempi degli strati eseguiti sul dispositivo
```

`RequestHandler._from_raw()` interpreta questi byte. Perciò formato e dimensioni dei campi devono corrispondere tra firmware e server.

La velocità di rete viene stimata in `MessageData` come:

```text
dimensione del messaggio / latenza osservata
```

È una stima ricavata dai messaggi, sensibile anche alla sincronizzazione degli orologi.

## 7. Algoritmo di offloading

La decisione su dove dividere il lavoro è concentrata in [src/server/offloading_algo/offloading_algo.py](src/server/offloading_algo/offloading_algo.py).

Contiene la classe `OffloadingAlgo`. Per ogni punto candidato `k`, valuta:

```text
costo(k) =
    somma dei tempi ESP32 fino a k
    + dimensione delle attivazioni di k / velocità stimata
    + somma dei tempi server dopo k
```

| Metodo | Funzione |
|---|---|
| `evaluation()` | Calcola il costo di una configurazione. |
| `mixed_computation_evaluation()` | Confronta le divisioni tra dispositivo e server. |
| `device_only_evaluation()` | Valuta l'esecuzione dell'intera rete sul dispositivo, includendo l'invio dell'uscita. |
| `edge_only_computation_evaluation()` | Calcola un costo per l'esecuzione sul server, ma il codice non lo usa per aggiornare la scelta migliore. |
| `static_offloading()` | Esegue il confronto e restituisce l'indice selezionato. |
| `get_info()` | Restituisce lo stato dell'oggetto come dizionario. |

Nonostante il nome `static_offloading()`, il gestore lo richiama dopo aver ricevuto nuove misure: il punto scelto può quindi cambiare nel tempo.

Il costo implementato considera tempi e trasmissione; non contiene termini espliciti per energia, scadenze o code di più dispositivi.

## 8. Gestione e preparazione dei modelli

| File | Cosa contiene e a cosa serve |
|---|---|
| [src/server/models/model_manager_config.py](src/server/models/model_manager_config.py) | Valori predefiniti per nome e cartella del modello e per alcuni script di generazione. Il modello predefinito è `test_model.h5`. |
| [src/server/models/model_manager.py](src/server/models/model_manager.py) | Carica il modello completo e gestisce l'esecuzione dei singoli strati attraverso TFLite. Misura i tempi, calcola i byte delle attivazioni e salva le statistiche. |
| [src/server/models/model_split.py](src/server/models/model_split.py) | Scompone il modello Keras in un sott modello per ogni strato eseguibile. Produce file `.h5`, `.tflite` e header `.h`, oltre al selettore `layers.h`. Gestisce anche la creazione di ingressi multipli per gli strati che li richiedono. |
| [src/server/models/model_build.py](src/server/models/model_build.py) | Costruisce e salva una piccola rete dimostrativa: convoluzione, Batch Normalization, ReLU, Max Pooling e Dense. Il nome della funzione richiama ResNet, ma il codice non costruisce una ResNet completa con blocchi residui. |
| [src/server/models/model_input_converter.py](src/server/models/model_input_converter.py) | Converte un'immagine PNG in array NumPy e i byte RGB565 della telecamera in pixel RGB. La normalizzazione viene applicata dai chiamanti. |

La trasformazione dei formati è questa:

```text
Modello Keras completo
        ↓ model_split.py
Un sott modello per strato
        ├── .h5      → rappresentazione Keras
        ├── .tflite  → formato usato per l'esecuzione
        └── .h       → stessi dati incorporabili nel firmware C++
```

Un `.h` del modello contiene quindi **un array di byte**, che rappresenta il sott modello serializzato, con struttura e parametri necessari all'esecuzione.

### Modello principale: `models/test/test_model/`

I percorsi nella tabella sono relativi a `src/server/models/test/test_model/`.

| File o famiglia | Contenuto |
|---|---|
| `test_model.h5` | Modello completo caricato dal server con le impostazioni predefinite. Dai metadati risulta un ingresso `96×96×3`, un `InputLayer` e 59 strati eseguibili. |
| `pred_data/test_image.png` | Immagine usata per inizializzare tempi e dimensioni sul server. |
| `layers/h5/submodel_0.h5` … `submodel_58.h5` | I 59 sott modelli Keras, uno per strato eseguibile. |
| `layers/tflite/submodel_0.tflite` … `submodel_58.tflite` | Gli stessi 59 sott modelli convertiti in TFLite, caricati da `ModelManager`. |
| `layers/h/layer_0.h` … `layer_58.h` | I 59 sott modelli TFLite sotto forma di array C++. |
| `layers/h/layers.h` | Include gli header e definisce `LOAD_LAYER()`, macro che seleziona il modello corrispondente a un nome come `"layer_16"`. |

Per capire cosa contiene ciascuno dei file numerati, si può usare questa corrispondenza. L'indice vale per tutte e tre le rappresentazioni: per esempio `submodel_25.h5`, `submodel_25.tflite` e `layer_25.h` rappresentano lo stesso strato.

| Indici | Operazione contenuta |
|---|---|
| `0, 6, 8, 15, 17, 23, 26, 33, 35, 41, 44, 50, 53, 56, 57` | **Conv2D:** convoluzioni che trasformano le caratteristiche dell'immagine. |
| `1, 4, 7, 9, 13, 16, 18, 21, 24, 27, 31, 34, 36, 39, 42, 45, 48, 51, 54` | **BatchNormalization:** trasformazioni di normalizzazione con i parametri del modello. |
| `2, 5, 10, 14, 19, 22, 28, 32, 37, 40, 46, 49, 55` | **ReLU:** funzioni di attivazione. |
| `3, 12, 20, 30, 38, 47` | **DepthwiseConv2D:** convoluzioni applicate separatamente ai canali. |
| `11, 29` | **ZeroPadding2D:** aggiunta di bordi di zeri ai tensori. |
| `25, 43, 52` | **Add:** somma delle attivazioni provenienti da due rami della rete. |
| `58` | **Softmax:** trasformazione finale dei punteggi in probabilità lungo l'asse configurato. |

Gli strati `Add` spiegano una difficoltà dello split: **alcuni punti della rete richiedono anche un risultato precedente**, oltre all'uscita dello strato immediatamente antecedente.

### Modello dimostrativo: `models/resnet_model/`

I percorsi nella tabella sono relativi a `src/server/models/resnet_model/`.

| File o famiglia | Contenuto |
|---|---|
| `resnet_model.keras` | Piccolo modello completo con Conv2D, BatchNormalization, ReLU, MaxPooling2D e Dense. |
| `layers/keras/submodel_0.keras` … `submodel_4.keras` | I cinque sott modelli in formato Keras. |
| `layers/tflite/submodel_0.tflite` … `submodel_4.tflite` | Le cinque versioni TFLite. |
| `layers/h/layer_0.h` … `layer_4.h` | Le cinque versioni incorporabili in C++. |

Questo secondo insieme non viene selezionato dal percorso predefinito di `ModelManager`.

## 9. Valutazioni, dashboard e log

| File | Cosa contiene e a cosa serve |
|---|---|
| [src/server/evaluations/evaluations.csv](src/server/evaluations/evaluations.csv) | Archivio delle misure dei messaggi. Al momento dell'analisi conteneva 100 record con timestamp, dispositivo, payload, latenza, velocità stimata, indice di split, attivazioni e tempi del dispositivo. |
| [src/server/evaluations/edit_evaluations.ipynb](src/server/evaluations/edit_evaluations.ipynb) | Notebook per trasformare il CSV: interpreta liste salvate come testo, le espande in colonne e produce CSV ripuliti. Alcune colonne attese non corrispondono al CSV esaminato, quindi richiede una verifica prima dell'uso. |
| [src/server/web/webpage.py](src/server/web/webpage.py) | Dashboard Streamlit. Rilegge i dati ogni tre secondi e mostra split, dimensione del payload, latenza, velocità stimata, tempi per strato e immagine ricevuta. |
| [src/server/logger/log.py](src/server/logger/log.py) | Configura il logger usato dai sorgenti: console, formato dei messaggi e file con rotazione temporale. |
| [src/server/logger/log_config.py](src/server/logger/log_config.py) | Costanti per cartella dei log, livelli e conservazione. |
| [src/server/logger/init_logger.py](src/server/logger/init_logger.py) | Classe alternativa di configurazione del logging basata su un dizionario e sull'ambiente `ENV_RUN`. |
| [src/server/logger/logging.yml](src/server/logger/logging.yml) | Configurazione YAML associata al sistema alternativo: formati, handler e livelli per sviluppo, test e produzione. |

Nel percorso principale i moduli importano il logger da `log.py`.

## 10. Broker MQTT

| File | Funzione |
|---|---|
| [src/server/mosquitto_broker/dockerfiles/Dockerfile](src/server/mosquitto_broker/dockerfiles/Dockerfile) | Usa come base `eclipse-mosquitto:2.0.18`. |
| [src/server/mosquitto_broker/conf/mosquitto.conf](src/server/mosquitto_broker/conf/mosquitto.conf) | Imposta listener sulla porta `1883`, destinazione dei log, dimensione massima dei pacchetti e accesso anonimo. |

Mosquitto fa da intermediario: riceve i messaggi pubblicati dall'ESP32 e li consegna al client MQTT del server, e viceversa.

## 11. Client ESP32

| Cartella | Comunicazione |
|---|---|
| `src/client/esp32-s3-eye-http/` | Richieste HTTP agli endpoint del server. |
| `src/client/esp32-s3-eye-mqtt/` | Pubblicazione e sottoscrizione attraverso il broker MQTT. |
| `src/client/esp32-s3-eye-websocket/` | Connessione WebSocket per inviare dati e ricevere risposte. |

Le tre cartelle hanno quasi la stessa struttura. La tabella seguente copre i file presenti **in ciascuna delle tre**.

| File relativo alla cartella del client | Cosa contiene e a cosa serve |
|---|---|
| `README.md` | Istruzioni di preparazione e descrizione del firmware. Anche i README delle varianti HTTP e WebSocket contengono molto testo riferito a MQTT: per le differenze effettive conta il sorgente. |
| `platformio.ini` | Configura scheda, framework Arduino, monitor seriale, opzioni di compilazione e dipendenze. La libreria di comunicazione cambia secondo la variante. |
| `src/conf.template.h` | Modello di configurazione: Wi-Fi, indirizzo del server/broker, NTP, dimensioni dell'immagine, numero di strati, buffer, watchdog e pin della telecamera. Va adattato nel `conf.h` incluso dal firmware. |
| `src/main.cpp` | Programma completo della scheda: inizializzazione, acquisizione, preparazione dell'immagine, esecuzione degli strati, misurazione dei tempi e comunicazione. |
| `src/model_layers/layer_0.h` … `layer_58.h` | I 59 sott modelli incorporati nel firmware. Al momento dell'analisi coincidevano con gli header della cartella del modello sul server. |
| `src/model_layers/layers.h` | Include tutti gli strati e definisce la macro per selezionarli. Anche questo coincideva con la copia sul server. |
| `include/README` | Testo standard PlatformIO che spiega dove mettere header aggiuntivi. |
| `lib/README` | Testo standard PlatformIO che spiega dove mettere librerie locali. |
| `test/README` | Testo standard PlatformIO sui test. Non contiene test del firmware. |
| `.gitignore` | Esclude build PlatformIO, configurazioni dell'editor, log e il file locale `src/conf.h`. |
| `LICENSE` | Copia della licenza GPL versione 3. |

### Parti comuni dei tre `main.cpp`

| Parte | Comportamento |
|---|---|
| `setup()` | Inizializza seriale, watchdog, PSRAM, buffer, telecamera, timer e comunicazione. |
| `cameraConfiguration()` | Configura pin e acquisizione in RGB565 a `96×96`. |
| `getModelDataForPrediction()` | Converte i pixel RGB565 in valori RGB normalizzati per la rete. |
| `loadNeuralNetworkLayer()` | Seleziona il sott modello e prepara l'interprete TensorFlow Lite Micro. |
| `runNeuralNetworkLayer()` | Esegue gli strati fino al punto di split, misura i tempi e prepara il messaggio con le attivazioni. |
| Gestione `FOMO` | Conserva uscite intermedie necessarie ai collegamenti tra rami. Gli indici sono specificati nel codice per il modello incluso. |
| Funzioni Wi-Fi e timer | Gestiscono connessione, riconnessione e registrazione. |
| Funzioni temporali | Sincronizzano l'orologio con NTP e producono timestamp. |
| `loop()` | Acquisisce un frame, lo invia se registrato, prepara l'input, esegue la rete e restituisce il buffer alla telecamera. |

### Differenze tra i tre firmware

- [HTTP `main.cpp`](src/client/esp32-s3-eye-http/src/main.cpp): usa richieste `POST` per registrazione, immagine e attivazioni; una richiesta `GET` recupera il punto di split.
- [MQTT `main.cpp`](src/client/esp32-s3-eye-mqtt/src/main.cpp): costruisce i topic, pubblica registrazione, immagine e attivazioni e riceve il punto di split tramite sottoscrizione.
- [WebSocket `main.cpp`](src/client/esp32-s3-eye-websocket/src/main.cpp): invia registrazione JSON e messaggi binari sulla connessione; elabora le risposte tramite callback e chiamate a `poll()`.

I template esaminati configurano **59 strati, tre canali RGB e una tensor arena da circa 1 MiB**, più altri buffer in PSRAM.

### Altri file sotto `client/`

| File | Contenuto |
|---|---|
| [src/client/README.md](src/client/README.md) | Breve descrizione della cartella dei client. |
| [src/client/python/README.md](src/client/python/README.md) | Soltanto la dicitura “Python SCIoT client”. Nel checkout esaminato, **in questa cartella non c'è un client Python eseguibile**. |

## 12. Test Python

| File | Cosa contiene e a cosa serve |
|---|---|
| [tests/commons.py](tests/commons.py) | Percorsi dei file JSON di esempio usati nei test. |
| [tests/conftest.py](tests/conftest.py) | Registra i moduli che forniscono le fixture di pytest. |
| [tests/fixtures/offloading_fixtures.py](tests/fixtures/offloading_fixtures.py) | Carica tempi e dimensioni dai JSON di esempio e li fornisce ai test. |
| [tests/fixtures/mqtt_client_fixture.py](tests/fixtures/mqtt_client_fixture.py) | Sostituisce alcuni percorsi con quelli di test e costruisce istanze di `MqttClient`. La costruzione comprende la sincronizzazione NTP. |
| [tests/test_edge/test_edge.py](tests/test_edge/test_edge.py) | Richiama l'inizializzazione del server sul modello `96×96`. Non verifica esplicitamente il risultato numerico dell'inferenza. |
| [tests/test_mqtt_client/test_mqtt_client.py](tests/test_mqtt_client/test_mqtt_client.py) | Verifica creazione del payload e chiamate a pubblicazione, sottoscrizione, connessione e disconnessione, usando mock. |
| [tests/test_offloading_algo/test_offloading_algo.py](tests/test_offloading_algo/test_offloading_algo.py) | Prova l'algoritmo con due condizioni estreme di latenza. Controlla un limite sull'indice restituito. |
| [tests/test_samples/device_inference_times.json](tests/test_samples/device_inference_times.json) | Tempi di esempio del dispositivo per cinque strati. |
| [tests/test_samples/edge_inference_times.json](tests/test_samples/edge_inference_times.json) | Tempi di esempio del server per cinque strati. |
| [tests/test_samples/layer_sizes.json](tests/test_samples/layer_sizes.json) | Dimensioni di esempio delle attivazioni per cinque strati. |
| `tests/logs/DEBUG.log` | Log storico con messaggi dettagliati. |
| `tests/logs/INFO.log` | Log storico con messaggi informativi, comprese valutazioni dell'algoritmo. |
| `tests/logs/WARNING.log` | File dei warning; vuoto al momento dell'analisi. |
| `tests/logs/ERROR.log` | File degli errori; vuoto al momento dell'analisi. |

C'è un dettaglio da tenere presente nel test dell'algoritmo: passa i tempi del dispositivo anche come tempi del server. La fixture con i tempi edge è ricevuta dalla funzione, ma non viene usata nella costruzione di `OffloadingAlgo`.

## 13. File `__init__.py`

I file `__init__.py` esaminati sono tutti vuoti. Identificano i pacchetti Python e si trovano in:

```text
src/server/
src/server/device/
src/server/edge/
src/server/evaluations/
src/server/logger/
src/server/models/
src/server/mosquitto_broker/
src/server/offloading_algo/
tests/
tests/fixtures/
```

## 14. File e cartelle generati dagli strumenti

| Percorso | Contenuto |
|---|---|
| `.venv/` | Ambiente virtuale Python: interprete, eseguibili e dipendenze installate. |
| `src/sciot.egg-info/PKG-INFO` | Metadati del pacchetto installato: nome, versione, descrizione e dipendenze. |
| `src/sciot.egg-info/SOURCES.txt` | Elenco dei file associati alla distribuzione del pacchetto. |
| `src/sciot.egg-info/requires.txt` | Dipendenze del pacchetto. |
| `src/sciot.egg-info/top_level.txt` | Pacchetti principali, qui `client` e `server`. |
| `src/sciot.egg-info/dependency_links.txt` | File di collegamenti aggiuntivi alle dipendenze; sostanzialmente vuoto. |
| `.git/` | Cronologia, riferimenti e metadati del repository. |

Questi file vengono gestiti dagli strumenti e non contengono la logica applicativa di SCIoT.

## 15. Limiti visibili nell'implementazione esaminata

### Avvio dei protocolli sequenziale e bloccante

`settings.yaml` elenca WebSocket, HTTP e MQTT, ma `run_edge.py` avvia prima WebSocket e rimane nella sua chiamata `run()`. La lista non determina tre servizi contemporanei.

### Stato condiviso

Il punto di split, i JSON delle statistiche e l'immagine salvata non sono organizzati come stati indipendenti per ogni dispositivo.

### Dipendenze tra rami della rete

Il server riceve un solo tensore di attivazioni; alcuni strati successivi possono richiedere risultati precedenti che quel tensore non contiene. Di conseguenza, non tutti i punti di split sono necessariamente validi.

### Compressione differenziale ancora proposta

La compressione differenziale è descritta nei documenti locali come direzione da esplorare. Il percorso esaminato trasmette le attivazioni complete e non conserva un riferimento tra frame per ricostruirle da differenze.

## 16. Ordine consigliato per studiare il codice

Per seguire un'elaborazione reale:

```text
main.cpp del client
    → request_handler.py
    → edge_initialization.py
    → model_manager.py
    → offloading_algo.py
    → risposta al client
```

`model_split.py` si studia a parte: prepara i file che questo percorso utilizza durante l'esecuzione.
