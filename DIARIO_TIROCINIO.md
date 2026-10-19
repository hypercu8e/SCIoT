# Diario del tirocinio SCIoT

Aggiornato il 18 ottobre 2026. Titolo del tirocinio: **Multi Device Split Computing**.
Tirocinio interno da 300 ore, con possibile sviluppo in tesi triennale in Informatica
a UNIMORE, referente prof. Luca Bedogni.

Per una lettura d'insieme di ciò che abbiamo fatto e capito:
[recap del lavoro sul fork](RECAP_LAVORO_FORK.md).

Questo diario ricostruisce le attività dall'inizio del percorso sulla base dei
documenti locali e delle prove conservate. La data amministrativa esatta di inizio
e le ore effettivamente svolte non sono riportate nelle fonti disponibili: non
vengono inventate. Le prime attività tecniche documentate risalgono al 15 ottobre.
Non è un registro ufficiale delle presenze.

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

## Stato e prossime decisioni

- Studio iniziale, modello candidato, split Keras e baseline senza perdita completati.
- Esperimento con perdita definito, implementato ed eseguito; risultati e
  interpretazione conservati insieme al report del 17 ottobre.
- Prova TCP con suffisso Keras in processo separato completata sul PC;
  resta separata dal protocollo SCIoT. Replica DPCM/dead-zone ancora da fare.
- Prima conversione INT8 e confronto con TFLite float32 completati sul PC;
  fedeltà da valutare, nessuna qualità accettabile o compatibilità ESP32 approvata.
- Confronto 16×8 completato sugli stessi dati: fedeltà migliore nelle metriche
  riportate, file e attivazioni più grandi dell'INT8; costi sul target ancora aperti.
- Mancano dataset annotato e più sequenze/split per generalizzare i risultati.
- Nessun riaddestramento, porting del codec nel firmware, benchmark su ESP32,
  emulazione prestazionale, misura di energia o prova di rete reale.
- L'eventuale porting va deciso confrontando il beneficio temporale con la
  compressione indipendente alla stessa qualità e misurandone il costo sul dispositivo.
- Prossimo passo: verificare il supporto INT8/INT16 nel runtime Micro effettivo,
  poi misurare memoria/tempo e verificare lo split sul target. Ampliare calibrazione
  e valutazione su sequenze distinte, senza cercare parametri sul test.
  Conservare float32 come controllo.
- DPCM/dead-zone rimane un confronto successivo da specificare; misurare il
  beneficio temporale sulla rappresentazione scelta senza estendere i numeri
  float32 alle nuove varianti INT8 o 16×8.

Per riprendere: [istruzioni esperimenti](experiments/activation_compression/README.md)
e [scaletta aggiornata](SCALETTA_TIROCINIO.md).
