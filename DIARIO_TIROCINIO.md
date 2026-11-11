# Diario del tirocinio SCIoT

Aggiornato il 9 novembre 2026. Titolo del tirocinio: **Multi Device Split Computing**.
Tirocinio interno da 300 ore, con possibile sviluppo in tesi triennale in Informatica
a UNIMORE, referente prof. Luca Bedogni.

Per una lettura d'insieme di ciò che abbiamo fatto e capito:
[recap del lavoro sul fork](RECAP_LAVORO_FORK.md).

Questo diario ricostruisce le attività dall'inizio del percorso sulla base dei
documenti locali e delle prove conservate. La data amministrativa esatta di inizio
e le ore effettivamente svolte non sono riportate nelle fonti disponibili: non
vengono inventate. Le prime attività tecniche documentate risalgono al 15 ottobre.
Non è un registro ufficiale delle presenze.
Le sezioni datate descrivono le evidenze disponibili in quel momento; lo stato
attuale e le attività successive sono riportati in fondo al documento.

Per riprendere dalla fine del 9 novembre: [punto di ripresa operativo](RIPRESA_LAVORO.md), con riepilogo delle ultime quattro giornate.

## Obiettivo iniziale

Capire SCIoT e individuare un miglioramento utile per distribuire l'inferenza di
una rete neurale tra dispositivi IoT e server. Secondo il contesto annotato nella
scaletta, il docente ha indicato la comunicazione come area di ottimizzazione e
segnalato il limite della gestione di un solo client. La compressione temporale
delle attivazioni è la prima pista sperimentale, non un argomento definitivo.

## 1. Studio del framework e dei concetti — attività documentate il 15 ottobre

Abbiamo chiarito modello, pesi, layer, tensori, attivazioni, inferenza e
addestramento. Lo split interrompe l'esecuzione sul dispositivo e la prosegue sul
server utilizzando i risultati intermedi necessari; non richiede di addestrare
una rete diversa per ogni taglio.

Abbiamo esaminato struttura del repository, configurazione, caricamento e
conversione dei modelli, firmware MQTT/HTTP/WebSocket, server e algoritmo di
offloading. Nel percorso esaminato il client invia l'uscita del layer di split,
metadati e tempi; invia anche l'immagine originale in un messaggio separato.
Il server non implementa la compressione temporale qui studiata.

Risultati dell'analisi statica:

- Il protocollo e il firmware assumono attivazioni float32.
- FOMO contiene rami residui: alcuni split richiedono più di un tensore di confine.
- La presenza di un README in `src/client/python/` non equivale a un client Python
  eseguibile disponibile nel checkout.
- La gestione di più dispositivi richiede stato e statistiche separati.

**Artefatti:** [spiegazione del repository](SPIEGAZIONE_REPOSITORY.md),
[scaletta](SCALETTA_TIROCINIO.md). La spiegazione è stata salvata il 17 ottobre
ricostruendo lo studio precedente. Il checkout inizialmente esaminato era
`0cfeb9b`; questo non identifica automaticamente la versione remota attuale.

## 2. Paper, limiti e possibili interventi — studio iniziale e consolidamento

La scaletta documenta una prima lettura del paper SCIoT CCNC 2026 e il confronto
con il repository. Restano da approfondire algoritmo, grafici, versione del
software usata dagli autori e disponibilità del loro client Python.

È stata annotata anche letteratura sulla codifica differenziale con quantizzazione:
il contributo da esplorare è l'implementazione e valutazione nel contesto SCIoT,
senza rivendicare l'invenzione del principio della compressione temporale.

Abbiamo raccolto proposte su separazione tra modello e infrastruttura, supporto
a tipi numerici diversi, split validi, protocollo, più client, WebSocket,
trasmissione opzionale delle immagini e duplicazioni tra firmware.
**Sono analisi e proposte, non refactoring completati né benefici misurati.**

**Artefatti:** [analisi dei miglioramenti](ANALISI_MIGLIORAMENTI_SCIOT.md),
[analisi delle duplicazioni](ANALISI_CODICE_SUPERFLUO.md),
riferimenti al paper e alla letteratura nella [scaletta](SCALETTA_TIROCINIO.md).
I due report di analisi sono stati scritti il 17 ottobre a partire dalla discussione
del 15 ottobre. Le stime di riduzione del sorgente non sono misure di codice eliminato.

## 3. Scelta del modello e prima inferenza — 15 ottobre

Abbiamo scelto come candidato sperimentale il FOMO pubblico Beer vs. cans,
esportato in Keras `.h5`. È separato dal modello originario incluso nel framework,
le cui etichette non erano state identificate. Non abbiamo addestrato né affinato
il modello; il reinforcement learning è stato discusso, non impiegato.

Caratteristiche del candidato: ingresso `(1,96,96,1)` in grigio, uscita
`(1,12,12,3)` con sfondo e due classi. Preparazione usata: ritaglio quadrato centrale,
resize Lanczos, grigio BT.601 e normalizzazione in [0,1]. Restano da confermare
l'ordine delle etichette dell'esportazione e la parità pixel per pixel con Studio.

La prima inferenza su `canCoke.jpeg` è stata eseguita sul PC; non ha prodotto una
rilevazione con soglia 0,5. Gli artefatti temporanei di quella singola prova non
sono disponibili: il risultato è conservato come resoconto della chat, non come
nuova verifica. Non basta una foto per valutare l'accuratezza complessiva.

**Artefatto:** [analisi delle attivazioni, sezioni 2–4](ANALISI_COMPRESSIONE_ATTIVAZIONI.md).

## 4. Video, split e attivazioni — 15 ottobre

Abbiamo usato `VideoWithCan.mp4`, circa 29,26 secondi, estraendo 146 frame a 5 fps
e un sottoinsieme di 30 frame a 1 fps. Le frequenze sono scelte di campionamento,
non prestazioni misurate o simulate dell'ESP32.

Abbiamo verificato lo split dopo `block_2_add`, che richiede un solo tensore
`24×24×8`: 4.608 float32, pari a 18.432 byte per frame. Prima parte e seconda parte
Keras hanno riprodotto l'uscita del modello intero, con differenza massima osservata
0,0 sui 146 frame. La sequenza salvata ha forma `(146,24,24,8)`.

**Artefatti:** [script di estrazione](experiments/activation_compression/extract_activations.py),
[metadati storici](experiments/activation_compression/baseline_2026-10-15/input-metadata.json).
È una verifica Keras sul PC, non del firmware, dei sott modelli TFLite o della rete.

## 5. Primo esperimento senza perdita — 15 ottobre

Abbiamo confrontato tensori raw, zlib indipendente, differenze numeriche float64,
XOR e riordino dei byte. Sottrarre o appiattire un tensore non lo comprime da solo.
La sottrazione/somma float32 non garantisce gli stessi bit; XOR è reversibile.

Il prototipo conta sessione, header di 24 byte per frame, checksum, completo
iniziale e rinnovi ogni 5 secondi. Nei frame intermedi prova completo e aggiornamento
compressi e invia il più piccolo; può tornare al completo raw. Non conta overhead
e comportamento reali di Wi-Fi/TCP/MQTT/HTTP/WebSocket.

| Campione | Migliore riduzione sul raw | Vantaggio temporale sul completo con lo stesso shuffle/zlib |
|---|---:|---:|
| 5 fps | 14,96% | 5,71% |
| 1 fps | 12,31% | 2,78% |

Ricostruzione verificata byte per byte per ogni frame e ripetizione. Sei test
verificano codec e recupero dopo errori. I tempi sono quelli del PC; il riferimento
di 18.432 byte non misura il picco di RAM del sistema.

**Artefatti:** [script](experiments/activation_compression/compare.py),
[baseline storica](experiments/activation_compression/baseline_2026-10-15/README.md).
Conclusione: beneficio in byte presente ma contenuto; convenienza complessiva su
ESP32 ancora da dimostrare.

## 6. Conservazione del lavoro e chiarimenti — 17 ottobre

Abbiamo consolidato spiegazioni, metadati, report, checksum e lock dell'ambiente
per riprendere il lavoro su un'altra macchina. La cronologia locale ora contiene
`d38a489` (prototipo e baseline) e `087fef9` (documentazione), entrambi del 17 ottobre:
le vecchie note «non ancora in un commit» descrivono il momento precedente a
questi commit. Non è stato verificato se tali commit siano sul remoto.

Nella discussione successiva abbiamo distinto:

- Compressione indipendente: il frame si ricostruisce senza attivazioni precedenti.
- Compressione temporale: servono le attivazioni di riferimento condivise.
- Meno byte trasmessi può ridurre il trasferimento e l'occupazione della rete;
  non aumenta la velocità fisica del collegamento e non garantisce minore latenza totale.
- Il server ricostruisce il tensore completo; il codec temporale può aumentare la RAM.
- I riferimenti devono coincidere, includendo le approssimazioni quando c'è perdita.
- Emulare il firmware non permette di assumere tempi esatti della scheda.
  Per misurare la compressione si può prima usare un benchmark ESP32 con attivazioni
  registrate, senza integrare subito camera e rete neurale.

È stata conservata come pista separata la selezione preventiva dei frame simili,
che potrebbe evitare inferenza e trasmissione:
[idee da esplorare](IDEE_DA_ESPLORARE.md). Non è stata implementata.

## 7. Esperimento con perdita controllata — 17 ottobre

L'utente ha autorizzato l'esperimento. Abbiamo definito una quantizzazione uniforme
delle attivazioni: `q = rint(x / passo)` e ricostruzione `float32(q * passo)`.
Si provano passi `0,0001`, `0,001`, `0,01`, `0,1`, `0,5`, `1`.
Il limite per valore è circa mezzo passo, includendo separatamente gli
arrotondamenti numerici. Nessun clipping: gli input fuori intervallo vengono rifiutati.

Gli interi sono int32; il modello resta float32. Non è la conversione del modello
in INT8. Confrontiamo due rappresentazioni della stessa sequenza quantizzata:

- Indipendente: compressione del tensore intero q.
- Temporale: compressione della differenza intera tra q corrente e q precedente,
  con completo iniziale, rinnovi e selezione del payload più piccolo.

**I due metodi ricostruiscono gli stessi tensori approssimati.** Possiamo attribuire
al riferimento temporale il solo risparmio aggiuntivo, a qualità identica.
È una prima variante a griglia uniforme, non una riproduzione del metodo del paper
né una prova di tutte le possibili soglie/dead-zone.

Su questa macchina mancava l'ambiente: abbiamo creato `.venv` con Python 3.11.17,
TensorFlow 2.15.0, NumPy 1.26.4 e h5py 3.11.0. È un ambiente minimo per gli
esperimenti, non l'installazione completa di tutti i servizi SCIoT.
Gli input video/modello/foto sono stati verificati con i checksum storici.
Abbiamo rigenerato i 146 frame e verificato di nuovo lo split con differenza massima 0,0.

Le verifiche includono identità tra ricostruzioni indipendenti e temporali, limite
d'errore, coerenza dei riferimenti, cambiamenti piccoli cumulativi, perdita di un
delta, recupero, corruzione, duplicati, troncamenti e overflow.
Misuriamo byte, tempi CPU PC, MAE/RMSE/max errore sulle attivazioni e sull'uscita,
e cambiamenti nelle celle FOMO. Le celle non sono oggetti distinti e non abbiamo
annotazioni per misurare l'accuratezza di detection.

**Codice:** [codec](experiments/activation_compression/lossy_codec.py),
[confronto](experiments/activation_compression/compare_lossy.py),
[test](experiments/activation_compression/test_lossy.py).

### Risultati della prova completata

| Passo, a 5 fps | Risparmio indipendente/raw | Risparmio temporale/raw | Vantaggio temporale/indipendente | Celle cambiate a soglia 0,5 |
|---|---:|---:|---:|---:|
| 0,0001 | 35,19% | 38,46% | 5,04% | 0 |
| 0,001 | 40,61% | 48,66% | 13,57% | 0 |
| 0,01 | 52,50% | 57,47% | 10,48% | 1 |
| 0,1 | 60,79% | 68,28% | 19,09% | 2 |
| 0,5 | 67,81% | 79,01% | 34,78% | 49 |
| 1 | 72,32% | 83,85% | 41,63% | 93 |

Il riferimento presenta 151 celle oggetto su 21.024 celle-frame a soglia 0,5.
Con passo 0,001 il massimo errore sui punteggi è circa 0,000603 e non cambiano
le etichette delle celle a quella soglia. Con passo 0,1 il massimo errore sui
punteggi sale a circa 0,0648: una cella scompare e una compare. Con passo 0,5 le
celle perse sono 20 e quelle introdotte 29. Le metriche sono proxy di griglia
rispetto al modello non compresso, non valutazioni su annotazioni né conteggi
del postprocessing FOMO.

Sono state completate anche le misure a 1 fps: per passo 0,001 il risparmio
temporale sul raw è 45,17%, con vantaggio aggiuntivo 7,77% sull'indipendente.
Il beneficio temporale resta quindi sensibile alla distanza tra frame.

I 15 test sono passati. La ricostruzione dei due metodi coincide per ogni frame,
passo e frequenza in tutte le tre ripetizioni. Abbiamo conservato hash, ambiente,
parametri e controlli dei conteggi. Le nuove attivazioni hanno un hash diverso
dalla baseline storica: nessuna causa specifica è stata attribuita senza prova;
tutti i confronti nuovi usano gli stessi tensori rigenerati.

**Artefatti permanenti:** [report](experiments/activation_compression/lossy_2026-10-17/report.md),
[dati e riproduzione](experiments/activation_compression/lossy_2026-10-17/README.md).
La baseline senza perdita del 15 ottobre è stata preservata e verificata con
i suoi checksum. Non abbiamo eseguito commit o push del nuovo lavoro.

## 8. Prova client–server TCP su PC — 18 ottobre

Realizzato un client Python che riproduce le attivazioni già estratte e un server
separato che ricostruisce il tensore ed esegue il suffisso Keras. Il collegamento
è TCP loopback, con formato sperimentale separato dal protocollo SCIoT.
Non sono state modificate le applicazioni server o firmware esistenti.

146 frame, tre metodi, tre giri: 1.314 richieste verificate e 18 connessioni.
Ogni sequenza viene interrotta volontariamente a metà tra due frame confermati:
la connessione nuova riparte con sessione, sequenza e riferimento nuovi.
Non è una prova di recupero automatico da guasti durante un messaggio.

Byte applicativi client → server: raw 2.696.760, indipendente 1.602.438,
temporale 1.385.197, costanti nei tre giri. Il risparmio temporale sul raw è
48,63%; sull'indipendente è 13,56%. Le risposte del server occupano 261.146 byte
per ciascuna sequenza e sono conteggiate separatamente. Header TCP/IP esclusi.
Sul loopback il codec aumenta il tempo complessivo: non c'è una dimostrazione
di beneficio di latenza su ESP32 o rete limitata.

Verificati hash dei tensori, uscite raw rispetto all'estrazione e identità byte
per byte delle uscite indipendenti/temporali. Nessuna cella cambia a soglia 0,5
nel campione; senza annotazioni resta una misura di accordo col raw.
20 test passati. Input e ambiente sono identificati nei nuovi artefatti:
non si assumono identici ai tensori rigenerati della prova con perdita del 17.

Chiarito anche il rapporto con il paper di Shiba et al. (IEEE Access 2026):
il nostro codec quantizza prima il tensore e codifica poi differenze intere;
il DPCM del paper quantizza invece il residuo rispetto alla ricostruzione
precedente, e D+DZ aggiunge dead-zone sui residui. Non è una replica di D+DZ.

**Artefatti:** [prova TCP](experiments/activation_compression/tcp_2026-10-18/README.md),
[client/server](experiments/activation_compression/socket_benchmark.py).

## 9. Chiarimenti sul significato dei risultati e sul paper — 18 ottobre

Abbiamo esplicitato cosa significa compressione indipendente: ogni tensore
viene compresso e inviato separatamente; il ricevitore non usa il precedente.
Il temporale mantiene invece un riferimento condiviso e può inviare differenze.
La perdita di precisione è una scelta distinta dall'uso del riferimento temporale.

Chiarito anche il confronto dei tempi TCP. La misura va dal tensore già pronto
alla risposta del server, includendo codifica, scambio e suffisso della rete.
Sul loopback del PC il temporale è più lento sia del raw sia dell'indipendente:
il trasferimento è molto rapido e il lavoro del codec non viene compensato dal
risparmio di byte. Non è una previsione dei tempi su ESP32 o Wi-Fi.

Ricontrollato il PDF del paper di Shiba e documentato cosa dimostrano le metriche
di accordo e comprimibilità, quali confronti usano un delta ideale e quali misure
hardware/rete restano aperte. I risultati del paper sono distinti dai nostri:
non rivendichiamo una sua replica o la convenienza complessiva sul dispositivo.

**Nuovi appunti e proposta:** [analisi, sezioni 9.2–9.4](ANALISI_COMPRESSIONE_ATTIVAZIONI.md#92-cosa-abbiamo-misurato-con-il-client-e-il-server-tcp--18-ottobre).
Proposto di spiegare e definire il nuovo codec, poi confrontare DPCM uniforme
e DPCM/dead-zone sugli stessi input del FOMO, conservando i controlli attuali.
È un aggiornamento documentale: nessun nuovo codec o benchmark eseguito qui.

## 10. Fattibilità INT8 del modello — 18 ottobre

Dopo la revisione delle priorità abbiamo verificato se il modello dato potesse
essere adattato numericamente all'ESP32 senza riaddestramento. Preparato un
esperimento separato che converte il modello intero in TFLite float32 (controllo)
e integer-only INT8, con ingresso e uscita int8. Il percorso SCIoT non è modificato.

Primi 48 frame per calibrare gli intervalli, successivi 98 per valutare. Gli indici
sono disgiunti, ma provengono dallo stesso video e sono temporalmente correlati.
Nessuna annotazione o ricerca dei parametri sui dati di valutazione.

| Risultato sui 98 frame | TFLite float32 | TFLite INT8 |
|---|---:|---:|
| Byte del file | 84.292 | 57.088 |
| Byte dei valori a `block_2_add` nel modello intero | 18.432 | 4.608 |
| Errore assoluto massimo sui punteggi rispetto a Keras | 0,00000310 | 0,289446 |
| Celle cambiate a soglia 0,5 | 0 | 25 |
| Celle oggetto perse / introdotte rispetto a Keras | 0 / 0 | 11 / 14 |

Il riferimento ha 99 celle oggetto su 14.112 celle-frame. L'accordo globale INT8
del 99,82% nasconde l'11,11% di celle oggetto perse; non sono conteggi di oggetti
distinti o accuratezza su annotazioni. La variante è fattibile sul PC, ma non
viene promossa a baseline di qualità. La causa degli scostamenti non è stabilita.

Verificati conversione, allocazione e inferenza desktop, assenza di fallback
float, inventario di operatori/versioni e parametri del confine. INT8 comprende
tensori int8 e int32; questi ultimi includono bias e forme. La riduzione del
32,27% riguarda il file TFLite; quella del 75% i soli valori del tensore al confine.
Non abbiamo misurato picco di RAM, tempo, energia o rete sull'ESP32, né esportato
e verificato due sottomodelli INT8 o integrato ESP-NN.

I quattro nuovi test INT8 verificano scale/zero point, clipping senza overflow,
parametri invalidi e separazione degli indici. Passati 19 test senza socket;
i cinque test TCP precedenti non sono stati rieseguiti in questa attività.
Un percorso separato ricarica i file salvati, riesegue l'inferenza e controlla
hash, metriche e conteggi CSV. Archivio permanente con modelli TFLite, report,
input/source hash e verifiche. Le baseline precedenti sono conservate.

**Artefatti:** [risultati e riproduzione](experiments/activation_compression/int8_2026-10-18/README.md),
[conversione e confronto](experiments/activation_compression/check_int8.py),
[verifica dei file salvati](experiments/activation_compression/verify_int8.py).

## 11. Confronto 16×8 — 18 ottobre

Provata la quantizzazione con attivazioni INT16, pesi INT8 e bias INT64, senza
riaddestramento e mantenendo gli stessi 48 frame di calibrazione e 98 di
valutazione. Riuscite conversione integer-only, allocazione e inferenza desktop.
I controlli float32 e INT8 sono gli stessi binari precedenti: ricaricati,
riproducono gli stessi hash delle uscite e le stesse metriche.

Il 16×8 occupa 69.056 byte (-18,08% rispetto al TFLite float32) e il tensore
al confine 9.216 byte (-50% sui soli valori). A soglia 0,5 le celle cambiate
scendono da 25 di INT8 a 18; perse da 11 a 7 sulle 99 del riferimento,
introdotte da 14 a 11. MAE dei punteggi da 0,00223682 a 0,000776675; il massimo
scostamento resta circa 0,286. Più fedeltà in queste metriche, senza una qualità
approvata per l'applicazione o una valutazione su annotazioni.

Salvati modello 16×8, controlli identici, report, metriche per frame e hash;
verificati in un percorso separato ricaricando i file. Passati 23 test senza
socket, inclusi quattro nuovi controlli INT16. Archivi precedenti conservati.
Nessuna modifica a firmware/server, split quantizzato distribuito, esecuzione
ESP32 o misura di tempo/memoria. La variante INT16 dei singoli operatori deve
essere verificata nel runtime Micro effettivo prima di scegliere il porting.

**Artefatti:** [confronto e riproduzione](experiments/activation_compression/16x8_2026-10-18/README.md),
[esperimento](experiments/activation_compression/check_16x8.py),
[verifica dei binari](experiments/activation_compression/verify_16x8.py).

## 12. Dati pubblici e prova HTTP originale sul PC — 18 ottobre

Raccolte 84 immagini con bounding box dal set pubblico di test Beer/can e
gli archivi OTB Coke (291 frame) e Liquor (1.741). Verificati immagini, hash e
CRC ZIP. Eseguita l'inferenza su tutte le 84 foto e 32 frame scelti uniformemente
per ogni sequenza, senza addestrare o ricalibrare. Keras intero e split coincidono
(max errore 0,0). TFLite float32 non cambia celle a soglia 0,5; INT8 ne cambia
35, 16×8 ne cambia 33 rispetto alle 355 celle oggetto del riferimento.
Sono metriche di fedeltà: ordine dei canali del nostro H5 da confermare, nessun
postprocessing FOMO o valutazione dell'accuratezza sulle annotazioni.

Provato il vero percorso HTTP con client Python e server in processi distinti:
registrazione, immagine RGB565, attivazioni, suffisso TFLite e decisione dello
split. Modello RGB originale SCIoT, distinto dal candidato in grigio; errore
massimo osservato rispetto a Keras intero `2,38e-7`. Dati di stato isolati e
originali verificati invariati; orologio locale al posto di NTP, profili copiati
e tempi dispositivo nulli. Non sono misure realistiche o prove dell'avvio ordinario.

Preparati script ripetibili e [guida PC](TEST_SU_PC.md). Alla successiva richiesta
di chiarimento abbiamo discusso TCP/UDP lasciando fermo l'esperimento UDP.
Nessun porting del codec nel server originale o prova ESP32 eseguito.

## 13. Preparazione delle prove ESP32 — 19 ottobre

In attesa di una scheda, deciso di chiedere il 20 ottobre al professore una
ESP32-S3-EYE in prestito; acquisto da valutare se non disponibile. Nessun messaggio
al professore inviato dall'assistente e nessun acquisto eseguito.

Diviso direttamente il modello INT8 TFLite già conservato in prima e seconda
parte, senza riaddestrare, ricalibrare o convertire di nuovo. Conservati pesi,
opzioni e parametri di quantizzazione; rimappati gli indici e rimosse le costanti
non usate dalle singole parti. Taglio a `block_2_add`, un tensore INT8 `24×24×8`
da 4.608 byte. File: intero 57.088 byte, prima parte 16.400, seconda 41.168.

Rigenerati i 146 input del video, con hash NPY identico alla precedente prova
INT8. Prima parte identica byte per byte al confine del modello intero; seconda
parte, dopo serializzazione/rilettura dei byte intermedi, identica all'uscita
intera su tutti i frame. È equivalenza dello split, non accuratezza su annotazioni.
Salvati tre vettori hardware fissati (frame 48, 96, 145), tutti nella precedente
partizione di valutazione. Un percorso separato ricarica i tre binari e verifica
hash, scale, tipi e uscite dei vettori.

Preparato firmware isolato PlatformIO/Arduino, senza camera o rete, con tre
versioni: `prefix`, `full`, `suffix`. Compilazione e collegamento riusciti per
tutte, usando TensorFlowLite_ESP32 1.0.0, la libreria indicata nel firmware
originale. Il programma registra solo i cinque operatori necessari, mantiene
resolver/interprete validi, confronta le uscite e stampa log JSON di tempi,
arena e heap. Arena iniziale 512 KiB in PSRAM; i byte statici del compilatore
non sono il consumo RAM totale. Nessuna esecuzione `AllocateTensors`/`Invoke`
su hardware, nessun collegamento ESP32–server, nessuna ottimizzazione ESP-NN.

Ispezionata la libreria effettivamente scaricata: percorsi INT8 presenti per i
cinque operatori; nella depthwise convolution manca il ramo con ingresso INT16.
Il modello 16×8 archiviato ha sei nodi con ingresso INT16: non eseguibile con
quella implementazione invariata. Non è un limite generale dell'hardware ESP32-S3.

Passati 31 test degli esperimenti, compresi cinque socket e tre nuovi test del
taglio, più quattro test del verificatore seriale con log sintetici. Conservati
modelli, vettori, manifest, verifica indipendente, versioni e hash del build/runtime.
Firmware/server originali invariati. Script e istruzioni:
[archivio](experiments/activation_compression/esp32_prep_2026-10-19/README.md),
[guida della prova hardware](experiments/esp32_int8_firmware/README.md).

## 14. Correzioni dei tre firmware e verifiche native — 19 ottobre

Implementato il piano concordato durante l'attesa della scheda. HTTP, MQTT e
WebSocket usano ora funzioni comuni per eseguire un layer float32 e comporre il
pacchetto binario. L'interprete viene distrutto soltanto dopo la copia dell'uscita,
e il resolver resta valido; controllati allocatore, AllocateTensors, Invoke,
input/output e secondo ingresso FOMO. Fermato l'invio in caso di errore. Gli ID
vengono copiati come testo; inviati esattamente i tempi fino allo split. Aggiunti
controlli su split, frame e allocazioni principali; inizializzazione camera azzerata
e arresto operativo se setup fallisce.

Nei template `OUTPUT_MSG_SIZE` passa da 922.253 a 461.261 byte: richiesta PSRAM
ridotta di 460.992 byte, senza misura del picco RAM complessivo. Restano uguali
modello, float32, arena e formato riconosciuto dal server. I `conf.h` locali
possono mantenere la vecchia capacità finché non vengono aggiornati.

Configurata una build con piattaforma e dipendenze dirette fissate, profilo S3
generico con flash 8 MB e PSRAM OPI e fallback al template senza credenziali.
Compilazione e link riusciti per tutti i client. La libreria camera viene dal
framework Arduino; UUID 0.1.6 rientra nel precedente intervallo di dipendenza.

Preparato harness nativo C++ con la stessa libreria Micro 1.0.0, ASan e UBSan.
Eseguite 1.170 invocazioni su tre input sintetici, sei split e due ripetizioni;
33.363.072 valori intermedi identici ai kernel di riferimento desktop sugli
stessi 59 binari. Il confronto iniziale diretto degli intermedi con Keras aveva
segnalato differenze: il riferimento definitivo usa i binari effettivamente
distribuiti e registra separatamente lo scostamento Keras. Il massimo intermedio
è 0,00074768; sulle uscite finali 4,77e-7, entro `rtol=atol=1e-5`.

Le prove negative verificano schema, capacità, tipi, allocazione e fallimenti
del calcolo. Quattro pacchetti C++, incluso il massimo da 461.261 byte, decodificati
con il parser server originale e contenuti verificati. Nessun errore ASan/UBSan;
passati nuovamente anche 31 test degli esperimenti e quattro del verificatore log.
L'ambiente PC è stato completato con dipendenze già dichiarate dal progetto,
fra cui pandas per importare il parser reale. Nessun server o broker avviato.

Non misurati tempi/RAM ESP32, camera o rete reale. Non affrontati invii asincroni,
concorrenza delle callback, frammentazione MQTT, NTP e riconnessioni. Nessuna
modifica al server o ai modelli. [Report](experiments/firmware_fixes_2026-10-19/README.md),
[riproduzione dei test](tests/firmware/README.md).

## 15. Esecuzione Micro nativa e costo della suddivisione per layer — 19 ottobre 2026

Implementati due esperimenti riproducibili con il runtime TensorFlowLite_ESP32
1.0.0 sul PC. Il candidato INT8 viene eseguito intero, nelle due parti e come
catena con confine realmente prodotto da Micro, con controlli ASan/UBSan.
Il confronto esatto con i vettori archiviati fallisce: Micro coincide invece
con i kernel desktop `BUILTIN_REF`, e intero e catena Micro coincidono fra loro.
I vettori precedenti restano invariati; il comando segnala il fallimento con
codice 2 e conserva diagnosi e risultati. Non è una misura di accuratezza.

Per float32 sono composti prefissi 0/11/25/58 direttamente dai binari dei
layer, preservando operatori, opzioni e costanti. Confrontati layer separati,
prefisso ricreato per immagine e prefisso persistente: nessuna differenza
numerica osservata sui tre ingressi sintetici. La build con sanitizer è
separata dal benchmark Release, che raccoglie 1.080 misure. Copie esplicite,
memoria nativa e tempi del PC sono riportati separatamente.

I dettagli, i risultati e i comandi sono nel
[report Micro](experiments/micro_execution_2026-10-19/README.md).
Nessuna integrazione dei prefissi nei client o modifica al server; resta da
valutare sul target il compromesso fra memoria, tempo e cambio dello split.

## 16. Survey e valutazione di FOMO con early exiting — 20 ottobre 2026

Individuato il survey SC/EE di Matsubara nei PDF locali e discusso un percorso
di lettura. Chiarito il ruolo delle teste intermedie addestrate e della decisione
di arresto nel software di esecuzione. L'ispezione della configurazione del
candidato H5 mostra una sola uscita finale `softmax`, senza teste anticipate.

L'idea compare già come tema 6 nel catalogo delle proposte. La
[valutazione dedicata](ANALISI_FOMO_EARLY_EXITING.md) distingue rilevamento
anticipato completo e riconoscimento di immagini vuote, collega il precedente
BlankSkip e propone una sola testa con verifica iniziale su PC. Sono documentati
limiti dei dati, costo aggiuntivo, rischio di oggetti mancati, confronti con
modelli statici e condizioni per passare a ESP32 e più client.

La proposta è da discutere con il docente: ridurre offloading e carico sul server
la collega alle esigenze di rete e multi-client, ma non è un argomento approvato.
Nessun modello addestrato, nuovo benchmark o risultato hardware in questa attività.
I PDF e le versioni sono descritti nell'[inventario](papers/README.md).

## 17. FLOAT32 e INT8 con ESP-NN sulla scheda — 27 ottobre 2026

Eseguito un confronto fisico su una ESP32-S3-EYE, CPU 240 MHz, arene in PSRAM,
con prefisso sul dispositivo e suffisso sul PC via HTTP sperimentale. Stesso
FOMO candidato 96×96 in grigio e taglio `block_2_add`. INT8 comprende pesi e
attivazioni; le chiamate ai kernel ESP32-S3 sono verificate nel firmware.
Due sessioni complete, 816 richieste validate, incluse immagini identiche,
84 foto annotate, camera alternata e sequenze continue.

Le attivazioni passano da 18.432 a 4.608 byte (-75%); lo scambio HTTP completo
per immagine scende da 20.647 a 6.822 byte (circa -67%). Sui tre ingressi fissi,
la mediana del tempo completo è circa 860 ms FLOAT32 contro 160 ms INT8.
Nelle sequenze camera: circa 1,1 contro 4,9–5,5 immagini/s. Questi numeri
riguardano questa configurazione, non il vecchio endpoint SCIoT o due schede.

Sulle 84 foto, con matching che ignora la classe, FLOAT32 trova 111/112 oggetti
con 7 falsi positivi; INT8 110/112 con 5 falsi positivi. L'ordine beer/can dei
canali non è confermato e l'indipendenza dal training dell'H5 non è dimostrata.
Non si generalizza il risultato a nuove scene. L'ingresso viene ripristinato
prima di ogni Invoke perché il runtime può riutilizzarne il buffer.

**Artefatti:** [rapporto](experiments/esp32_representation_benchmark/espnn_2026-10-27/report.md),
[metodo e riproduzione](experiments/esp32_representation_benchmark/README.md).
Il firmware originale è stato ripristinato e verificato dopo la prova.

## 18. Valutazione EON e decisione sul runtime — 27–28 ottobre 2026

Preparato il prefisso INT8 congelato, senza training o ricalibrazione. Dopo un
primo rifiuto per il ruolo della API key, upload e configurazione freeform sono
riusciti. La compilazione EON ha restituito `enterprise_required_for_imported_model`:
nel progetto usato l'accesso EON per modelli importati/BYOM richiede Enterprise.
È il risultato di questo tentativo, non una dichiarazione generale sui prezzi
né un'incompatibilità tecnica dimostrata del modello.

Non sono state ottenute librerie EON, build, prove hardware o misure prestazionali.
Decisione: accantonare EON come dipendenza e continuare con TFLite Micro + ESP-NN,
già verificato sulla scheda. Nessun piano a pagamento attivato e nessun modello
riaddestrato per aggirare il vincolo.

**Artefatti:** [stato e istruzioni](experiments/eon_prefix_benchmark/README.md),
[risposta persistente del servizio](experiments/eon_prefix_benchmark/STATUS.json).

## 19. Servizio HTTP v2 multi-client — verifica PC del 28 ottobre 2026

Implementati server `src/server/multiclient/`, firmware ESP32 dedicato e selezione
`--http-v2` nel launcher. Il servizio distingue client, sessione e richiesta;
consente una richiesta pendente per dispositivo, usa coda FIFO limitata e un solo
worker di inferenza. Sono espliciti rifiuti, scadenze, sostituzione delle sessioni
e gestione dei completamenti tardivi. Il percorso legacy resta distinto.

La suite registra 10 test passati. La matrice con 1/2/4/8/16/32 client simulati
sul loopback produce 1.890 tentativi, 1.743 completamenti corretti e 147 rifiuti
429, senza altri errori. In una prova di circa 60 secondi con due client a 20
richieste/s ciascuno: 2.402 completamenti corretti. Queste sono verifiche PC,
non 32 flussi video su Wi-Fi né una misura stabile della capacità massima.

Build del firmware riuscita: 51.540 byte di RAM statica e 1.196.518 byte di flash,
che non sono picchi RAM misurati sulla scheda. Nessuna flash o prova hardware
multi-client è stata eseguita in questa attività. Restano prima una scheda con
client simulati, poi due ESP32 con almeno 1.000 richieste ciascuna, riavvio di A
mentre B continua e verifica di stabilità di un'ora.

**Artefatti:** [report PC/build](experiments/multiclient_validation/2026-10-28/README.md),
[server e protocollo](src/server/multiclient/README.md),
[firmware e procedura hardware](src/client/esp32-s3-eye-multiclient/README.md).

## 20. INT8 non compresso contro zlib — 28 ottobre, chiusura 29 ottobre 2026

Implementato un esperimento separato con lo stesso prefisso INT8 ESP-NN e un
solo interprete: invio raw contro miniz 3.0.2, zlib livello 1, indipendente per
ogni tensore. Nessuna compressione temporale, nuova quantizzazione o modifica
del modello. Compressione e decompressione sono comprese nel tempo completo.
Due sessioni, 816 richieste validate; quattro test del codec e protocollo passati.

Sui tre ingressi canonici il payload mediano scende da 4.608 a 3.949 byte
(-14,3%), lo scambio HTTP da 6.822 a 6.163 byte (circa -9,7%). La compressione
richiede circa 6,8 ms. La mediana del ciclo cresce da 157,4 a 162,7 ms nella prima
sessione e da 163,1 a 166,7 ms nella seconda. Con camera i tempi non indicano un
vantaggio uniforme. Per questa configurazione il codec risparmia byte ma non
mostra un miglioramento stabile della velocità; INT8 raw resta il controllo.

Per ciascuna sessione, attivazioni e punteggi dei 87 ingressi fissi coincidono
byte per byte fra le modalità. Anche le predizioni fra sessioni coincidono.
Sulle 84 foto entrambe trovano 110 oggetti, ne mancano 2 e producono 5 falsi
positivi, con il medesimo limite sul matching senza classe. Workspace del codec:
319.296 byte, più buffer. Non è una misura del picco RAM dell'applicazione.

Il 29 ottobre completato il ripristino: digest degli interi 8 MB confrontato col
backup prima dell'avvio e log seriale del firmware `sciot_esp32_client 0.1.0`,
modello `fomo_224`. Una prima lettura non coincideva dopo il riavvio: le differenze erano nei settori
`0xb000` e `0xc000`, nell'area NVS. Il backup definitivo è stato letto e verificato
mantenendo ferma l'applicazione fra le due operazioni.

**Artefatti:** [rapporto](experiments/esp32_int8_compression_benchmark/2026-10-28/report.md),
[verifiche e ripristino](experiments/esp32_int8_compression_benchmark/2026-10-28/verification.json),
[metodo e comandi](experiments/esp32_int8_compression_benchmark/README.md).

## Stato e prossime decisioni — 29 ottobre 2026

- INT8 con ESP-NN è una baseline fisica favorevole nel modello/taglio/rete provati.
  Le due schede sono disponibili; la validazione del servizio HTTP v2 con due
  dispositivi reali resta da eseguire.
- Zlib indipendente su INT8 risparmia byte ma non dà un vantaggio stabile di
  velocità: mantenere INT8 raw come controllo per i prossimi confronti.
- Confermare classi e preprocessing, usare scene indipendenti e più condizioni
  di luce/distanza/occlusione. Le 84 foto non bastano ad approvare la qualità.
- INT16/16×8 è stato verificato sul PC, non sulla scheda. Il limite della vecchia
  libreria Arduino non dimostra un limite generale del target o del nuovo runtime.
- Compressione temporale su INT8, DPCM/dead-zone, altri tagli, selezione dei frame
  ed early exit restano esperimenti separati; l'early exit richiederebbe training.
- Nessun riaddestramento, misura di energia o misura del picco RAM complessivo
  dell'applicazione è documentato. EON è accantonato e non blocca il lavoro.
- Il lavoro recente è locale e in parte non tracciato da Git; questo aggiornamento
  allinea la documentazione senza creare commit o sincronizzare remoti.

Per riprendere: [recap](RECAP_LAVORO_FORK.md), [scaletta](SCALETTA_TIROCINIO.md)
e [archivi degli esperimenti](experiments/activation_compression/README.md).


## Codec Rice INT8 — 30 ottobre 2026

Preparato un esperimento isolato con raw, miniz1, Rice indipendente e temporale,
sottrazioni INT16 e ricostruzione esatta INT8; controllo secondario D+DZ4 con
miniz6 o packing di due simboli per byte. Ingressi rigenerati con hash identici,
stessi modelli della campagna precedente verificati tramite digest, nessuna
nuova calibrazione. Sui 146 frame desktop Rice temporale richiede 2534,06 B/frame.

Dopo la correzione dei permessi Linux della seriale, una prima diagnosi Wi-Fi
ha richiesto la correzione del nome della rete; nessuna misura è stata accettata
in quella prova e il firmware originale è stato ripristinato e verificato.
La campagna completa successiva ha completato 5616 richieste e 360 diagnostiche,
con attivazioni e uscite lossless identiche al raw prodotto dalla scheda.
D+DZ4 con miniz e con packing ricostruisce esattamente gli stessi tensori con
perdita. Report: [campagna Python](experiments/esp32_lossless_codec_benchmark/hardware_python_2026-10-30/report.md).

Il costo del decoder Rice Python (circa 12 ms temporale) ha motivato un decoder
C++ per il percorso misurato, mantenendo Python indipendente nell'audit.
Nella campagna nativa ordinaria, 3504 richieste, le mediane temporali rispetto
al raw variano fra -1,4% e +1,6%; non superano il criterio predefinito di almeno
-5% in tutte le tre coppie, con p95 non oltre +5%.

Completata anche la campagna con proxy del corpo applicativo a 128 kbit/s:
3504 richieste, mediane Rice temporale inferiori del 23–31% rispetto al raw,
criterio superato in tutte le tre coppie. Una riga USB ha perso soltanto il
prefisso identificativo; tutti i tempi sono presenti. Recupero stretto e
dichiarato da header e contesto sequenziale, con hash e log originale invariato;
nessun tempo stimato. La suite complessiva di 18 test include quattro controlli
specifici per questo recupero, oltre a encoder/decoder, miniz e TCP/proxy reali.
Ogni campagna completata ha ripristino integrale della flash e avvio originale
verificati. Il proxy non simula contesa radio o perdita di pacchetti.

Conclusa la prova a 512 kbit/s: altre 3504 richieste, nessun recupero seriale
necessario; mediane Rice temporale inferiori del 7,3–9,1% nelle tre coppie,
criterio superato. Anche questa campagna ha ripristino e avvio originale
verificati. Totale delle quattro campagne: 16128 richieste misurate e
360 diagnostiche. Le mediane aggregate con proxy scendono del 26,91% a
128 kbit/s e dell'8,51% a 512 kbit/s; sulla rete ordinaria il criterio non è
superato. Questi numeri non confrontano direttamente latenze assolute di
sessioni radio diverse e non simulano contesa o ritrasmissioni Wi-Fi.

Il filone post-hoc su questo modello/split è ora delimitato da una conclusione
operativa: raw per la latenza ordinaria, Rice temporale opzionale in banda
ridotta. La rassegna bibliografica è mirata, non esaustiva; rANS e bottleneck
addestrati restano sviluppi distinti. [Rapporto unico](experiments/esp32_lossless_codec_benchmark/report.md),
[dati e riproduzione](experiments/esp32_lossless_codec_benchmark/README.md).


## Stima offline della soglia — 1 novembre 2026

Rianalizzati i CSV nativi del 30 ottobre, senza collegare la scheda e senza
nuove misure. Un fit T(R)=a/R+b sui proxy 128/512 kbit/s stima circa 0,70 Mbit/s
per il guadagno del 5% sulla sola mediana. Nove abbinamenti dei tre blocchi per
regime danno sensibilità 0,60–0,85 Mbit/s, non un intervallo di confidenza.
Il pareggio del fit è circa 1,2 Mbit/s (sensibilità 0,87–2,16); il modello ideale
CPU+byte, escludendo differenze di trasporto, darebbe invece 4,13 Mbit/s.
Non è una soglia hardware verificata: mancano punti intermedi e il p95 non
è previsto. Dati, formule, hash e grafico nella [stima offline](experiments/esp32_lossless_codec_benchmark/offline_threshold_2026-11-01/report.md).


## Soglia Rice misurata sulla scheda — 1 novembre 2026

Dopo la stima offline, eseguita una nuova campagna isolata sull'hotspot a
2,4 GHz, con stesso modello/split INT8, ESP-NN e 146 ingressi canonici.
Solo raw e Rice temporale, decoder C++, sei giri in ordine alternato per rate:
1752 richieste a ciascuno dei rate 600, 800, 900 e 1000 kbit/s, totale 7008.
Il proxy limita il corpo della richiesta, non misura la velocità PHY Wi-Fi.

600 e 800 superano il criterio predefinito nelle tre coppie (mediana almeno
-5%, p95 non oltre +5%); 900 e 1000 non lo superano. Massimo punto verificato
favorevole 800 kbit/s, con mediana aggregata da 221,67 a 207,77 ms (-6,27%).
Fascia osservata 800–900 kbit/s: non un intervallo di confidenza né il pareggio.
A 900 la prima coppia ha guadagno mediano 4,43% e p95 +13,02%; a 1000 una
coppia guadagna 4,87%, sotto il margine del 5%. Le mediane aggregate rimangono
migliori del raw anche a questi due rate.

Ventuno test superati; tutti i pacchetti ricostruiti dal decoder Python
indipendente, attivazioni e uscite identiche al raw INT8. Log seriali completi,
nessun recupero e nessun tempo stimato. Backup integrale verificato prima del
flash, ripristino degli 8 MB e avvio originale verificati dopo ogni punto.
La rete differisce da ottobre: non si uniscono i campioni di reti diverse per
decidere la fascia e non si presenta la prova come validazione dello stesso fit.
[Rapporto e grafico](experiments/esp32_rice_threshold_benchmark/sweep_2026-11-01/report.md),
[protocollo e riproduzione](experiments/esp32_rice_threshold_benchmark/README.md).

## Prime prove HTTP v2 fisiche e passaggio al laptop — 5 novembre 2026

Collegate e identificate due ESP32-S3-EYE; salvati e verificati separatamente
gli 8 MiB di flash di entrambe. Preparati runner automatico con ripristino in
`finally`, archiviazione delle richieste/risposte, comandi firmware per prove
brevi e temporizzate, letture heap e associazione USB stabile per MAC.

Venti test server superati e build firmware riuscita. Due tentativi si fermano
nel controllo individuale di A: 60 input incorporati completati in ciascuno;
nessun completamento camera nel primo, uno da circa 6,3 secondi seguito da HTTP
408 nel secondo. Il secondo trattiene il framebuffer durante inferenza/invio
e aggiunge log/riconnessione Wi-Fi, senza risolvere il problema. Causa non
isolata; nessun timeout aumentato. Replay del suffisso esatto sui punteggi di
tutte le 60 e 61 richieste archiviate, rispettivamente.

Entrambe le flash originali ripristinate e verificate prima del boot dopo
ciascun tentativo. La successiva preparazione per partire da B completa solo
i backup, senza installare firmware sperimentale; entrambe vengono riavviate
sul firmware originale prima del passaggio al laptop vicino al router.
Nessuna prova simultanea o di stabilità di un'ora completata. Preparato un
piccolo archivio versionato con gli artefatti di modello necessari; backup,
credenziali e log integrali rimangono esclusi da Git.

[Diagnostica](experiments/multiclient_hardware/2026-11-05/report.md) ·
[Procedura](experiments/multiclient_hardware/README.md) ·
[Punto di ripresa sul laptop](RIPRESA_MULTICLIENT_LAPTOP.md).


## Validazione hardware multi-client sul fisso — 9 novembre 2026

Configurata la rete con hotspot Pixel 9a e inoltro USB ADB della porta 8000,
dopo aver verificato che il passaggio diretto hotspot → tethering USB non
raggiungeva il server. Le prime prove individuali completano 60 input fissi e
20 frame camera per scheda, con 160 risposte ricalcolate esattamente sul PC.

La prima campagna completa si interrompe su HTTP 410 di B, rimasta inattiva
oltre i 60 secondi di validità della sessione. Corretto il firmware per registrare
una nuova sessione all'inizio di ogni comando; nessun timeout aumentato.
Build riuscita e 21 test server superati, incluso il recupero tramite nuova
registrazione dopo la scadenza. Tentativo interrotto e ripristini conservati.

La nuova campagna completa supera le prove individuali, A con client PC
simulato, 1.000 frame camera per scheda insieme e il riavvio isolato di A:
B completa 35 richieste durante il riavvio. Nell'ora continua A completa
14.137 frame e B 14.162, senza errori dispositivo o rifiuti. Tutte le 34.296
richieste archiviate ricevono HTTP 200 e hanno punteggi del suffisso identici
al replay indipendente. Attivazioni degli input fissi identiche fra schede e fasi.
Entrambe le flash originali da 8 MiB ripristinate, verificate prima del boot e
avviate sul firmware originale.

Validazione riferita al servizio sperimentale HTTP v2 INT8 raw, ESP-NN,
split `block_2_add`, un worker/thread CPU e rete Pixel + ADB. Non misura
accuratezza annotata, energia, capacità massima o vantaggio dello split.
[Rapporto completo e dati](experiments/multiclient_hardware/2026-11-09-pixel-adb-full/report.md).


## Ottimizzazione input e acquisizione camera — 9 novembre 2026

Implementato un esperimento separato per conversione RGB565 → INT8 mediante LUT
in PSRAM e restituzione anticipata del framebuffer. Verificati tutti i 65.536
colori RGB565 e input/attivazioni di 100 frame reali, anche con camera attiva
durante l'inferenza: nessuna differenza. Nel run locale valido, tre ripetizioni
da 200 frame per variante, il ciclo passa da circa 195 a 98 ms e la cadenza da
5,00 a 9,62 attivazioni/s; età del frame p95 circa 194 contro 197 ms. Conversione
con buffer trattenuto da 47,174 a 1,291 ms. Costo LUT: 64 KiB in PSRAM e circa
327 ms di inizializzazione. Non si tratta di predizioni complete ricevute dal
server: HTTP e suffisso sono esclusi dalla diagnostica locale.

Misurati 2.600 frame camera, incluso un controllo grayscale esplorativo escluso
dalla selezione perché cambia l'ingresso del modello e manca la valutazione
qualitativa. Cinque test analizzatore e build superati; audit finale senza avvisi
watchdog o righe corrotte. Un primo run locale è stato invalidato per watchdog
e una riga persa; quello valido include pause periodiche per il task idle.

Il nuovo confronto HTTP è interrotto da 408, riprodotto anche con il vecchio
firmware già collaudato. Non invalida l'ora multi-client completata prima, ma
impedisce di confermare il guadagno sul ciclo completo e sulle due schede.
Causa non isolata. Firmware originali ripristinati/confermati; nessuna campagna
lasciata attiva e inoltro ADB temporaneo rimosso. Prima di nuove misure complete,
ripartire dalla stabilità del riferimento HTTP senza aumentare i timeout.

[Report e audit](experiments/esp32_input_camera_benchmark/2026-11-09/report.md) ·
[Filoni software](FILONI_OTTIMIZZAZIONE_SOFTWARE.md) ·
[Punto di ripresa e riepilogo giornate](RIPRESA_LAVORO.md).

## Screening HTTP delle ottimizzazioni — 10 novembre 2026

Ripristinato il collegamento hotspot Pixel 9a + USB/ADB e identificato entrambe
le ESP32-S3-EYE. Due controlli individuali del client precedente in ordine A/B
e B/A completano 320 richieste. Aggiunta al runner sperimentale la modalità
`--http-smoke-only`: tre ripetizioni da 20 frame camera per ciascuna delle
quattro varianti RGB565, precedute da input incorporati e warmup. Altre 1.200
richieste completate; 240 frame camera misurati. Verificati senza differenze
65.536 colori RGB565 e input/attivazioni di 100 frame reali.

Tutte le 1.520 risposte hanno punteggi del suffisso identici al replay;
zero errori dispositivo e HTTP 408. Persistono oscillazioni del trasporto:
uno scambio del riferimento impiega 5,2 s, contro circa 0,15 s nel servizio
server. Causa dei precedenti 408 non isolata; nessuna stabilità prolungata
stabilita dalle prove brevi.

Mediane descrittive delle statistiche di tre serie: sola LUT con buffer
trattenuto, ciclo p50 da 438,614 a 322,488 ms (circa -26,5%), cadenza da 2,177
a 2,745 risultati/s e età p95 da 572,467 a 487,465 ms. LUT + rilascio anticipato
riduce ulteriormente il p50, ma peggiora la freschezza e registra un intervallo
fra risultati da 5 s. Nessuna selezione o promozione; confronto completo e
conferma multi-client della variante ancora da eseguire.

Cinque test analizzatore, compilazione Python e build di entrambi i firmware
superati. Backup aggiornati e verificati prima dei flash; firmware originali
e boot confermati alla chiusura. Server spento, seriali libere e inoltro ADB
rimosso. Nessun commit o push.

[Report, statistiche e audit](experiments/esp32_input_camera_benchmark/2026-11-10/report.md)
· [punto di ripresa](RIPRESA_LAVORO.md).

### Seguito del 10 novembre — confronto lungo originale/LUT

Completate tre ripetizioni da 1.000 frame per versione su A, poi 1.000 frame
per versione su ciascuna delle due schede insieme. Criteri individuali e
simultanei superati: mediana dei p50 del ciclo 336,232 → 244,757 ms (-27,2%),
p95 e freschezza entro i margini. Escluse le varianti con rilascio anticipato.

Ora continua interrotta dopo circa 34 minuti: A riceve HTTP 408 per corpo non
ricevuto entro 3 s; B non registra errori nel tratto osservato. Disconnessioni
Wi-Fi di A rilevate soltanto all'avvio, senza coincidenza con il guasto.
Causa non isolata; nessuna promozione al client operativo.

Replay esatto su 23.829 risposte riuscite; 2 terminali 408, il secondo durante
l'arresto. Preservati 5.349/7.225 frame camera di A/B prima dello stop. Durante
il ripristino sequenziale il vecchio runner lasciava B inviare dopo la chiusura
del log: separate 295 risposte successive allo stop, una ancora correlata e
294 senza campione seriale. Corretto l'audit: 240 warmup effettivi, non 534.

Runner corretto per resettare entrambe le schede prima di chiudere i log e
ripristinare; errori di reset/chiusura non saltano i ripristini. Nuovo percorso
verificato staticamente, non con una nuova campagna hardware. Sette test
analizzatore superati. Entrambe le flash originali ripristinate e verificate,
boot confermati, server spento e inoltro ADB rimosso. Nessun commit/push.

[Report lungo e audit](experiments/esp32_input_camera_benchmark/2026-11-10/lut-hold-full-report.md).

### Chiusura concordata del filone LUT

L'utente considera sufficiente la valutazione: LUT utile e numericamente
identica, con beneficio della conversione locale indipendente dalla rete.
Il guadagno end-to-end misurato resta riferito alla configurazione provata.
Timeout probabilmente dovuto al particolare percorso Pixel/hotspot/USB-ADB,
senza causa isolata; nessun altro test di rete richiesto e nessuna ripetizione
automatica dell'ora. Conservati esito interrotto, log e audit. Codice LUT nel
progetto sperimentale; nessuna integrazione nel client operativo eseguita.

## Profilazione per operatore sulla ESP32 — 10 novembre 2026

Creato esperimento separato, senza camera/Wi-Fi/HTTP, sul prefisso INT8
congelato con ESP-NN. Scheda B, tre input fissi, tre round alternati
normale/profilato sulla stessa arena PSRAM: 540 inferenze misurate,
90 warmup, 2.970 record di operatori. Tempo normale 93,762 ms, profilato
93,874 ms, scostamento +0,119%; arena effettiva 229.820 byte.

La prima convoluzione costa 23,439 ms (25,0%), l'espansione 1×1 del nodo 3
18,017 ms (19,2%), il PAD 14,628 ms (15,6%). Gli scope operatori coprono
99,906% di Invoke; entrypoint ESP-NN 82,776%. PAD generico con cicli per
singolo elemento: candidato a futura copia per righe, da verificare
numericamente e misurare; nessuna nuova ottimizzazione applicata.

Attivazioni normali/profilate identiche su dispositivo e identiche alle tre
attivazioni canoniche del precedente firmware ESP32. Il confronto aggiuntivo
con TFLite PC rileva differenze già presenti (massimo 4 livelli INT8):
674/680/587 elementi diversi su 4.608 per i tre input. Primo audit stretto
fallito conservato; audit finale distingue confronto PC e continuità con il
backend ESP32. Nessuna nuova misura di accuratezza né causa numerica isolata.

Cinque test dell'analizzatore superati, build e misure hardware riuscite.
Backup integrale verificato prima del flash; ripristino integrale della
flash originale B verificato e boot originale confermato. Nessun server
avviato, nessun commit/push. Report, CSV, mappa dei tensori e snapshot salvati.

[Report della profilazione](experiments/esp32_layer_profile/2026-11-10/report.md).
