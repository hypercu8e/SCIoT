# Tirocinio SCIoT — scaletta e contesto per ripartire

Aggiornato il 29 ottobre 2026. Cronologia: [diario](DIARIO_TIROCINIO.md).
Risultati e stato generale: [recap](RECAP_LAVORO_FORK.md).

## Punto di ripresa

- **Baseline fisica disponibile:** INT8 con ESP-NN, taglio `block_2_add`, una
  ESP32-S3-EYE e suffisso HTTP sul PC. Il [confronto del 27 ottobre](experiments/esp32_representation_benchmark/espnn_2026-10-27/report.md)
  misura meno traffico e meno attesa rispetto a FLOAT32 nella configurazione provata.
- **Zlib già provato sul target:** il [confronto del 28–29 ottobre](experiments/esp32_int8_compression_benchmark/2026-10-28/report.md)
  risparmia circa 14,3% sul payload dei tre ingressi canonici, ma aumenta la mediana
  del tempo completo. Con camera il vantaggio temporale non è uniforme. I punteggi
  coincidono esattamente; INT8 raw resta il controllo.
- **Multi-client implementato, hardware da validare:** server HTTP v2, firmware
  dedicato, dieci test e prove con client simulati fino a 32 identità sul PC.
  [Report PC/build](experiments/multiclient_validation/2026-10-28/README.md).
- **EON accantonato:** upload del prefisso riuscito, compilazione rifiutata per
  il piano del progetto sui modelli importati; nessuna misura hardware EON.
  [Esito persistente](experiments/eon_prefix_benchmark/STATUS.json).
- **Qualità ancora da consolidare:** 84 foto annotate valutate senza distinguere
  la classe; restano ordine dei canali, dati indipendenti e scene rappresentative.

Prossima verifica: HTTP v2 con una scheda e client simulati, poi due ESP32 reali,
almeno 1.000 richieste per scheda, riavvio di A mentre B continua e prova di un'ora.
Seguire il [README del firmware](src/client/esp32-s3-eye-multiclient/README.md),
con backup verificato della specifica scheda e coordinamento sull'uso dell'hardware.
La chiusura del test di compressione del 29 ottobre ha verificato il ripristino
del firmware preesistente: non è una validazione del client HTTP v2.

Le sezioni di fonti riportano anche riscontri storici; le checklist qui sotto
separano ciò che è completato da ciò che manca. Nessun commit eseguito durante
l'allineamento documentale; dati locali e stato Git sono descritti nel recap.

## Contesto

- Tirocinio interno da 300 ore e possibile tesi triennale in Informatica a UNIMORE, con il prof. Luca Bedogni.
- Il tirocinio è iniziato ufficialmente. Titolo generale concordato: **Multi Device Split Computing**.
- La compressione delle differenze delle attivazioni è una prima direzione da esplorare, non un argomento definitivo. Se non produce benefici, si potranno approfondire altre esigenze del progetto.
- Il professore ha indicato la comunicazione di rete come principale area di ottimizzazione; ha inoltre segnalato il limite del singolo client sul server.
- L'utente sta imparando i concetti: spiegare prima il funzionamento e il motivo delle scelte, distinguendo ipotesi, analisi statica e risultati sperimentali.

## Idea attualmente in esplorazione

Nel flusso esaminato, l'ESP32 esegue i primi layer del modello e invia al server l'intero tensore di attivazioni al punto di split. Il server completa l'inferenza.

Una pista successiva resta conservare un riferimento condiviso tra client e server e inviare una codifica compressa delle differenze delle attivazioni tra frame consecutivi. Il server ricostruisce il tensore corrente prima di eseguire i layer rimanenti. Servono invii completi per inizializzare e ripristinare il riferimento.

**Domanda:** il risparmio di traffico compensa il costo aggiuntivo di calcolo e memoria sull'ESP32, mantenendo risultati di detection adeguati?

Distinzioni già chiarite:

- Il tensore contiene i dati; il layer esegue una trasformazione. Le attivazioni sono i risultati intermedi della rete.
- Appiattire un tensore multidimensionale in un vettore non riduce il numero di valori o i byte.
- Anche la semplice sottrazione tra tensori non comprime: occorre codificare le differenze in meno byte, contando anche gli eventuali indici e metadati.
- La quantizzazione riduce la precisione dei valori ed è una scelta distinta dalla codifica delle differenze.
- Saltare del tutto elaborazione e trasmissione dei frame simili è un'altra idea, annotata in [IDEE_DA_ESPLORARE.md](IDEE_DA_ESPLORARE.md). Va ripresa dopo l'esplorazione attuale.

## Fonti e verifiche già svolte

### Repository — riscontri storici del 15–18 ottobre

Checkout esaminato: `main`, commit `0cfeb9b08ca20dadc754cb38a5201c60991066ba`. La corrispondenza col ramo pubblico era stata verificata durante l'analisi precedente; ricontrollarla prima di assumere che non siano arrivati aggiornamenti.

- Sono presenti client ESP32 MQTT, HTTP e WebSocket.
- I client inviano il tensore completo. Il server non mantiene un riferimento tra frame per ricostruire aggiornamenti differenziali. Il salvataggio delle valutazioni in CSV non svolge questa funzione.
- La configurazione seleziona FOMO 96 × 96. Il firmware pubblico configura tre canali e 59 layer eseguibili.
- Non abbiamo identificato il nome della classe di oggetti del modello originariamente incluso in SCIoT. L'ispezione dei metadati HDF5/Keras e dei 64 sott modelli TFLite non ha trovato etichette; non sono emersi dataset o file di etichette nella cronologia locale consultata. Il nuovo candidato Beer vs. cans è usato separatamente nell'esperimento.
- `src/client/python/` contiene soltanto un README, non un client eseguibile.
- Il README prevede l'importazione di un modello Keras `.h5`; `model_split.py` genera sott modelli TFLite e header C.
- Il supporto dichiarato a TensorFlow Lite non garantisce la compatibilità di qualunque architettura, operazione o punto di split.
- Durante questa prima ispezione non erano state eseguite prove su ESP32. È stato invece configurato `.venv` con Python 3.11.17, TensorFlow/Keras 2.15.0, NumPy 1.26.4 e h5py 3.11.0, installando le dipendenze autorizzate. Sono state eseguite inferenze complete e con split in Keras sul PC, e il confronto dei codec con sei test superati. I tempi del PC non emulano l'ESP32.

### Esperimento storico isolato completato su PC

- Script e istruzioni: [experiments/activation_compression/README.md](experiments/activation_compression/README.md).
- Modello candidato: [Beer vs. cans FOMO](https://studio.edgeimpulse.com/public/89078/latest), `.h5` scaricato dall'utente. Nessun riaddestramento effettuato. L'ordine delle etichette dell'esportazione resta da confermare.
- Ingresso: 96 x 96 in grigio, float32 normalizzati in [0,1]. La parità pixel per pixel con Studio non è stata verificata.
- Video: `VideoWithCan.mp4`, circa 29,26 secondi; campione di 146 frame a 5 fps e sottoinsieme di 30 a 1 fps.
- Split: `block_2_add`, un solo tensore `24 x 24 x 8`, cioè 18.432 byte per frame. Il file di attivazioni contiene un tensore per ciascun frame campionato.
- Prima parte seguita dalla seconda parte e modello completo: differenza massima osservata 0,0 sui 146 frame.
- Il confronto senza perdita ricostruisce tutti i tensori byte per byte. Include header, checksum, primo completo, rinnovi ogni 5 secondi e ritorno al completo quando il delta è più grande.
- I risultati contano il flusso applicativo sperimentale; escludono overhead e comportamento effettivo dei trasporti di SCIoT. Il codec non è integrato nel framework.
- I file generati in `results/` sono ignorati da Git. Una copia stabile di report, JSON, CSV, metadati e lock è in [baseline_2026-10-15](experiments/activation_compression/baseline_2026-10-15/README.md). Baseline e documenti iniziali risultano nei commit locali `d38a489` e `087fef9`; la prova con perdita è nel commit locale `78eac02`. TCP e quantizzazione PC risultano successivamente tracciati nella cronologia locale; i nuovi lavori hardware e multi-client sono ancora nel working tree. Lo stato corrente è nella sezione Git del recap; la corrispondenza col remoto non è stata verificata.

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
- [x] Conservare modello, provenienza dei dati, configurazione, preprocessing, manifest e hash.
- [ ] Confermare l’associazione dei canali alle classi dell’H5 esportato.
- [x] Verificare il candidato TFLite INT8 nel percorso sperimentale ESP-NN/HTTP.
- [ ] Validare sulla scheda il nuovo percorso HTTP v2 e confermare la preparazione degli input prima di ampliare il dataset.

**Stato:** candidato recuperato senza nuovo addestramento, usato nei benchmark fisici ESP-NN e nel nuovo server/client HTTP v2. La validazione hardware di v2 resta aperta. Edge Impulse serve anche ad addestrare ed esportare; lo split distribuisce l'esecuzione del modello già addestrato.

### 4. Ottenere un'inferenza completa sul PC

- [x] Preparare l'ambiente compatibile col progetto, verificando dipendenze e versioni.
- [x] Elaborare un'immagine nota e spiegare la griglia FOMO. Nella prima prova su `canCoke.jpeg` non è stata ottenuta una rilevazione con soglia 0,5; non è una valutazione complessiva dell'accuratezza.
- [x] Verificare dimensioni, canali, normalizzazione e tipo numerico usati nella prova. Parità esatta con Studio e ordine delle etichette restano da confermare.

### 5. Riprodurre lo split sul PC

- [x] Scegliere un punto compatibile con le dipendenze del grafo: `block_2_add`, un tensore di confine.
- [x] Eseguire le due parti in Keras sul PC e confrontarle con l'inferenza completa su 146 frame: differenza massima 0,0. Successivamente verificati split TFLite INT8 e percorso fisico ESP-NN/HTTP.
- [x] Realizzare un client Python sperimentale: riproduce le attivazioni registrate; non esegue camera o prefisso della rete. Il client degli autori non è stato recuperato.
- [x] Verificare lo scambio TCP col ricevitore separato e l'inferenza del suffisso Keras sul PC, inclusa nuova sessione dopo riconnessione. Successivamente verificato il percorso sperimentale ESP32/HTTP; il vecchio endpoint SCIoT e HTTP v2 multi-client hanno verifiche distinte.

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
- [x] Contare i byte dei messaggi sperimentali, inclusi header e rinnovi; misurare tempi del codec sul PC e identificare il riferimento minimo da conservare. Tempi e traffico HTTP sul target sono ora misurati per FLOAT32/INT8 e zlib INT8; il picco RAM complessivo resta aperto.
- [x] Verificare nel prototipo sequenze/riferimenti, checksum, rifiuto di delta mancanti e ripristino tramite completo; sei test superati.
- [x] Definire nei prototipi riferimento condiviso, sequenze, invii completi e recupero dopo aggiornamenti mancanti. Un cambio di split richiede una nuova sessione; integrazione nel framework ancora da fare.
- [x] Provare una prima perdita controllata: passi da 0,0001 a 1, quantizzazione uniforme delle attivazioni, confronto indipendente/temporale a ricostruzione identica e riferimenti coerenti. Misurati byte, errore su attivazioni/uscite e cambiamenti delle celle.
- [x] Distinguere fedeltà alle uscite originali da accuratezza su annotazioni; il primo conteggio su 84 foto annotate ignora la classe e non certifica la qualità generale.
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
- [x] Verificare INT8 con ESP-NN sul target, split e parametri quantizzati coerenti,
  tempi completi, arene e traffico HTTP sperimentale (27 ottobre).
- [x] Confrontare raw e zlib indipendente INT8 sul target con ricostruzione esatta
  e costo del codec incluso (28–29 ottobre).
- [ ] Misurare picco RAM complessivo ed energia, se richiesti dalla domanda di ricerca.
- [ ] Verificare runtime e costi della variante 16×8 sulla scheda prima di adottarla.
- [ ] Spiegare con un esempio e specificare il nuovo codec DPCM: riferimento,
  quantizzazione del residuo, parametri e rinnovi; poi aggiungere dead-zone come
  variante separata. Non ancora implementato.
- [ ] Confrontare indipendente, temporale attuale, DPCM e DPCM/dead-zone sugli
  stessi input; misurare byte ed errore senza assumere ricostruzioni identiche.

### 9. Decidere se proseguire e verificare su hardware

- [x] Misurare sulla scheda INT8 ESP-NN e zlib indipendente, con camera e rete reali. La compressione temporale non è inclusa in questa verifica.
- [ ] Definire quando conviene tornare al tensore completo.
- [x] Documentare il compromesso osservato con zlib: meno byte, più attesa sulle immagini identiche.
- [x] Implementare HTTP v2 con identità/sessioni, coda limitata e verifiche PC.
- [ ] Validare HTTP v2 con una e poi due ESP32; riconnessioni, 1.000 richieste per scheda e stabilità di un’ora.
- [ ] Valutare altre piste, inclusa la selezione dei frame in `IDEE_DA_ESPLORARE.md`, dopo aver fissato i controlli.

## Prossimo traguardo

**Chiudere la validazione hardware multi-client mantenendo INT8 raw con ESP-NN
come controllo**, seguendo la procedura del client v2. Le prove PC e la build
sono già disponibili; non dimostrano il comportamento di due schede su Wi-Fi.

In parallelo confermare classi e preprocessing e ampliare la qualità su dati
indipendenti, separando calibrazione e valutazione. Usare byte, tempo completo,
memoria e riconoscimenti utili come criteri distinti. Dopo questa base, scegliere
un confronto fra temporale INT8, altri tagli o 16×8; specificare DPCM/dead-zone
prima di implementarlo. EON non è una dipendenza del percorso attuale.
