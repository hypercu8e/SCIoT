# Tirocinio SCIoT — scaletta e contesto per ripartire

Aggiornato il 18 ottobre 2026, con baseline senza perdita del 15 ottobre, prima
prova con perdita del 17, prova TCP e verifiche INT8/16×8 su PC del 18.
Cronologia: [diario](DIARIO_TIROCINIO.md).

## Punto di ripresa

**19 ottobre — correzioni firmware:** applicati ai tre client float32 i controlli
di interprete/tensori/allocazioni e la serializzazione condivisa. Nei template
il buffer messaggio riserva 460.992 byte in meno. Build HTTP/MQTT/WebSocket riusciti;
1.170 esecuzioni di layer Micro sul PC, 33.363.072 valori identici al riferimento
TFLite e pacchetti verificati col parser server. [Report](experiments/firmware_fixes_2026-10-19/README.md).
Questi test non certificano camera, rete o prestazioni ESP32. Per lo stato attuale
dei firmware questa nota aggiorna i riscontri storici ancora elencati più sotto.

**19 ottobre — preparazione in attesa della scheda:** l'utente chiederà al
professore una ESP32-S3-EYE in prestito il 20 ottobre; se non disponibile valuterà
l'acquisto. Nel frattempo completata la [preparazione INT8](experiments/activation_compression/esp32_prep_2026-10-19/README.md):
taglio del binario già quantizzato, equivalenza byte per byte sui 146 frame,
tre vettori fissi e tre firmware compilati. [Guida hardware](experiments/esp32_int8_firmware/README.md).
Prossimo passo: caricare `prefix`, poi `full` e `suffix`, verificare i log e misurare
memoria/tempi. Non sono ancora risultati hardware o integrazione SCIoT.
Nel runtime TensorFlowLite_ESP32 1.0.0 manca il percorso INT16 della depthwise
convolution necessario al nostro 16×8; occorre aggiornare/estendere il runtime
prima di provare quella variante. INT8 resta da validare sulla scheda.

Per iniziare dalla visione d'insieme: [recap del lavoro sul fork](RECAP_LAVORO_FORK.md).

La trascrizione ragionata di spiegazioni, scelte, prove e limiti della chat è in
[ANALISI_COMPRESSIONE_ATTIVAZIONI.md](ANALISI_COMPRESSIONE_ATTIVAZIONI.md), con le
istruzioni per trasferire il lavoro su un'altra macchina.

È stato scelto un FOMO pubblico come candidato sperimentale, configurato l'ambiente
e verificato uno split Keras su PC. Il primo confronto senza perdita è completato:
XOR con riordino dei byte e zlib riduce i byte del 14,96% rispetto al raw a 5 fps;
il beneficio temporale rispetto al completo con lo stesso riordino è 5,71%, e
scende a 2,78% a 1 fps. Sono misure su un video e uno split, non su ESP32 o rete reale.

È ora completata anche una prima prova con perdita controllata a griglia uniforme:
a 5 fps, passo 0,001, risparmio sul raw del 40,61% per l'indipendente e del 48,66%
per il temporale; vantaggio temporale aggiuntivo 13,57% a identica ricostruzione.
Nessuna cella cambiata a soglia 0,5 sul video, senza una valutazione su annotazioni.
Report: [lossy_2026-10-17](experiments/activation_compression/lossy_2026-10-17/README.md).
La convenienza sull'hardware resta aperta.

Completata il 18 ottobre anche la [prova client–server TCP su PC](experiments/activation_compression/tcp_2026-10-18/README.md):
replay delle attivazioni, suffisso Keras in processo separato, raw/indipendente/
temporale e nuova sessione dopo riconnessione. Non è integrazione SCIoT né replica
del DPCM/dead-zone di Shiba et al.; sul loopback si risparmiano byte ma aumentano
i tempi. Il vantaggio temporale sull'indipendente è 13,56% nel flusso in salita.

Completata anche la [verifica INT8 su PC](experiments/activation_compression/int8_2026-10-18/README.md):
file TFLite da 84.292 a 57.088 byte, conversione integer-only ed esecuzione desktop
riuscite. Su 98 frame non usati nei 48 di calibrazione cambiano 25 celle a soglia
0,5 (11 perse, 14 introdotte; 99 celle oggetto nel riferimento). Non è una
configurazione approvata per qualità o hardware: verificare la calibrazione con
input rappresentativi separati dalla valutazione. Nessun riaddestramento richiesto.

Il successivo [confronto 16×8](experiments/activation_compression/16x8_2026-10-18/README.md)
usa la stessa partizione e gli stessi binari di controllo: 18 celle cambiate a
soglia 0,5, 7 perse e 11 introdotte; file 69.056 byte e confine 9.216 byte.
Migliore fedeltà nelle metriche riportate, con dimensioni maggiori dell'INT8.
Compatibilità INT16 del runtime Micro e costi sulla scheda ancora da verificare.

## Contesto

- Tirocinio interno da 300 ore e possibile tesi triennale in Informatica a UNIMORE, con il prof. Luca Bedogni.
- Il tirocinio è iniziato ufficialmente. Titolo generale concordato: **Multi Device Split Computing**.
- La compressione delle differenze delle attivazioni è una prima direzione da esplorare, non un argomento definitivo. Se non produce benefici, si potranno approfondire altre esigenze del progetto.
- Il professore ha indicato la comunicazione di rete come principale area di ottimizzazione; ha inoltre segnalato il limite del singolo client sul server.
- L'utente sta imparando i concetti: spiegare prima il funzionamento e il motivo delle scelte, distinguendo ipotesi, analisi statica e risultati sperimentali.

## Idea attualmente in esplorazione

Nel flusso esaminato, l'ESP32 esegue i primi layer del modello e invia al server l'intero tensore di attivazioni al punto di split. Il server completa l'inferenza.

La proposta è conservare un riferimento condiviso tra client e server e inviare una codifica compressa delle differenze delle attivazioni tra frame consecutivi. Il server ricostruisce il tensore corrente prima di eseguire i layer rimanenti. Servono invii completi per inizializzare e ripristinare il riferimento.

**Domanda:** il risparmio di traffico compensa il costo aggiuntivo di calcolo e memoria sull'ESP32, mantenendo risultati di detection adeguati?

Distinzioni già chiarite:

- Il tensore contiene i dati; il layer esegue una trasformazione. Le attivazioni sono i risultati intermedi della rete.
- Appiattire un tensore multidimensionale in un vettore non riduce il numero di valori o i byte.
- Anche la semplice sottrazione tra tensori non comprime: occorre codificare le differenze in meno byte, contando anche gli eventuali indici e metadati.
- La quantizzazione riduce la precisione dei valori ed è una scelta distinta dalla codifica delle differenze.
- Saltare del tutto elaborazione e trasmissione dei frame simili è un'altra idea, annotata in [IDEE_DA_ESPLORARE.md](IDEE_DA_ESPLORARE.md). Va ripresa dopo l'esplorazione attuale.

## Fonti e verifiche già svolte

### Repository

Checkout esaminato: `main`, commit `0cfeb9b08ca20dadc754cb38a5201c60991066ba`. La corrispondenza col ramo pubblico era stata verificata durante l'analisi precedente; ricontrollarla prima di assumere che non siano arrivati aggiornamenti.

- Sono presenti client ESP32 MQTT, HTTP e WebSocket.
- I client inviano il tensore completo. Il server non mantiene un riferimento tra frame per ricostruire aggiornamenti differenziali. Il salvataggio delle valutazioni in CSV non svolge questa funzione.
- La configurazione seleziona FOMO 96 × 96. Il firmware pubblico configura tre canali e 59 layer eseguibili.
- Non abbiamo identificato il nome della classe di oggetti del modello originariamente incluso in SCIoT. L'ispezione dei metadati HDF5/Keras e dei 64 sott modelli TFLite non ha trovato etichette; non sono emersi dataset o file di etichette nella cronologia locale consultata. Il nuovo candidato Beer vs. cans è usato separatamente nell'esperimento.
- `src/client/python/` contiene soltanto un README, non un client eseguibile.
- Il README prevede l'importazione di un modello Keras `.h5`; `model_split.py` genera sott modelli TFLite e header C.
- Il supporto dichiarato a TensorFlow Lite non garantisce la compatibilità di qualunque architettura, operazione o punto di split.
- Non è stata eseguita alcuna prova su ESP32. È stato invece configurato `.venv` con Python 3.11.17, TensorFlow/Keras 2.15.0, NumPy 1.26.4 e h5py 3.11.0, installando le dipendenze autorizzate. Sono state eseguite inferenze complete e con split in Keras sul PC, e il confronto dei codec con sei test superati. I tempi del PC non emulano l'ESP32.

### Esperimento isolato completato su PC

- Script e istruzioni: [experiments/activation_compression/README.md](experiments/activation_compression/README.md).
- Modello candidato: [Beer vs. cans FOMO](https://studio.edgeimpulse.com/public/89078/latest), `.h5` scaricato dall'utente. Nessun riaddestramento effettuato. L'ordine delle etichette dell'esportazione resta da confermare.
- Ingresso: 96 x 96 in grigio, float32 normalizzati in [0,1]. La parità pixel per pixel con Studio non è stata verificata.
- Video: `VideoWithCan.mp4`, circa 29,26 secondi; campione di 146 frame a 5 fps e sottoinsieme di 30 a 1 fps.
- Split: `block_2_add`, un solo tensore `24 x 24 x 8`, cioè 18.432 byte per frame. Il file di attivazioni contiene un tensore per ciascun frame campionato.
- Prima parte seguita dalla seconda parte e modello completo: differenza massima osservata 0,0 sui 146 frame.
- Il confronto senza perdita ricostruisce tutti i tensori byte per byte. Include header, checksum, primo completo, rinnovi ogni 5 secondi e ritorno al completo quando il delta è più grande.
- I risultati contano il flusso applicativo sperimentale; escludono overhead e comportamento effettivo dei trasporti di SCIoT. Il codec non è integrato nel framework.
- I file generati in `results/` sono ignorati da Git. Una copia stabile di report, JSON, CSV, metadati e lock è in [baseline_2026-10-15](experiments/activation_compression/baseline_2026-10-15/README.md). Baseline e documenti iniziali risultano nei commit locali `d38a489` e `087fef9`; la prova con perdita è nel commit locale `78eac02`. La prova TCP del 18 ottobre e gli ultimi aggiornamenti documentali sono modifiche locali non ancora in un commit. La corrispondenza col remoto non è stata verificata.

File utili:

- `README.md`
- `src/server/models/model_split.py`
- `src/server/models/model_manager.py`
- `src/server/edge/edge_initialization.py`
- `src/server/communication/request_handler.py`
- `src/server/offloading_algo/offloading_algo.py`
- `src/server/settings.yaml`
- `src/client/esp32-s3-eye-mqtt/src/main.cpp`
- `src/client/esp32-s3-eye-mqtt/src/conf.template.h`

### Paper SCIoT del 2026 — prima lettura completata

**SCIoT: Design and Evaluation of a Split Computing Framework for Collaborative Inference in the IoT**, L. Lamazzi, J. W. Wang, F. Franco, L. Bedogni, CCNC 2026.

- DOI: <https://doi.org/10.1109/CCNC65079.2026.11366406>
- PDF scaricato dall'utente: `/home/gabriele/Downloads/SCIoT_Design_and_Evaluation_of_a_Split_Computing_Framework_for_Collaborative_Inference_in_the_IoT.pdf`
- Testo estratto temporaneo: `/tmp/sciot-paper-2026.txt` (rigenerabile dal PDF).
- **Pagina 3, III-A:** gli autori addestrano con Edge Impulse un FOMO su immagini 96 × 96 in scala di grigi di oggetti di uso quotidiano. Non elencano le classi e non forniscono un dataset identificabile.
- Il percorso descritto comprende raccolta/annotazione, addestramento, valutazione su dati separati, esportazione del modello con pesi in `.h5` e suddivisione in sott modelli.
- **Pagina 3, III-B:** dichiarano una versione del lato dispositivo in Python e il suo utilizzo nella valutazione sperimentale. Tale implementazione non è stata trovata nel checkout pubblico consultato.
- **Pagina 4, IV:** i tempi di riferimento del dispositivo provengono da un ESP-EYE. Gli scenari variano capacità del server, velocità e stabilità della rete. Non confondere questi scenari parametrizzati con misure dirette di tutti i casi su ESP32.
- **Pagina 6, VI:** indicano tra gli sviluppi futuri più dispositivi verso uno stesso server e hardware eterogeneo.
- La trasmissione differenziale delle attivazioni tra frame non è descritta come funzionalità del framework. La compressione compare nella discussione di altri lavori.
- Da chiarire la relazione tra immagini in scala di grigi del paper e configurazione a tre canali del repository.

### Letteratura sull'idea

Il principio non è nuovo. Il riferimento più vicino già consultato è **Delta Coding With Dead-Zone Quantization for Bandwidth-Efficient Split Computing on Video Streams**, Shiba et al., IEEE Access 2026.

- <https://doi.org/10.1109/ACCESS.2026.3690477>
- PDF: <https://da.lib.kobe-u.ac.jp/da/kernel/0100504251/0100504251.pdf>
- Studia differenze quantizzate, riferimento ricostruito e invii completi periodici. Le prove sono su classificazione e simulano la separazione su una macchina; non dimostrano benefici su ESP32 con object detection e rete reale.
- Un nostro eventuale contributo sarebbe implementazione e valutazione su SCIoT, non l'invenzione della codifica differenziale.

Il 18 ottobre abbiamo precisato risultati, metriche e limiti nella
[sezione 9.3 dell'analisi](ANALISI_COMPRESSIONE_ATTIVAZIONI.md#93-risultati-del-paper-e-differenze-dal-nostro-metodo).
Lì sono distinti accordo col modello originale, comprimibilità e tempi di un
sistema distribuito. La prova TCP attuale usa il nostro codec preliminare;
non è una replica del metodo specifico del paper.

## Scaletta aggiornata

### 1. Approfondire le issue

- [ ] Leggere le discussioni pertinenti e collegarle al codice.
- [ ] Dare priorità alla [issue #10](https://github.com/UBICO/SCIoT/issues/10), sui collegamenti condivisi tra layer FOMO e i punti di split.
- [ ] Considerare anche #8 (gestione dei modelli), #11 (stato/registrazione dei client) e #13–16 (comunicazione), secondo necessità.

L'elenco e diversi contenuti delle issue sono già stati consultati; l'analisi sistematica resta da fare.

### 2. Discutere il paper e confrontarlo col repository

- [x] Recuperare e leggere una prima volta il PDF completo.
- [ ] Approfondire insieme algoritmo, esperimenti e grafici.
- [ ] Chiarire quale versione del software è stata usata e se è recuperabile il client Python.

### 3. Scegliere un modello con classi e dati noti

- [x] Selezionare un progetto FOMO pubblico come candidato per la prima prova: Beer vs. cans. Non è una scelta definitiva per l'applicazione su hardware.
- [ ] Conservare etichette, provenienza dei dati, configurazione, preparazione degli input e versione del modello.
- [ ] Verificare presto esportazione e importazione con SCIoT, prima di investire nella raccolta di un dataset esteso.

**Stato:** modello pubblico recuperato e caricato in Keras. Non abbiamo addestrato un nuovo modello né completato l'integrazione del candidato nel firmware/server SCIoT. Edge Impulse serve anche ad addestrare ed esportare; lo split distribuisce l'esecuzione del modello già addestrato.

### 4. Ottenere un'inferenza completa sul PC

- [x] Preparare l'ambiente compatibile col progetto, verificando dipendenze e versioni.
- [x] Elaborare un'immagine nota e spiegare la griglia FOMO. Su `canCoke.jpeg` non è stata ottenuta una rilevazione con soglia 0,5; non è una valutazione complessiva dell'accuratezza.
- [x] Verificare dimensioni, canali, normalizzazione e tipo numerico usati nella prova. Parità esatta con Studio e ordine delle etichette restano da confermare.

### 5. Riprodurre lo split sul PC

- [x] Scegliere un punto compatibile con le dipendenze del grafo: `block_2_add`, un tensore di confine.
- [x] Eseguire le due parti in Keras sul PC e confrontarle con l'inferenza completa su 146 frame: differenza massima 0,0. Prova TFLite/distribuita ancora da fare.
- [x] Realizzare un client Python sperimentale: riproduce le attivazioni registrate; non esegue camera o prefisso della rete. Il client degli autori non è stato recuperato.
- [x] Verificare lo scambio TCP col ricevitore separato e l'inferenza del suffisso Keras sul PC, inclusa nuova sessione dopo riconnessione. Integrazione col server SCIoT e hardware ancora da fare.

### 6. Preparare le sequenze di valutazione

- [x] Acquisire una prima sequenza esplorativa: `VideoWithCan.mp4`. Non costituisce un dataset di valutazione completo.
- [ ] Includere scene stabili, oggetti che entrano/escono, movimenti e variazioni di luce; prevedere anche condizioni sfavorevoli alla compressione.
- [ ] Usare sequenze di valutazione separate dai dati di addestramento. Evitare che frame quasi identici della stessa ripresa finiscano in entrambi gli insiemi.
- [ ] Considerare intervalli tra frame plausibili per il dispositivo: un video ad alta frequenza può sovrastimare la somiglianza temporale disponibile su ESP32.

### 7. Estrarre e caratterizzare le attivazioni

- [x] Salvare i tensori al punto di split per ogni frame campionato: `(146, 24, 24, 8)`.
- [x] Effettuare una prima caratterizzazione delle differenze e misurare i payload dei codec; nessun valore identico nella stessa posizione tra i frame confrontati a questo split.
- [x] Valutare uno split fisso. Il confronto con altri punti validi resta un possibile approfondimento.

### 8. Confrontare le strategie di trasmissione

- [x] Confrontare su PC tensore completo, compressione indipendente e codifiche differenziali senza perdita, con e senza riordino dei byte.
- [x] Contare i byte dei messaggi sperimentali, inclusi header e rinnovi; misurare tempi del codec sul PC e identificare il riferimento minimo da conservare. Picco RAM, tempi ESP32 e traffico di rete reale restano da misurare.
- [x] Verificare nel prototipo sequenze/riferimenti, checksum, rifiuto di delta mancanti e ripristino tramite completo; sei test superati.
- [x] Definire nei prototipi riferimento condiviso, sequenze, invii completi e recupero dopo aggiornamenti mancanti. Un cambio di split richiede una nuova sessione; integrazione nel framework ancora da fare.
- [x] Provare una prima perdita controllata: passi da 0,0001 a 1, quantizzazione uniforme delle attivazioni, confronto indipendente/temporale a ricostruzione identica e riferimenti coerenti. Misurati byte, errore su attivazioni/uscite e cambiamenti delle celle.
- [x] Distinguere fedeltà alle uscite originali da accuratezza su annotazioni; la seconda resta da valutare con un dataset adatto.
- [x] Verificare i due prototipi con 15 test, inclusi limite d'errore, riferimenti, overflow, corruzione e recupero.
- [x] Confrontare i tre metodi via TCP loopback con suffisso Keras in un processo
  separato, rinnovo della sessione dopo riconnessione e 20 test complessivi.
- [x] Chiarire risultati e limiti del paper di Shiba, distinguendone il metodo
  dal codec attuale e la fedeltà al modello dall'accuratezza su annotazioni.
- [x] Convertire il modello intero in TFLite float32 e INT8 senza riaddestramento,
  separando calibrazione (48 frame) e valutazione (98 frame dello stesso video).
  Verificati tipi int8/int32, operatori/versioni, inferenza desktop e predizioni;
  quattro nuovi test INT8, 19 test senza socket passati.
- [x] Confrontare il 16×8 sugli stessi 48/98 frame, con attivazioni INT16,
  pesi INT8 e bias INT64; verificati assenza di fallback float, predizioni,
  binari di controllo invariati e ricaricamento dei risultati. 23 test senza socket.
- [ ] Verificare la calibrazione su input rappresentativi aggiuntivi, con
  valutazione separata: la prima variante INT8 modifica 25 celle a soglia 0,5.
- [ ] Verificare sul target operatori/runtime, memoria e tempo della variante
  scelta, incluse le varianti INT16 degli operatori. Esportare e verificare uno
  split quantizzato con scale/zero point coerenti; i byte osservati nel modello
  intero non sono un payload SCIoT integrato.
- [ ] Spiegare con un esempio e specificare il nuovo codec DPCM: riferimento,
  quantizzazione del residuo, parametri e rinnovi; poi aggiungere dead-zone come
  variante separata. Non ancora implementato.
- [ ] Confrontare indipendente, temporale attuale, DPCM e DPCM/dead-zone sugli
  stessi input; misurare byte ed errore senza assumere ricostruzioni identiche.

### 9. Decidere se proseguire e verificare su hardware

- [ ] Se i risultati preliminari giustificano il lavoro, portare la soluzione su ESP32 e misurare tempi, memoria e comportamento della rete reali.
- [ ] Definire quando conviene tornare al tensore completo.
- [ ] Se i benefici sono insufficienti, documentare il risultato e valutare altre attività, inclusa la pista già annotata in `IDEE_DA_ESPLORARE.md`.

## Prossimo traguardo

**Verificare il supporto INT8/INT16 nel runtime Micro effettivo prima di scegliere
il porting e misurare memoria/tempo sulla scheda.**

Le sezioni [9.5](ANALISI_COMPRESSIONE_ATTIVAZIONI.md#95-verifica-int8-del-modello--18-ottobre)
e [9.6](ANALISI_COMPRESSIONE_ATTIVAZIONI.md)
documentano le prove completate: il 16×8 migliora la fedeltà su questo campione,
ma nessuna qualità è ancora approvata. Ampliare calibrazione e valutazione su
sequenze distinte. Il modello rimane quello dato; calibrare non richiede
annotazioni, mentre l'accuratezza reale le richiede. Evitare di cercare parametri
sul campione usato per valutare.

Poi verificare esecuzione sul target e split con parametri coerenti; tempi e
memoria ESP32 vanno misurati. Conservare float32 come controllo. DPCM/dead-zone
resta un approfondimento successivo: chiarire intervalli, precisione e dead-zone,
perché il solo cambio d'ordine con passo fisso può lasciare quasi uguali le
ricostruzioni. Confrontare il vantaggio temporale sulla rappresentazione scelta,
senza trasferire automaticamente i precedenti numeri float32 a INT8 o 16×8.
