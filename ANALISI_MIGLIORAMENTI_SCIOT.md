# SCIoT: miglioramenti, supporto ad altre reti neurali e WebSocket

Documento creato il 17 ottobre 2026 per raccogliere l'analisi discussa in chat il 15 ottobre 2026.

**Obiettivo:** individuare come migliorare SCIoT e renderlo utilizzabile con reti che svolgono compiti diversi dalla rilevazione di oggetti con FOMO, approfondendo anche il suggerimento di usare WebSocket per la comunicazione.

L'analisi iniziale riguarda il checkout al commit `0cfeb9b`. I riscontri principali nel codice sono stati ricontrollati durante la stesura. Le proposte non costituiscono modifiche già implementate né una dimostrazione di benefici su ESP32.

## 1. Valutazione generale

La base di SCIoT è riutilizzabile: il dispositivo esegue una parte della rete, trasmette le attivazioni intermedie e il server completa l'inferenza. Tuttavia, acquisizione, preparazione degli input, configurazione e protocollo sono molto legati alla telecamera e al modello FOMO.

Per supportare altre applicazioni occorre separare tre responsabilità:

1. Acquisire e preparare i dati: immagini, audio o campioni di sensori.
2. Eseguire e distribuire il calcolo della rete neurale.
3. Interpretare l'uscita: classi, rilevamenti, valori numerici o punteggi di anomalia.

Il motore di split dovrebbe lavorare con tensori descritti esplicitamente, mentre preparazione e interpretazione dei dati dovrebbero dipendere dal modello scelto.

## 2. Separare il modello dal meccanismo di split

### Riscontri nel codice

- L'inizializzazione del server parte da un'immagine PNG e applica una normalizzazione per immagini.
- Il caricamento dei modelli e dei sott modelli usa percorsi legati a `test_model`.
- La configurazione pubblica seleziona FOMO 96 × 96.
- Il firmware prepara immagini RGB a partire dal formato RGB565 della telecamera.

Cambiare soltanto il nome del modello nel file YAML non basta quindi a introdurre un'applicazione diversa.

Riferimenti: [inizializzazione edge](src/server/edge/edge_initialization.py), [gestione dei modelli](src/server/models/model_manager.py), [configurazione dei modelli](src/server/models/model_manager_config.py), [configurazione server](src/server/settings.yaml), [firmware MQTT](src/client/esp32-s3-eye-mqtt/src/main.cpp).

### Proposta

Definire una configurazione per ogni modello con:

- Identificativo, versione e percorsi degli artefatti.
- Forma e tipo numerico degli input e degli output.
- Preparazione dei dati e normalizzazione.
- Etichette e interpretazione del risultato.
- Punti di split consentiti e tensori richiesti a ogni confine.

La camera, il microfono e i sensori avrebbero ciascuno la propria preparazione dei dati. Il motore di inferenza riceverebbe i tensori già preparati.

## 3. Gestire reti con rami e connessioni residue

### Problema

Una rete non è necessariamente una catena in cui ogni layer usa soltanto l'uscita del precedente. Alcune connessioni conservano un risultato precedente e lo riutilizzano più avanti, per esempio in una somma tra due rami.

Il generatore di sott modelli contempla layer con più ingressi, ma il protocollo attuale trasporta un solo tensore di attivazioni. Il firmware contiene inoltre una gestione specifica per FOMO con indici scritti direttamente nel codice, come `{16, 34, 43}`.

Se una connessione attraversa il punto di split, il server potrebbe aver bisogno di un'attivazione precedente che il dispositivo non ha trasmesso. Il supporto a più ingressi del singolo layer non risolve da solo questo problema.

Riferimenti: [generazione dei sott modelli](src/server/models/model_split.py), [esecuzione sul server](src/server/edge/edge_initialization.py), [parser dei messaggi](src/server/communication/request_handler.py), [firmware MQTT](src/client/esp32-s3-eye-mqtt/src/main.cpp).

### Proposta

Analizzare il grafo e individuare, per ogni taglio, tutti i tensori necessari per proseguire. Il protocollo dovrebbe poter trasportare più tensori identificati esplicitamente.

Un primo passo più contenuto consiste nell'ammettere soltanto i tagli che richiedono un singolo tensore, escludendo automaticamente quelli incompatibili. Il supporto generale ai rami può arrivare in seguito.

## 4. Generalizzare i messaggi e supportare INT8

Il parser interpreta le attivazioni come `float32`; anche il firmware usa buffer di `float`. Questa assunzione limita l'introduzione di modelli quantizzati e formati diversi.

Un messaggio più generale dovrebbe descrivere:

- Versione del protocollo e tipo del messaggio.
- Dispositivo, sessione, identificativo e versione del modello.
- Punto di split e numero di sequenza.
- Identificativo, forma, tipo numerico e lunghezza di ogni tensore.
- Parametri di quantizzazione, quando necessari.
- Codifica del payload ed eventuale riferimento temporale.

La quantizzazione INT8 porta da quattro byte a uno per elemento rispetto a `float32`. Questo rapporto riguarda i valori del tensore, non garantisce una riduzione di quattro volte del traffico totale o della latenza.

Servono calibrazione e verifica dell'accuratezza. Se si quantizzano sottoreti separate, l'uscita della prima e l'ingresso della seconda devono usare rappresentazioni compatibili o una conversione esplicita.

Riferimenti: [parser](src/server/communication/request_handler.py), [gestione dei sott modelli](src/server/models/model_manager.py), [documentazione sulla quantizzazione intera](https://developers.google.com/edge/litert/conversion/tensorflow/quantization/post_training_integer_quant).

## 5. Ottimizzare i dati effettivamente trasmessi

### Immagine originale e attivazioni

I tre client inviano sia l'immagine originale sia il risultato intermedio della rete. Rendere opzionale l'immagine originale permetterebbe di conservarla per visualizzazione e debug senza inviarla necessariamente a ogni inferenza.

Nel profilo salvato in [layer_sizes.json](src/server/layer_sizes.json) sono presenti 59 layer. L'attivazione più grande misura **460.992 byte**, mentre un frame RGB565 96 × 96 misura **18.432 byte**.

Sono dimensioni del profilo incluso nel repository, non misure raccolte su hardware durante questa analisi. Mostrano che eseguire più layer sul dispositivo non garantisce una riduzione del traffico: alcuni layer espandono la rappresentazione.

### Compressione delle differenze tra attivazioni

L'idea discussa consiste nel mantenere un riferimento condiviso tra dispositivo e server e inviare una codifica compressa delle differenze rispetto al riferimento. Il server ricostruisce il tensore prima di completare l'inferenza.

Occorre prevedere:

- Un invio completo iniziale.
- Riferimenti identificati e sincronizzati.
- Ripristino dopo disconnessione o riferimento mancante.
- Invalidazione del riferimento quando cambiano modello, punto di split o formato del tensore.
- Stato separato per ogni dispositivo e modello.
- Invio completo quando risulta più conveniente del differenziale.

Calcolare una differenza non riduce da solo il numero di byte: serve una codifica che sfrutti la struttura dei dati. Inoltre, sottrazione e somma in virgola mobile non garantiscono sempre una ricostruzione identica; va dichiarato e verificato se il metodo è senza perdita o con perdita.

Il vantaggio va valutato contando metadati, calcolo aggiuntivo, memoria e qualità del risultato. L'assenza di questa funzione nel percorso applicativo esaminato non dimostra novità scientifica.

**Nota sullo stato locale alla stesura:** è già presente un esperimento separato in [experiments/activation_compression](experiments/activation_compression/README.md). Il suo README documenta prove su PC e precisa che il formato sperimentale non è integrato nel protocollo SCIoT. Questo documento raccoglie la discussione architetturale; i risultati di quell'esperimento vanno consultati nella relativa documentazione e non costituiscono una validazione su ESP32 o rete reale.

La selezione dei frame da elaborare è una direzione distinta, già annotata in [IDEE_DA_ESPLORARE.md](IDEE_DA_ESPLORARE.md).

## 6. Rendere più affidabile la scelta dello split

L'algoritmo stima il costo come somma di calcolo sul dispositivo, trasferimento delle attivazioni e calcolo sul server.

Nella versione esaminata, l'esecuzione interamente sul server viene valutata ma esclusa dalla selezione del punto migliore. Durante la chat, un controllo isolato con costi sintetici ha mostrato una scelta da circa 10 secondi pur avendo un costo di solo calcolo sul server di 0,03 secondi. Questo controllo evidenzia l'esclusione del candidato: un confronto completo deve includere anche il costo di invio dell'input al server.

Riferimento: [algoritmo di offloading](src/server/offloading_algo/offloading_algo.py), in particolare `static_offloading()`.

Miglioramenti proposti:

- Confrontare esecuzione locale, sul server e suddivisa con costi coerenti.
- Escludere tagli incompatibili con memoria, operatori o dipendenze del grafo.
- Considerare il carico del server e la presenza di altri dispositivi.
- Filtrare le misure di rete per evitare cambiamenti continui dovuti al rumore.
- Cambiare punto di split soltanto quando il beneficio atteso supera una soglia.
- Considerare scadenze temporali, se richieste dall'applicazione.
- Usare le dimensioni realmente trasmesse, includendo codifica e metadati.

Una rete molto piccola potrebbe risultare più conveniente interamente locale. Lo split va giustificato dalle misure.

## 7. Altre applicazioni e reti candidate

Le famiglie seguenti sono candidate da valutare, non modelli già compatibili e validati con SCIoT.

| Compito | Rete candidata | Estensione necessaria |
|---|---|---|
| Classificare immagini | Piccola CNN | Preparazione immagini configurabile, etichette e probabilità |
| Riconoscere parole o rumori | Piccola CNN su caratteristiche audio | Acquisizione audio, finestre temporali, spettrogramma o MFCC |
| Riconoscere gesti o vibrazioni | MLP o CNN temporale | Buffer dei campioni, frequenza di acquisizione e normalizzazione |
| Individuare anomalie | Piccolo autoencoder | Errore di ricostruzione, soglia e valutazione dei falsi allarmi |
| Stimare una grandezza numerica | MLP di regressione | Output numerici, unità di misura e metriche dell'errore |

Per ogni modello concreto vanno verificati conversione, operatori disponibili, memoria e punti di split. La disponibilità del formato TensorFlow Lite non garantisce che qualunque rete possa essere eseguita sul microcontrollore.

Come primo ampliamento era stata proposta una piccola rete per sensori oppure un autoencoder, mantenendo FOMO come riferimento. Sarebbe un modo concreto per verificare la generalizzazione di input e output; non è una decisione già presa né sostituisce l'esplorazione della compressione.

Riferimenti: [riconoscimento audio con Edge Impulse](https://docs.edgeimpulse.com/docs/tutorials/end-to-end-tutorials/audio/audio-classification), [runtime e limiti sui microcontrollori](https://developers.google.com/edge/litert/microcontrollers/overview).

## 8. WebSocket per migliorare la comunicazione

### Cosa esiste già

WebSocket è già implementato nel [client ESP32](src/client/esp32-s3-eye-websocket/src/main.cpp) e nel [server](src/server/communication/websocket_server.py). Il client invia dati binari e riceve il nuovo punto di split.

Il lavoro consiste quindi nel verificare e migliorare questa implementazione e confrontarla con gli altri trasporti.

### Benefici possibili e limiti

WebSocket mantiene una connessione aperta e permette lo scambio di messaggi nelle due direzioni. Può ridurre il lavoro associato a richieste HTTP ripetute e consentire al server di inviare aggiornamenti senza attendere una nuova richiesta del dispositivo.

Il guadagno rispetto a HTTP dipende però anche dal riuso delle connessioni e dal numero di richieste per inferenza. MQTT usa già una connessione persistente: rispetto a MQTT, il possibile beneficio del WebSocket diretto riguarda anche l'assenza del passaggio attraverso il broker. Non è garantito che sia più veloce.

WebSocket non riduce di per sé la dimensione delle attivazioni. Trasporto, quantizzazione e compressione intervengono su aspetti diversi e possono essere combinati.

Riferimenti: [protocollo WebSocket, RFC 6455](https://www.rfc-editor.org/rfc/rfc6455), [specifica MQTT 3.1.1](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html).

### Problemi da risolvere o verificare

1. **Tipo del messaggio esplicito.** Il server riconosce un'immagine dalla lunghezza esatta di `18432` byte. Questo criterio è ambiguo: un altro payload della stessa dimensione verrebbe classificato come immagine. Serve un campo che distingua registrazione, input, attivazioni e controllo.
2. **Gestione della comunicazione durante l'inferenza.** Il client chiama `poll()` tra le fasi, ma non durante il ciclo di esecuzione dei layer. Sul server l'inferenza viene eseguita direttamente nel gestore asincrono. Sono possibili fonti di ritardo da misurare e, se necessario, separare dalla gestione della connessione.
3. **Immagine originale opzionale.** Anche il client WebSocket invia il frame oltre alle attivazioni.
4. **Ripristino della sessione.** Riconnessione, conferma dello stato del modello e recupero del riferimento differenziale devono essere definiti esplicitamente.

### Esperimento proposto

Confrontare inizialmente il trasporto attuale e WebSocket usando lo stesso modello, gli stessi input, lo stesso punto di split e gli stessi payload. Rendere identiche anche le impostazioni di invio delle immagini originali e documentare le garanzie di consegna dei trasporti confrontati.

Successivamente confrontare WebSocket senza compressione e WebSocket con compressione. Questo permette di attribuire separatamente i benefici al trasporto e alla riduzione dei dati.

Misurare byte effettivi trasmessi, latenza completa e sua variabilità, per esempio mediana e percentili 95 e 99, oltre a memoria, costo del codec e comportamento dopo una riconnessione. Distinguere i byte applicativi dal traffico comprensivo degli strati di rete.

## 9. Problemi di base da correggere prima di ampliare il sistema

- **Durata di vita dell'interprete nel firmware.** In `loadNeuralNetworkLayer()` il puntatore globale viene assegnato all'indirizzo di un oggetto locale. Il nome `static_interpreter` non lo rende statico: l'oggetto cessa di esistere al ritorno della funzione. Il problema compare nei tre client ed è un difetto rilevabile dal sorgente; le conseguenze sul dispositivo non sono state misurate in questa chat.
- **Duplicazione del motore di inferenza.** Conviene condividere la parte comune del firmware e mantenere separati i trasporti, così le correzioni non devono essere replicate tre volte.
- **Stato condiviso sul server.** Punto di split e file delle statistiche non sono isolati per dispositivo e modello. Il supporto a più client richiede sessioni distinte e una gestione coerente degli accessi.
- **Test più significativi.** Servono confronti tra inferenza completa e suddivisa, round-trip dei messaggi e verifiche del ripristino dei riferimenti. Nel test attuale dell'offloading vengono passati i tempi del dispositivo anche come tempi del server e l'asserzione non controlla esattamente il taglio atteso.

Riferimenti: [firmware MQTT](src/client/esp32-s3-eye-mqtt/src/main.cpp), [firmware HTTP](src/client/esp32-s3-eye-http/src/main.cpp), [firmware WebSocket](src/client/esp32-s3-eye-websocket/src/main.cpp), [gestione delle richieste](src/server/communication/request_handler.py), [percorsi condivisi](src/server/commons.py), [test dell'offloading](tests/test_offloading_algo/test_offloading_algo.py).

## 10. Ordine di lavoro proposto e limiti delle verifiche

1. Correggere i difetti di base e verificare la corrispondenza tra inferenza completa e suddivisa.
2. Definire messaggi espliciti e punti di split validi.
3. Misurare il traffico attuale e rendere opzionale l'immagine originale.
4. Confrontare i trasporti in condizioni equivalenti, approfondendo WebSocket.
5. Valutare la compressione sul dispositivo e integrarla soltanto se il risparmio compensa calcolo e memoria.
6. Introdurre un secondo compito e verificare che il motore di split non richieda modifiche specifiche per quel compito.
7. Estendere la gestione a più dispositivi e, quando necessario, a tagli con più tensori.

Questa è una proposta di priorità tecniche, non una modifica alla scaletta già concordata. Il contesto del tirocinio è raccolto in [SCALETTA_TIROCINIO.md](SCALETTA_TIROCINIO.md).

Nell'analisi iniziale della chat sono stati controllati sintatticamente 36 sorgenti Python ed eseguito un controllo isolato dell'algoritmo di offloading. In quella fase mancava TensorFlow nell'ambiente esaminato: non era stata eseguita una validazione completa del server o del firmware.

Le successive prove locali di compressione sono documentate separatamente. Né l'analisi statica né prove Keras sul PC dimostrano prestazioni su ESP32, riduzione del traffico reale, accuratezza della detection o vantaggi di WebSocket. Questi risultati richiedono misure dedicate sul sistema completo.
