# SCIoT: ottimizzazioni del firmware ESP32

Documento del 17 ottobre 2026, predisposto come approfondimento da integrare in [ANALISI_MIGLIORAMENTI_SCIOT.md](ANALISI_MIGLIORAMENTI_SCIOT.md), dopo la sezione 9 oppure come appendice dedicata al firmware.

**Obiettivo:** ridurre tempi, occupazione di memoria e lavoro superfluo sul dispositivo, mantenendo il modello e l'interfaccia del server attuali. Si parte dai progetti PlatformIO esistenti; una migrazione a ESP-IDF o una nuova repository non sono prerequisiti.

**Base dell'analisi:** sorgenti del checkout `087fef9`, in particolare i tre client ESP32-S3-EYE. I problemi indicati come riscontri sono rilevati dal codice; i benefici delle proposte devono essere misurati sulla scheda. In questa attività non sono stati compilati, modificati o caricati firmware, né raccolti benchmark hardware.

## 1. Perimetro e ordine delle priorità

**Aggiornamento del 19 ottobre 2026:** applicati ai tre client i prerequisiti di
correttezza per interprete, buffer e serializzazione; ridotto il buffer messaggio
nei template e preparate build ripetibili. Le sezioni seguenti conservano l'analisi
storica e le proposte; lo stato implementato e i limiti sono nel
[report delle correzioni](experiments/firmware_fixes_2026-10-19/README.md).
Verificati sul PC codice C++ condiviso, runtime Micro reale e parser del server;
compilati HTTP/MQTT/WebSocket. Nessuna misura hardware.

Il documento riguarda codice C++, configurazione della build, gestione della camera, memoria, inferenza e comunicazione sul dispositivo. Il parser del server è stato consultato soltanto per verificare la compatibilità delle proposte con il formato esistente.

| Priorità | Intervento | Risultato da verificare |
|---|---|---|
| P0 | Correggere durata di interprete e resolver, controlli e gestione degli errori | Inferenza valida e assenza di accessi a memoria non valida |
| P0 | Correggere serializzazione e lunghezze dei messaggi | Pacchetti leggibili dal server, senza dati non inizializzati |
| P1 | Separare misure di caricamento, copie, calcolo e invio | Confronti ripetibili e individuazione del costo dominante |
| P1 | Dimensionare buffer e arena; limitare allocazioni ripetute | Minore memoria occupata e maggiore stabilità nel tempo |
| P1 | Ridurre log, costruzioni di stringhe e ricerca del layer | Minore lavoro di supporto per ogni inferenza |
| P1 | Gestire invii in corso, callback e riconnessioni | Code limitate, dati coerenti e recupero della connessione |
| P2 | Ottimizzare conversione RGB565 e copie dei tensori | Riduzione del tempo di preparazione e movimento dei dati |
| P2 | Valutare task separati e configurazione della camera | Minore attesa o maggiore frequenza di elaborazione |
| P2 | Condividere il motore fra i tre firmware | Correzioni uniformi e confronti fra trasporti più affidabili |

P0 indica prerequisiti di correttezza. P1 e P2 esprimono un ordine iniziale: dopo le prime misure, la priorità delle ottimizzazioni dipende dai costi osservati.

## 2. Correggere i difetti prima di confrontare le prestazioni

### 2.1 Durata di interprete e resolver

Nei tre `main.cpp`, `loadNeuralNetworkLayer()` costruisce un `AllOpsResolver` e un `MicroInterpreter` locali, poi assegna l'indirizzo dell'interprete al puntatore globale `interpreter`. Al ritorno dalla funzione entrambi gli oggetti cessano di esistere; il chiamante usa comunque quel puntatore per accedere ai tensori e invocare il modello.

Il nome `static_interpreter` non attribuisce durata statica all'oggetto. È un difetto di correttezza, anche se una particolare esecuzione sembra funzionare.

**Intervento:** definire un ciclo di vita esplicito. Una prima soluzione consiste nell'eseguire costruzione, allocazione, inferenza ed estrazione dell'output entro lo stesso ambito, copiando i dati necessari prima di distruggere l'interprete. In alternativa si può usare un contesto persistente con costruzione e distruzione controllate. In entrambi i casi anche il resolver deve restare valido per tutta la durata dell'interprete.

Non basta aggiungere `static` all'interprete: il modello cambia a ogni layer e un oggetto inizializzato una sola volta rimarrebbe associato al primo modello. Non è corretto neppure conservare più interpreti già allocati sulla stessa arena e usarli come se avessero memoria indipendente.

**Verifica:** ripetere inferenze sugli stessi input, cambiare punto di split e confrontare le attivazioni con un riferimento numerico. Le prestazioni vanno confrontate dopo questa correzione.

### 2.2 Errori, dimensioni e limiti dei tensori

Nel codice attuale:

- Un errore di schema o di `AllocateTensors()` causa un ritorno da `loadNeuralNetworkLayer()`, senza un esito che obblighi il chiamante a interrompere l'inferenza.
- Il risultato di `Invoke()` viene ignorato.
- Le allocazioni principali con `ps_malloc()` non vengono controllate e il setup prosegue anche dopo il messaggio di errore della PSRAM.
- Il percorso assume tensori `float32`, accede a `data.f` e usa dimensioni di copia calcolate esternamente.
- Per il secondo ingresso dei layer FOMO viene riutilizzata `inputSize`, anziché verificare la dimensione specifica di quell'ingresso e dei dati conservati.
- MQTT controlla solo il limite superiore dell'indice ricevuto; HTTP lo assegna senza un controllo equivalente. WebSocket controlla già entrambi i limiti.

**Intervento:** propagare gli errori, verificare tipo, forma e capacità dei buffer e ammettere soltanto indici interi nell'intervallo `0 <= indice < MAX_NUM_LAYER`. Campo mancante, tipo errato o inferenza fallita non devono produrre un pacchetto presentato come valido. Inizializzare con `{}` la struttura di configurazione della camera e interrompere il percorso operativo se la sua inizializzazione fallisce.

I controlli di dimensione sono necessari anche quando si mantengono gli stessi modelli: impediscono che una configurazione incoerente diventi una scrittura fuori dal buffer. Il blocco `try/catch` della conversione immagini non protegge dagli accessi fuori limite ai puntatori.

### 2.3 Composizione dei messaggi binari

I tre firmware copiano gli identificativi con `memcpy(..., &DeviceUUID, 9)` e `memcpy(..., &MessageUUID, 4)`. Questi sono indirizzi di oggetti Arduino `String`, non i byte del loro contenuto. Il [parser esistente](src/server/communication/request_handler.py) attende invece 9 e 4 byte di testo.

Inoltre `inference_times[MAX_NUM_LAYER]` viene riempito solo fino al layer eseguito. Il pacchetto dichiara la lunghezza dei tempi fino allo split, ma copia e invia l'intero array: con uno split anticipato trasmette anche elementi non inizializzati. Il calcolo della lunghezza usa `sizeof(int)` per un array di `float`.

**Intervento, compatibile con il parser attuale:**

- Copiare il contenuto degli identificativi, per esempio da `c_str()`, dopo averne verificato la lunghezza prevista.
- Inviare esattamente `(indice_split + 1) * sizeof(float)` byte di tempi validi.
- Usare un unico valore di lunghezza per campo dichiarato, copia e avanzamento dell'offset.
- Controllare che ogni scrittura rientri nella capacità del messaggio e mantenere l'ordine e la rappresentazione dei campi attesi dal server.

Questa correzione elimina dati non validi e byte superflui senza introdurre un nuovo protocollo. La definizione di un formato portabile diverso resta fuori dal perimetro.

## 3. Misurare separatamente i costi del firmware

La misura corrente parte da `float inizio = micros()` prima del caricamento del layer e termina dopo copie, inferenza e parte dei log. Quindi il valore chiamato tempo di inferenza include più operazioni. Conservare il contatore in un `float` introduce inoltre una perdita di precisione crescente con il tempo di accensione.

**Intervento:** usare un contatore monotono intero e calcolare prima la differenza, poi convertirla nell'unità desiderata. Se si usa un contatore a 32 bit, gestire il riavvolgimento con sottrazione senza segno e intervalli inferiori al suo periodo.

Misurare almeno:

| Fase | Costo da isolare |
|---|---|
| Acquisizione | Attesa e ottenimento del frame |
| Preparazione | Conversione RGB565 e normalizzazione |
| Preparazione del layer | Selezione del modello, costruzione dell'interprete e `AllocateTensors()` |
| Copie | Ingressi, uscite e attivazioni conservate per FOMO |
| Calcolo | Solo `Invoke()` |
| Serializzazione | Preparazione del pacchetto binario |
| Comunicazione | Accodamento dell'invio e completamento, quando osservabile |

Una chiamata asincrona di invio può terminare prima che il trasferimento sia completato. Il suo tempo di ritorno non dimostra la latenza di rete e, soprattutto, non dimostra che il server abbia completato l'inferenza.

Conservare le misure in memoria e stampare riepiloghi fuori dal tratto misurato. Mantenere nei messaggi attuali un costo per layer coerente con l'esecuzione effettiva; i dettagli aggiuntivi possono restare diagnostica locale. Sostituire silenziosamente il costo totale con il solo `Invoke()` altererebbe i dati usati dal server per scegliere lo split.

## 4. Ridurre memoria occupata e allocazioni ripetute

### 4.1 Buffer di uscita sovradimensionato

Nei `conf.template.h`, `OUTPUT_MSG_SIZE` riserva spazio per due attivazioni massime, mentre la serializzazione attuale ne invia una sola. Con le costanti incluse:

- `MAX_ELEMENTS_PER_MODEL_LAYER = 115.248` elementi;
- un buffer massimo `float32` occupa `460.992` byte;
- l'arena è impostata a `1.024.000` byte;
- `output_message` riserva `922.253` byte, assumendo le dimensioni dei tipi del target e i 59 tempi previsti.

Input, arena, messaggio e buffer FOMO sommano così **2.868.237 byte di allocazioni esplicite**, esclusi camera, librerie, stack e allocatore JSON. Sono valori ricavati dalle costanti, non misure dell'heap sul dispositivo.

Dimensionare il messaggio per una sola attivazione massima e i metadati correnti lo porterebbe a `461.261` byte, liberando **460.992 byte** rispetto alla riserva attuale. Prima di applicarlo occorre verificare che tutti gli output effettivi rientrino nel massimo dichiarato e che nessun altro percorso usi quel buffer diversamente.

### 4.2 Arena e dati conservati per FOMO

**Intervento:** misurare l'arena necessaria per ciascun sott modello usando gli strumenti disponibili nella versione TFLM adottata; scegliere una dimensione che copra il caso peggiore con un margine documentato. Se si ricostruisce un solo interprete alla volta, l'arena può essere riutilizzata sequenzialmente.

Anche il buffer `lastMultiOutputLayerData` va dimensionato sugli output effettivamente conservati, verificando gli indici FOMO `{16, 34, 43}` e la durata delle dipendenze. Il buffer di lavoro generale deve coprire il massimo fra input iniziale e attivazioni gestite, non soltanto una dimensione scelta empiricamente.

Registrare heap libero, minimo disponibile e blocco libero più grande, distinguendo RAM interna e PSRAM. La sola memoria libera totale non basta a diagnosticare la frammentazione.

### 4.3 Collocazione dei dati e ricezione MQTT

I grandi buffer sono già allocati una volta nel setup: il miglioramento non consiste nel rimuovere allocazioni che non avvengono nel ciclo. La ricezione MQTT, invece, usa `new char[total + 1]` per ogni messaggio e nel ramo con indice troppo grande esce senza liberarlo.

**Intervento:** usare un buffer di controllo con capacità limitata e riutilizzabile, validare `total`, `index` e `len`, e definire cosa accade se arriva una nuova sequenza prima che la precedente sia completa. Ogni uscita deve rilasciare o ripristinare lo stato di ricezione. Dimensionare separatamente i piccoli messaggi di controllo dai grandi payload di inferenza.

Valutare RAM interna per piccoli dati usati spesso e PSRAM per i grandi buffer, lasciando memoria interna sufficiente alla rete e ai task. L'arena attuale da circa 1 MB non va semplicemente trasferita tutta nella RAM interna. La PSRAM usa la cache e grandi accessi possono limitarne le prestazioni: è una motivazione per misurare collocazione e copie, non una prova di rallentamento già osservato in SCIoT. [Riferimento Espressif sulla memoria esterna](https://docs.espressif.com/projects/esp-idf/en/v4.4.6/esp32s3/api-guides/external-ram.html).

## 5. Ridurre il lavoro di supporto all'inferenza

### 5.1 Selezione numerica del modello

Per ogni layer viene costruita una `String` come `"layer_17"`. La macro `LOAD_LAYER()` confronta il nome con quelli dei 59 layer mediante una sequenza di `if`.

**Intervento:** sostituire questa ricerca con una tabella costante di puntatori ai modelli, indicizzata dall'intero già disponibile. Verificare il limite prima dell'accesso e mantenere i modelli nella memoria di sola lettura prevista dalla build, evitando copie in RAM dei pesi.

Il beneficio atteso riguarda lavoro di selezione e oggetti temporanei; va confrontato con il tempo di inferenza per capire quanto incida realmente.

### 5.2 Resolver e preparazione dell'interprete

L'`AllOpsResolver` locale viene costruito per ogni layer insieme all'interprete; anche `AllocateTensors()` viene ripetuto a ogni passaggio.

**Interventi progressivi:**

1. Dare al resolver una durata controllata e riutilizzarlo.
2. Inventariare gli operatori effettivamente presenti negli artefatti inclusi e valutare un `MicroMutableOpResolver` che registri solo quelli necessari.
3. Misurare costruzione e allocazione separatamente da `Invoke()`.
4. Se quei costi sono rilevanti, sperimentare contesti conservati solo con memoria indipendente e un bilancio RAM esplicito.

Un resolver ristretto può contribuire a ridurre il firmware, ma la differenza effettiva dipende anche dal linker e dalle librerie. Non è garantita un'accelerazione dei kernel. Conservare tutti i 59 interpreti con arene separate potrebbe invece superare la memoria disponibile: non è la soluzione predefinita.

Raggruppare più layer in nuovi sott modelli potrebbe ridurre ricostruzioni e copie, ma richiede rigenerazione degli artefatti e verifica della corrispondenza con lo split sul server. È quindi escluso dalla prima fase limitata al firmware.

### 5.3 Log nel percorso frequente

Le stampe complete dei tensori sono già protette da `DEBUG`, ma rimangono messaggi incondizionati per caricamento, allocazione, layer e frame, spesso con concatenazioni di `String`.

**Intervento:** introdurre livelli di log e un profilo di misura con diagnostica minima; evitare concatenazioni ripetute e stampare riepiloghi periodici. Confrontare lo stesso input con log attivi e ridotti, perché il tempo osservato può includere attese della seriale.

Non eliminare errori e contatori necessari a interpretare i risultati: ridurre le stampe frequenti deve migliorare la misura, non nascondere i fallimenti.

## 6. Ottimizzare preparazione dell'immagine e copie

### 6.1 Conversione RGB565

`getModelDataForPrediction()` scambia i byte, estrae i tre canali e normalizza ogni pixel con divisioni per `31.0` e `63.0`. I letterali senza suffisso sono di tipo `double` nel sorgente; il codice macchina effettivo dipende dalle ottimizzazioni del compilatore.

**Intervento:** valutare costanti `float`, moltiplicazioni per reciproci oppure piccole tabelle con i 32 e 64 valori normalizzati. Misurare prima di introdurre tabelle: il compilatore potrebbe avere già semplificato parte del lavoro.

La trasformazione deve preservare ordine dei canali, ordine dei byte e normalizzazione attesa. Una modifica aritmetica può cambiare gli ultimi bit: confrontare il tensore preparato e il risultato dell'inferenza con tolleranze dichiarate. Controllare inoltre formato, dimensioni e lunghezza del frame prima della conversione.

### 6.2 Copie fra buffer e tensori

Ogni layer riceve una copia dal buffer di lavoro e restituisce un output che viene ricopiato nello stesso buffer. Le attivazioni FOMO possono richiedere un'ulteriore conservazione.

**Intervento:** contare byte e tempo di ogni copia. Valutare la scrittura dell'immagine preparata direttamente nell'input del primo interprete e la serializzazione dell'ultimo output mentre è ancora valido, quando il ciclo di vita lo consente.

Non eliminare le copie fra layer senza un piano di validità dei dati: ricostruire l'interprete sulla stessa arena può sovrascrivere proprio l'output da passare al layer successivo. Un doppio buffer può essere utile soltanto se riduce il lavoro misurato e il suo costo in memoria è accettabile. Le attivazioni necessarie ai rami devono restare disponibili fino al loro ultimo utilizzo.

## 7. Gestire la comunicazione senza cambiare il protocollo

### 7.1 Proprietà dei buffer e invii in corso

Il frame viene passato al trasporto e restituito alla camera a fine ciclo; `output_message` viene riutilizzato nelle inferenze successive. Prima di anticipare il rilascio del frame o sovrapporre le fasi bisogna verificare, sulla versione esatta di ciascuna libreria, se l'invio copia i dati o conserva un riferimento. Il solo fatto che un'API sia asincrona non dimostra un difetto, ma rende necessaria questa verifica.

Nel client HTTP le funzioni di invio non fanno partire una nuova richiesta se la precedente è occupata, senza restituire al chiamante un esito che renda visibile il mancato invio.

**Intervento:** esporre esiti distinti per invio accettato, occupato e fallito; contare i casi e limitare i payload in attesa. Se una libreria mantiene il puntatore, il buffer deve restare immutato fino al completamento o alla cancellazione. Le conferme di trasporto non vanno interpretate come conferme di inferenza del server.

### 7.2 Connessione e callback

Nel client MQTT esiste un timer che forza la disconnessione ogni 600.000 ms. Può essere utile in un esperimento di resilienza, ma introduce riconnessioni periodiche nel funzionamento ordinario. Il codice richiama inoltre l'attesa NTP da callback Wi-Fi e MQTT; `timeConfiguration()` può continuare a tentare senza una scadenza applicativa complessiva.

Nei tre client diverse funzioni vengono adattate a callback di timer mediante `reinterpret_cast`, anziché dichiarare un wrapper con la firma richiesta.

**Intervento:**

- Rendere la disconnessione forzata un'opzione esplicita per le prove di recupero.
- Usare wrapper con firma corretta per i timer e demandare il lavoro a un contesto applicativo.
- Gestire NTP con timeout e stato esplicito, evitando di bloccare callback di rete; mantenere le durate locali sul contatore monotono.
- Se l'orologio non è valido, non presentare i timestamp al server come sincronizzati: il server attuale li usa per stimare la rete.
- Centralizzare le riconnessioni con intervalli limitati e crescenti, evitando tentativi ripetuti dentro ogni funzione di invio WebSocket.
- Nel client HTTP verificare anche l'esito della risposta prima di considerare riuscita la registrazione.

Le callback dei timer software devono essere brevi e non bloccanti, perché condividono il task di servizio. [Riferimento FreeRTOS](https://www.freertos.org/Documentation/02-Kernel/02-Kernel-features/05-Software-timers/01-Software-timers).

### 7.3 Stato condiviso e immagine originale

Punto di split e stato della connessione sono modificati da callback e letti nel percorso di inferenza. Usare una copia coerente dello split all'inizio di ogni inferenza e trasferire gli aggiornamenti tramite una coda o una sincronizzazione breve. Aggiungere soltanto `volatile` non definisce una sincronizzazione sufficiente. Evitare accessi contemporanei allo stesso client di rete da contesti diversi se la libreria non li supporta.

I tre firmware inviano anche il frame RGB565 da 18.432 byte. Dal codice del server l'immagine alimenta il salvataggio dell'input, mentre il completamento dell'inferenza riceve le attivazioni dal messaggio dei risultati.

Un'opzione firmware per inviare l'immagine solo a fini diagnostici è quindi una prova possibile senza cambiare il formato dei messaggi, previa verifica del flusso completo. Va documentato che visualizzazione e file dell'immagine potrebbero non aggiornarsi. Nei confronti di prestazioni la frequenza di invio deve essere identica, oppure dichiarata come variabile dell'esperimento. Non va confusa con la compressione delle attivazioni.

## 8. Camera, esecuzione e watchdog

La camera usa due framebuffer in PSRAM e il frame resta acquisito durante l'intera inferenza. WebSocket esegue `poll()` tra le fasi del `loop()`, senza richiamarlo nel ciclo dei layer.

**Interventi progressivi:**

1. Dopo aver verificato il contratto di invio, restituire il frame appena conversione e uso da parte del trasporto sono terminati.
2. Misurare se uno o due framebuffer siano più adatti all'obiettivo: memoria, frequenza di elaborazione e anzianità del frame sono metriche diverse.
3. Servire la connessione WebSocket tra layer, fuori dall'accesso a tensori temporanei, se le misure mostrano ritardi di gestione. Ciò non risolve un singolo `Invoke()` molto lungo.
4. Solo se necessario, separare comunicazione e inferenza in task con una coda limitata e proprietà esplicita dei buffer. Decidere se attendere o scartare nuovi frame quando il dispositivo è occupato, registrando gli scarti.

La separazione in task può aumentare la sovrapposizione delle fasi, ma costa stack, sincronizzazione e memoria. Usare due core non dimezza automaticamente la latenza: camera, rete e inferenza possono contendere le stesse risorse.

Il watchdog viene registrato dentro `runNeuralNetworkLayer()` e alimentato intorno a `Invoke()`. Verificarne registrazione e copertura per il task effettivo e misurare il tempo massimo dei layer. Un'operazione più lunga della scadenza può causare reset anche se viene alimentato subito prima e subito dopo. La soluzione va scelta sulla durata osservata, senza disabilitare indiscriminatamente il watchdog.

## 9. Build ripetibile e codice comune

I tre `platformio.ini` usano `platform = espressif32` senza una versione esatta e più dipendenze ammettono aggiornamenti. La definizione della scheda viene descritta nei README come un file da aggiungere all'installazione PlatformIO dell'utente.

**Intervento:** fissare una combinazione verificata di piattaforma, framework e librerie; rendere disponibile nel repository la definizione della scheda necessaria. Registrare configurazione di CPU, flash, PSRAM e compilatore effettivamente usata. Questa ripetibilità permette di attribuire i cambiamenti di prestazione alle modifiche del firmware.

Mantenere profili di diagnostica e misura, controllare dal rapporto di build occupazione di RAM e flash e confrontare eventuali cambiamenti delle ottimizzazioni del compilatore. Evitare flag aggressivi come `fast-math` senza una verifica numerica: possono modificare il comportamento in virgola mobile.

Estrarre in codice comune preparazione degli input, esecuzione dei layer, gestione dei buffer, misure e serializzazione. Lasciare ai tre adattatori i dettagli di MQTT, HTTP e WebSocket. Si può farlo restando in PlatformIO con Arduino; la riduzione delle duplicazioni migliora la manutenzione e la coerenza, senza garantire da sola un firmware più veloce.

## 10. Sequenza di lavoro e criteri di verifica

1. **Scegliere una variante iniziale.** Usare il trasporto impiegato nelle prove, documentare scheda, modello e build. Conservare il sorgente originale come riferimento storico; le sue misure possono essere compromesse dai difetti P0.
2. **Creare una base corretta.** Risolvere durata degli oggetti, errori, limiti e serializzazione. Verificare i risultati a split iniziale, intermedi validi e finale; controllare numericamente anche i percorsi FOMO coinvolti.
3. **Raccogliere il profilo.** Separare le fasi, registrare memoria, log e invii. Usare input RGB565 salvati e ripetibili per isolare le differenze di calcolo; provare separatamente la camera reale.
4. **Applicare modifiche isolate.** Prima buffer, log e selezione numerica; poi resolver, preparazione dei pixel, copie e collocazione della memoria, secondo il profilo rilevato.
5. **Verificare il funzionamento prolungato.** Provare messaggi frammentati o invalidi, NTP indisponibile, perdita di Wi-Fi, server lento e invii occupati. Controllare recupero, memoria e assenza di risultati presentati come validi dopo errori.
6. **Valutare la concorrenza.** Introdurre task o sovrapposizione solo se resta un'attesa significativa e il bilancio di memoria lo consente.
7. **Portare le correzioni agli altri trasporti.** Confrontare le tre build usando lo stesso motore e le stesse condizioni applicative.

Per ogni confronto mantenere fissi modello, input, split, impostazioni della scheda, log e invio dell'immagine. Separare avvio e regime, annotare il numero di campioni e riportare mediana, percentile 95 e casi peggiori delle durate locali, insieme a inferenze completate al secondo, errori, reset e memoria minima.

Una scheda sintetica per ciascuna modifica può contenere:

| Voce | Dato da registrare |
|---|---|
| Identificazione | Commit, variante, hardware e configurazione di build |
| Scenario | Input, split, numero di prove e condizioni della connessione |
| Prestazione | Tempi per fase e frequenza di elaborazione |
| Risorse | RAM interna, PSRAM, blocco libero massimo e dimensione del firmware |
| Comunicazione | Byte applicativi, invii accettati, occupati, falliti e riconnessioni |
| Correttezza | Differenza numerica rispetto al riferimento e verifica del pacchetto |

Il traffico applicativo può essere contato sul dispositivo; il traffico reale sul collegamento e la latenza completa fino al risultato del server richiedono osservazioni ulteriori. Un calo del tempo di `Invoke()` non basta a dimostrare un miglioramento dell'intero sistema.

## 11. Interventi esclusi dalla fase limitata al firmware

Non rientrano in questa proposta quantizzazione INT8, compressione delle attivazioni, nuovo protocollo, modifica dell'algoritmo di split, nuovi punti di taglio o rigenerazione dei sott modelli. Richiedono interventi o verifiche anche fuori dal firmware.

Una migrazione a ESP-IDF può essere valutata successivamente se emergono limiti concreti di configurazione o integrazione. Non elimina automaticamente copie, allocazioni o difetti del codice applicativo. Le ottimizzazioni qui descritte possono iniziare nei progetti Arduino/PlatformIO presenti nella repository.

## 12. Riferimenti al codice e limiti dell'analisi

- [Firmware MQTT](src/client/esp32-s3-eye-mqtt/src/main.cpp): `loadNeuralNetworkLayer()`, `runNeuralNetworkLayer()`, `processIncomingMessage()`, timer, setup e ciclo principale.
- [Firmware HTTP](src/client/esp32-s3-eye-http/src/main.cpp): stessi percorsi di inferenza; invii condizionati dallo stato delle richieste e callback di registrazione e split.
- [Firmware WebSocket](src/client/esp32-s3-eye-websocket/src/main.cpp): stessi percorsi di inferenza; riconnessioni nelle funzioni di invio e posizione delle chiamate a `poll()`.
- [Costanti MQTT](src/client/esp32-s3-eye-mqtt/src/conf.template.h), [HTTP](src/client/esp32-s3-eye-http/src/conf.template.h) e [WebSocket](src/client/esp32-s3-eye-websocket/src/conf.template.h): dimensioni di input, arena, buffer e numero di layer.
- [Selezione dei modelli](src/client/esp32-s3-eye-mqtt/src/model_layers/layers.h): macro `LOAD_LAYER()` e header inclusi.
- Configurazioni PlatformIO [MQTT](src/client/esp32-s3-eye-mqtt/platformio.ini), [HTTP](src/client/esp32-s3-eye-http/platformio.ini) e [WebSocket](src/client/esp32-s3-eye-websocket/platformio.ini).
- [Parser dei risultati](src/server/communication/request_handler.py) e [server WebSocket](src/server/communication/websocket_server.py): consultati per conservare compatibilità e distinguere il ruolo dell'immagine da quello delle attivazioni.

I riferimenti ai sorgenti supportano i riscontri statici. Non dimostrano velocità ottenibili, percentuali di risparmio temporale o stabilità sull'hardware. Le dimensioni riportate derivano dalle configurazioni template incluse; configurazioni locali diverse richiedono un nuovo calcolo. Le API e gli strumenti di misura da usare vanno verificati sulla combinazione di framework e librerie effettivamente fissata per le prove.
