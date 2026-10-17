# SCIoT — analisi del codice superfluo e delle duplicazioni

Analisi effettuata il 15 ottobre 2026; report scritto il 17 ottobre 2026.
I percorsi sono relativi alla radice del repository per poter lavorare su un'altra macchina.

## Valutazione complessiva

La riduzione stimata tramite pulizia e accorpamento è del **20–30% del sorgente applicativo**. È una stima di refactoring, non una misura della quantità di codice morto: il maggiore problema è codice necessario copiato in più posti.

Il conteggio dell'analisi comprendeva i file versionati:

| Ambito | Righe fisiche |
| --- | ---: |
| Server Python | 1.539 |
| Tre firmware C++ (`main.cpp`) | 1.941 |
| Totale applicativo | **3.480** |
| Test Python, conteggiati separatamente | 229 |

I numeri includono commenti e righe vuote. Gli header generati dei modelli sono esclusi dal totale applicativo. Eventuali nuovi esperimenti o file non versionati non rientrano in questi conteggi.

## 1. Duplicazioni nei firmware — intervento principale

File interessati:

- `src/client/esp32-s3-eye-http/src/main.cpp`
- `src/client/esp32-s3-eye-mqtt/src/main.cpp`
- `src/client/esp32-s3-eye-websocket/src/main.cpp`

Sono state individuate **622 righe fisiche di copie aggiuntive**:

- 256 righe derivano da nove funzioni ripetute nei tre firmware, uguali salvo spaziatura: `getCurrTimeStr`, `getCurrTime`, `timeConfiguration`, `loadNeuralNetworkLayer`, `generateMessageUUID`, `getModelDataForPrediction`, `connectToWifi`, `wifiConfiguration`, `cameraConfiguration`.
- `runNeuralNetworkLayer` condivide un prefisso di 183 righe identiche nei tre firmware: altre 366 righe di copie aggiuntive. La parte finale differisce soprattutto per l'invio del risultato.

**Intervento suggerito:** estrarre camera, conversione delle immagini, orologio, caricamento dei layer, inferenza e costruzione del messaggio in codice comune. Lasciare alle tre varianti la comunicazione specifica.

Le 622 righe misurano la duplicazione individuata; il risparmio finale dipenderà anche dal codice necessario per collegare il nucleo comune ai tre protocolli. Conservare il comportamento dei timer, delle callback e dell'inferenza FOMO; compilazione e prove su dispositivo sono necessarie dopo l'accorpamento.

## 2. Vecchio sistema di logging — candidato forte alla rimozione

- `src/server/logger/init_logger.py`: 66 righe.
- `src/server/logger/logging.yml`: 38 righe.

Nell'analisi non risultavano riferimenti a `LoggerSetUp` o a questa configurazione nel resto del repository. Il logging utilizzato dal codice passa invece da `src/server/logger/log.py` e `log_config.py`.

**Intervento suggerito:** ricontrollare i riferimenti sulla macchina di lavoro ed eliminare i due file se non sono utilizzati da script esterni. Risparmio previsto: **104 righe**, di cui 66 Python.

## 3. Passaggi ridondanti e componenti senza chiamanti nel server

### `src/server/communication/request_handler.py`

- `handle_registration` restituisce soltanto `device_id`.
- `handle_offloading_layer` restituisce soltanto `best_offloading_layer`.
- `_load_stats` ricostruisce dizionari identici prima di estrarne i valori: `list({k: v for k, v in dati.items()}.values())` può diventare `list(dati.values())`.
- I risultati di `_load_stats` sono già liste, ma vengono nuovamente copiati con `list(...)` quando si costruisce `OffloadingAlgo`.

I due metodi che restituiscono l'argomento possono essere rimossi aggiornando i chiamanti, oppure mantenuti se si intende implementarvi una responsabilità concreta. Attualmente aggiungono indirezione senza elaborazione.

### `src/server/models/model_manager.py`

- `get_model_layer` non aveva chiamanti nel repository.
- `get_layer_size_in_bytes` contiene un vecchio blocco di calcolo dei pesi disattivato dentro una stringa multilinea; il codice attivo misura l'output del layer.
- `save_inference_times(save_path=...)` aggiorna e normalizza `self.save_path`, ma scrive comunque nel percorso fisso `OffloadingDataFiles.data_file_path_edge`: la gestione del parametro non influenza la destinazione.
- `self.num_layers` viene assegnato ma non risultava letto dal resto del codice.

**Intervento suggerito:** rimuovere i residui e decidere esplicitamente se supportare un percorso di salvataggio configurabile. Non cancellare il parametro lasciando chiamanti incompatibili.

### Altri residui

- `OffloadingAlgo.get_info` non aveva chiamanti nel repository.
- Nel firmware MQTT, `modelLoaded` e `firstInferenceDone` risultavano soltanto dichiarati.
- `MODEL_NAME` risultava definito nei tre firmware senza utilizzi nel codice ispezionato.
- `MqttClient.create_random_payload` è usato dal relativo test, ma non dal flusso applicativo: è un candidato allo spostamento nei test, non una funzione completamente priva di riferimenti.
- `tests/fixtures/mqtt_client_fixture.py` contiene una fixture `device_fixture` senza utilizzatori individuati, molto simile alla fixture MQTT principale.

## 4. Calcolo eseguito senza influenzare la scelta del layer

In `src/server/offloading_algo/offloading_algo.py`, `edge_only_computation_evaluation()` calcola il costo di eseguire tutto sull'edge, ma non usa il risultato per aggiornare la scelta del layer. Il risultato serve soltanto ai log.

**Intervento suggerito:** chiarire se si vuole conservare questa diagnostica. Rimuoverla può preservare la decisione attuale, mentre includere il costo nella selezione cambierebbe l'algoritmo e richiederebbe una verifica distinta.

## 5. Dipendenze da ripulire

In `pyproject.toml`:

- `paho-mqtt` è dichiarato due volte, con vincoli compatibili ma ridondanti.
- Flask e Flask-Smorest non risultavano usati dal codice ispezionato, che impiega FastAPI: sono candidati alla rimozione.
- Ruff è elencato tra le dipendenze applicative; valutare lo spostamento tra quelle di sviluppo.

Non rimuovere automaticamente librerie come `h5py` o altre dipendenze scientifiche solo perché manca un import diretto: possono essere richieste da TensorFlow, dai formati dei modelli o dagli strumenti di preparazione.

## 6. Dati e artefatti ridondanti — separati dal codice

| Elemento | Riscontro | Possibile intervento |
| --- | --- | --- |
| Header dei modelli | 60 file identici presenti in quattro posizioni, circa 1,8 MB di copie aggiuntive | Usare una sorgente comune o una procedura di generazione/copia esplicita |
| `src/server/evaluations/evaluations.csv` | 19.332.296 byte per 100 righe | Valutare quali rappresentazioni delle attivazioni servono davvero |
| `tests/logs/` | Circa 221 KB di log versionati | Verificare se sono risultati generati anziché fixture necessarie |

Gli header identici si trovano nelle tre directory firmware `src/model_layers/` e in `src/server/models/test/test_model/layers/h/`. Sono dati dei modelli necessari alle build attuali: non basta cancellare le copie senza aggiornare inclusioni e configurazione.

Nel CSV, `payload`, `message_content` e `layer_output` conservano rappresentazioni sovrapposte delle attivazioni, circa 6,4 milioni di caratteri ciascuna. Prima di ridurle, controllare notebook, dashboard e necessità di riprodurre gli esperimenti. I dati storici non sono automaticamente scartabili.

Anche la documentazione ha copie obsolete: i tre README dei firmware erano identici e descrivevano MQTT anche nelle varianti HTTP e WebSocket; `README_streamlit.md` riportava percorsi e istruzioni diversi dal README principale.

## Ordine di lavoro suggerito

1. Ricontrollare riferimenti e chiamanti, quindi rimuovere il vecchio logging e i residui confermati.
2. Semplificare copie di liste, ricostruzioni di dizionari e parametri senza effetto.
3. Accorpare il nucleo dei firmware mantenendo i tre protocolli disponibili.
4. Ripulire le dipendenze e verificare installazione e avvio in un ambiente pulito.
5. Trattare separatamente header generati, log e dati sperimentali, preservando la riproducibilità.

## Limiti della verifica

I riscontri provengono da lettura dei sorgenti, ricerca dei riferimenti, parsing AST Python e confronto dei contenuti dei file. L'assenza di chiamanti nel repository non esclude utilizzi esterni o manuali.

Durante l'analisi del 15 ottobre TensorFlow non era disponibile nell'ambiente: non sono state eseguite validazioni complete del server o prove hardware. Questa indicazione descrive l'ambiente di allora e va ricontrollata sulla macchina di lavoro.

Prima di considerare concluso un refactoring, eseguire i test Python pertinenti, compilare tutti i firmware modificati e verificare su dispositivo acquisizione immagine, inferenza, scambio dei messaggi e aggiornamento del layer di offloading. Questo report non attesta che tali verifiche siano già passate.
