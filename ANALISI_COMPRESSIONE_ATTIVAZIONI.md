# SCIoT: analisi e spiegazioni della chat sulla compressione delle attivazioni

Consolidato il 17 ottobre 2026, aggiornato il 18 con la prova TCP, il confronto
con il paper di Shiba e le verifiche INT8 e 16×8 sul PC.
La baseline senza perdita rimane quella del 15 ottobre 2026.
Per la cronologia del percorso: [diario del tirocinio](DIARIO_TIROCINIO.md).

Questo documento trascrive in forma ragionata le spiegazioni, le scelte, i risultati
e le domande ancora aperte della chat. Non è il verbale integrale dei messaggi.
Serve a riprendere il lavoro su un'altra macchina senza dipendere dalla chat o da `/tmp`.

## 1. Obiettivo e conclusione raggiunta

Il tirocinio riguarda il **Multi Device Split Computing**. La prima direzione in
esplorazione è ridurre i dati che l'ESP32 invia al server, comprimendo le variazioni
delle attivazioni tra frame consecutivi.

La domanda sperimentale è: il minor traffico compensa il lavoro aggiuntivo e la
memoria necessari sul dispositivo, mantenendo risultati adeguati?

Abbiamo completato un primo esperimento **senza perdita, su PC**, usando un video,
un modello FOMO e uno split fisso. Il vantaggio in byte esiste, ma è modesto:

- il metodo migliore riduce i byte del flusso applicativo del **14,96% rispetto ai
  tensori completi non compressi** a 5 frame al secondo;
- rispetto alla compressione indipendente con lo stesso riordino dei byte, il
  vantaggio aggiuntivo del riferimento temporale è **5,71%**;
- a 1 frame al secondo quest'ultimo vantaggio scende al **2,78%**.

Questi dati non dimostrano ancora un vantaggio di latenza, energia o RAM su ESP32.
Il 17 ottobre abbiamo completato anche una prima prova con perdita controllata,
descritta nella sezione 9.1. A 5 fps e passo 0,001, risparmio sul raw del 40,61%
per l'indipendente e del 48,66% per il temporale: vantaggio temporale 13,57%
a identica ricostruzione. Nessuna cella cambiata alla soglia 0,5 nel video,
ma non è una misura di accuratezza rispetto ad annotazioni.

Il 18 ottobre abbiamo aggiunto una prova TCP con client e server in processi
separati sullo stesso PC. Il temporale risparmia il 13,56% dei byte in salita
rispetto all'indipendente, ma richiede più tempo sia del raw sia dell'indipendente
su questo collegamento locale. Le sezioni 9.2–9.4 spiegano il risultato, il rapporto
con il paper e la proposta di lavoro successiva.

È stata poi completata la verifica INT8 descritta nella sezione 9.5: conversione
integer-only ed esecuzione TFLite sul PC riuscite, file più piccolo del 32,27%
rispetto a TFLite float32. Sui 98 frame separati dalla calibrazione cambiano però
25 celle a soglia 0,5, con 11 celle oggetto perse rispetto alle 99 del riferimento.
La variante è fattibile sul PC, ma non è approvata come baseline di qualità né
validata sul target. La calibrazione va verificata su input più rappresentativi.

Il confronto successivo 16×8 (sezione 9.6), a calibrazione e valutazione invariate,
porta le celle cambiate da 25 a 18 e quelle oggetto perse da 11 a 7, con attivazioni
INT16 e pesi INT8. Il file occupa 69.056 byte e il confine 9.216 byte. Migliora la
fedeltà su questo campione, ma resta da verificare compatibilità e costo sul target.

## 2. Modello, layer, tensore e split

Un modello comprende la struttura della rete e i suoi pesi già addestrati. La
struttura stabilisce quali operazioni vengono eseguite; i pesi contengono ciò che
la rete ha imparato dai dati. Due reti con la stessa struttura possono riconoscere
oggetti diversi se sono state addestrate su dati diversi.

Un **layer** applica una trasformazione. Un **tensore** contiene dati numerici.
Le **attivazioni** sono i risultati intermedi prodotti dai layer.

Esempio semplificato:

```text
immagine -> A -> B -> C -> risultato
```

Si può eseguire A sul dispositivo, inviare la sua uscita al server e proseguire con
B e C. L'uscita inviata è il tensore di attivazioni al punto di split.

`src/server/models/model_split.py` carica un `.h5` Keras, crea un sottomodello per
ciascun layer eseguibile e lo converte in TFLite e in un array C. Riutilizza i pesi:
**non addestra nuove reti**. Questo percorso non equivale automaticamente a
ottenere due parti indipendenti per qualunque punto del grafo.

Il FOMO scaricato contiene connessioni residue con layer `Add`, che combinano
risultati di percorsi diversi. Alcuni tagli richiederebbero più di un tensore di
confine. Abbiamo scelto `block_2_add`, verificando che ai layer successivi serva
solo la sua uscita.

La nostra prova costruisce una prima e una seconda parte con Keras. Non esegue
il percorso TFLite per-layer di SCIoT e non coinvolge due dispositivi o la rete.

## 3. Scelta del modello e prima immagine

Il candidato scelto per gli esperimenti è un FOMO pubblico **Beer vs. cans**:

- progetto: <https://studio.edgeimpulse.com/public/89078/latest>;
- classi mostrate dal progetto pubblico: `beer` e `can`;
- la pagina consultata mostrava 524 immagini e licenza BSD 3-Clause Clear;
- il candidato è anche richiamato dalla documentazione ufficiale FOMO;
- file scaricato nella radice del repository:
  `ei-object-detection-with-fomo---bottles-vs.-cans-object-detection-keras-h5-model-model.5.zip`.

Lo ZIP contiene `model.h5`, 266.128 byte. Il file ispezionato è un modello Keras
Functional esportato con Keras 2.7.0, con 60 layer incluso l'ingresso, 59 layer di
elaborazione e 20.499 parametri. Le classi e il loro ordine non sono inclusi nello
ZIP: l'associazione dei canali a `beer` e `can` è stata ricavata dal progetto
pubblico, e rimane da confermare per l'esportazione dell'utente.

Questo modello è un **candidato sperimentale**, non una scelta definitiva per
un'applicazione di detection. È distinto dal modello originariamente incluso in
SCIoT, del quale non erano state identificate le etichette.

### Ingresso e uscita

```text
Ingresso di un frame: (1, 96, 96, 1)
                      ^          ^
                   un frame    grigio

Uscita del modello:  (1, 12, 12, 3)
```

L'uscita è una griglia di 12 x 12 celle con punteggi per sfondo e due classi.
FOMO stima i centri degli oggetti; non produce direttamente rettangoli precisi
che descrivano le dimensioni reali degli oggetti.

Un'immagine può essere fornita a una risoluzione diversa. Va però preparata nel
modo atteso dal modello. Abbiamo usato ritaglio quadrato centrale, ridimensionamento
Lanczos a 96 x 96, grigio BT.601 e normalizzazione in [0,1]. Non è stata verificata
la parità pixel per pixel con Edge Impulse Studio.

Il convertitore di SCIoT supporta il ridimensionamento, ma il percorso esistente
usa RGB come impostazione predefinita. Non adatta automaticamente il firmware e
il server a questo diverso modello in scala di grigi.

### Risultato su `canCoke.jpeg`

La foto è 365 x 547 pixel e mostra una lattina tenuta in mano. L'inferenza completa
sul PC è riuscita; in tutte le celle prevaleva lo sfondo. Il massimo dei canali
oggetto era circa 0,112, sotto la soglia di prova 0,5. Non abbiamo quindi ottenuto
una rilevazione della lattina.

Gli script e le immagini di questa primissima prova erano in `/tmp/sciot-can-check/`
e non sono più disponibili al controllo del 17 ottobre. Questo paragrafo conserva
il risultato riportato nella chat; non lo presenta come una nuova prova eseguita
il 17 ottobre. L'estrazione video e il confronto successivi hanno invece script
permanenti e risultati salvati nel repository.

### Perché la foto non decide l'esito del tirocinio

Un modello addestrato per una telecamera fissa e oggetti di dimensioni simili
nell'immagine può funzionare male con un oggetto in primo piano, inclinato,
parzialmente coperto da una mano o su uno sfondo diverso. Il nome `beer` non
garantisce il riconoscimento di qualunque bottiglia, ad esempio una bottiglia
d'acqua. Il modello va valutato rispetto allo scenario e al dataset previsti.

Questi test sono utili per la detection, ma il nostro obiettivo attuale è la
compressione delle attivazioni. Per misure senza perdita possiamo verificare la
ricostruzione esatta dei tensori anche quando il riconoscitore è mediocre.
Per valutare la qualità di una compressione con perdita occorre invece distinguere
la somiglianza rispetto all'uscita originale dall'accuratezza su annotazioni corrette.
Un modello che produce sempre sfondo sarebbe un riferimento poco informativo per
valutare il mantenimento delle rilevazioni.

## 4. Si può migliorare il riconoscitore con più dati? E con RL?

Si può continuare l'addestramento del modello con immagini annotate, aggiornando
i pesi esistenti: è il fine-tuning. Servono varietà e pertinenza delle scene, non
soltanto tanti frame quasi identici. È utile includere anche scene senza gli oggetti
cercati. Il miglioramento va verificato su dati separati da quelli di addestramento.

A parità di architettura, aumentare le immagini di addestramento non aumenta il
numero dei parametri della rete. Può migliorare i pesi, entro i limiti della capacità
del modello, ma non garantisce un miglioramento automatico.

Il **reinforcement learning (RL)** apprende quali azioni scegliere attraverso le
ricompense ottenute interagendo con un ambiente. Per migliorare questo riconoscitore
il percorso naturale è l'apprendimento supervisionato: immagini e annotazioni
corrette. In questa chat non è stato effettuato alcun riaddestramento, né RL.

## 5. Video e attivazioni: un tensore per frame?

Sì: **ogni frame elaborato produce un tensore al punto di split scelto**. Il video
originale può contenere più frame di quelli che decidiamo di elaborare.

Il video fornito, `VideoWithCan.mp4`, dura circa 29,26 secondi, è 474 x 850 pixel
e contiene 861 frame, con una frequenza media di circa 29,43 fps. Abbiamo ottenuto:

- 146 frame campionati a 5 fps;
- 30 frame nel sottoinsieme a 1 fps, ottenuto prendendo un frame ogni cinque dal
  campione precedente.

Le scelte di campionamento sono impostazioni dell'esperimento, non una velocità
misurata o emulata dell'ESP32. I tempi salvati sono quelli nominali della griglia
di campionamento del filtro `fps` di FFmpeg.

Al punto `block_2_add` il tensore ha forma `24 x 24 x 8`:

```text
24 * 24 * 8 = 4.608 valori
4.608 * 4 byte per float32 = 18.432 byte per frame

Intera sequenza salvata: (146, 24, 24, 8)
                         ^
                      asse dei frame
```

Abbiamo conservato tutti i tensori per analizzarli. In un codec in streaming sono
necessari il tensore corrente e il riferimento precedente, oltre ai buffer di
lavoro; non occorre conservare l'intera sequenza.

Su tutti i 146 frame, modello completo e prima parte seguita dalla seconda parte
hanno dato una **differenza numerica massima osservata pari a 0,0**. Questo verifica
lo split Keras sul PC per questi input; non dimostra il corretto funzionamento
del firmware, dei sott modelli TFLite o del trasporto di SCIoT.

## 6. Cosa significa comprimere le differenze

Un tensore più simile al precedente potrebbe essere rappresentato attraverso un
aggiornamento più compatto. Tuttavia:

- appiattire un tensore cambia la forma, non i byte;
- sottrarre due tensori produce ancora un tensore, senza ridurre automaticamente
  il numero di elementi o i byte;
- anche differenze piccole devono essere codificate in modo economico;
- vanno contati riferimenti iniziali, indici, intestazioni e altri metadati.

Nella sequenza studiata, a questo split e con questi campionamenti, nessun valore
era esattamente uguale al corrispondente valore del frame precedente. Quindi non
basta inviare soltanto pochi elementi cambiati. Ciò non esclude altre codifiche.

### Sottrazione numerica e arrotondamenti

In float32 l'operazione `precedente + (corrente - precedente)` non garantisce la
ricostruzione degli stessi bit. Nel controllo a 5 fps, 21.868 valori su 668.160
confrontati differivano; errore assoluto massimo circa `4,77e-7`. A 1 fps i valori
diversi erano 8.239 su 133.632, con lo stesso massimo osservato.

Questo è un controllo di sottrazione/somma su una singola transizione usando il
precedente originale, non un codec predittivo con perdita e riferimento aggiornato.
Un errore piccolo può essere accettabile in una prova con perdita, ma non permette
di chiamare la codifica senza perdita.

Abbiamo provato anche differenze calcolate e trasmesse in float64. Il codice
controlla la reversibilità sui dati effettivi e torna al completo se necessario:
neppure float64 garantisce reversibilità per ogni combinazione possibile di float32.

### XOR

XOR confronta i bit: produce 0 dove sono uguali e 1 dove sono diversi.

```text
Precedente: 10110010
Corrente:   10110110
XOR:        00000100

Precedente XOR aggiornamento = Corrente
```

È reversibile quando entrambe le parti possiedono lo stesso riferimento. XOR da
solo mantiene lo stesso numero di bit, ma la sequenza ottenuta può comprimersi
meglio con zlib. Non è la sottrazione numerica delle attivazioni.

### Riordino dei byte, o byte shuffle

Ogni float32 occupa quattro byte. Possiamo raggruppare tutti i primi byte dei valori,
poi tutti i secondi, e così via. È una permutazione reversibile. Può aiutare il
compressore a trovare regolarità. Per attribuire correttamente il vantaggio al
riferimento temporale, abbiamo provato lo stesso riordino anche sul tensore completo.

## 7. Confronto senza perdita: metodi, protocollo e risultati

Gli script permanenti sono in [experiments/activation_compression](experiments/activation_compression/README.md).
Il compressore di riferimento è zlib, livello 1, con finestra predefinita da 32 KiB.
Non è stato validato come scelta adatta alla RAM disponibile sull'ESP32.

I metodi differenziali inviano un completo iniziale e un completo ogni 5 secondi.
Negli altri frame confrontano il payload completo e quello differenziale, scegliendo
il più piccolo. Se comprimere il completo espande i dati, inviano il completo raw.
Il riferimento è l'ultimo tensore ricostruito, uguale byte per byte all'originale
in questa prova senza perdita.

Le dimensioni riportate includono:

- un'intestazione di sessione serializzata con forma, dtype, hash del modello,
  split, campionamento e parametri del codec;
- 24 byte di header per frame: firma, versione, codifica, flags, sequenza,
  identificatore del riferimento, lunghezza del payload e CRC32 del tensore;
- payload, wrapper/checksum zlib e invii completi di inizializzazione/rinnovo.

Questo formato è un prototipo sperimentale. Non è il protocollo binario esistente
di SCIoT. Non sono inclusi header Wi-Fi/TCP/MQTT/HTTP/WebSocket, ritrasmissioni,
connessioni, immagini eventualmente inviate a parte o altri messaggi del sistema.
Il file NPY è un contenitore per l'analisi, non il formato trasmesso nel confronto.

### 146 frame a 5 fps

| Metodo | Byte totali | Riduzione rispetto al raw |
|---|---:|---:|
| Tensori completi raw | 2.694.815 | 0,00% |
| Completi + zlib | 2.508.837 | 6,90% |
| Differenze numeriche float64 + zlib, con ritorno al completo | 2.508.837 | 6,90% |
| XOR + zlib | 2.401.249 | 10,89% |
| Completi + riordino byte + zlib | 2.430.375 | 9,81% |
| XOR + riordino byte + zlib | 2.291.562 | 14,96% |

L'header di sessione è 239 byte. I sei rinnovi programmati comprendono il primo
frame. Il metodo XOR con riordino sceglie 137 frame differenziali e nove completi,
compresi rinnovi e ritorni al completo.

Il candidato numerico float64 non viene scelto in nessuno dei 140 aggiornamenti
possibili: occupa sempre più del completo compresso. Il ritorno al completo evita
di peggiorare i byte trasmessi, ma comporta lavoro aggiuntivo. Questo risultato
riguarda tale codifica, non ogni possibile codifica delle differenze numeriche.

### 30 frame a 1 fps

| Metodo | Byte totali | Riduzione rispetto al raw |
|---|---:|---:|
| Tensori completi raw | 553.918 | 0,00% |
| Completi + zlib | 515.760 | 6,89% |
| Differenze numeriche float64 + zlib, con ritorno al completo | 515.760 | 6,89% |
| XOR + zlib | 504.339 | 8,95% |
| Completi + riordino byte + zlib | 499.607 | 9,80% |
| XOR + riordino byte + zlib | 485.721 | 12,31% |

L'header di sessione è 238 byte. Il vantaggio aggiuntivo del riferimento temporale
si calcola confrontando XOR e completo con lo stesso riordino:

```text
5 fps: 1 - 2.291.562 / 2.430.375 = 5,71%
1 fps: 1 -   485.721 /   499.607 = 2,78%
```

Queste sono percentuali relative ai rispettivi controlli, non punti percentuali
da sommare direttamente ai risparmi rispetto al raw.

### Tempi, memoria e verifiche

Ogni codec è stato eseguito tre volte. I tempi sono la mediana delle tre medie per
frame. A 5 fps, XOR con riordino ha richiesto circa **0,58 ms/frame in codifica** e
**0,10 ms/frame in decodifica** sul PC. Il completo con lo stesso riordino ha
richiesto circa 0,33 e 0,11 ms/frame rispettivamente.

Questi sono tempi del codec Python, inclusi selezione adattiva e CRC. Escludono
inferenza, preparazione iniziale dei byte, file e rete. **0,58 ms non è il tempo
dell'inferenza della rete neurale.**

Ogni lato di un metodo differenziale necessita di un riferimento da 18.432 byte.
È un requisito minimo di stato, non una misura del picco di RAM: mancano workspace
del compressore, buffer temporanei, modello, tensor arena e runtime.

La ricostruzione di ogni frame in ogni ripetizione è stata confrontata byte per
byte con l'originale. I sei test verificano anche pattern di bit particolari,
zero con segno, corruzione, duplicati, messaggi troncati, perdita di un delta e
recupero tramite un nuovo completo. Sono test del prototipo, non della rete reale.

## 8. PC, ESP32 e compressione nel framework attuale

Tutta l'inferenza e la compressione della prova sono eseguite sulla CPU del PC.
`CUDA_VISIBLE_DEVICES=-1` seleziona l'esecuzione CPU. Non abbiamo emulato o rallentato
il processore per simulare un ESP32.

A parità degli stessi tensori e dello stesso codec, il numero di byte non dipende
dalla velocità del processore. I tempi cambiano; inoltre un ESP32 può elaborare
frame più distanti nel tempo. TFLite e operatori diversi possono produrre valori
numericamente diversi: questi dati non garantiscono gli stessi payload sul target.

Nel percorso SCIoT controllato, il client copia `output->data.f` nel messaggio
binario e il server legge i valori float32 direttamente: in quel percorso non
c'è compressione applicativa delle attivazioni. I codec indipendente e temporale
sono esperimenti separati sotto `experiments/activation_compression/`.
Riferimenti nel codice:

- `src/client/esp32-s3-eye-mqtt/src/main.cpp`, copia dell'uscita nel messaggio;
- `src/server/communication/request_handler.py`, parsing di `layer_output`.

Non esiste una regola universale secondo cui ogni sistema comprime i tensori.
La quantizzazione del modello, per esempio con attivazioni int8, è una scelta
numerica distinta dalla compressione del messaggio; le due possono essere combinate.
Le prove di compressione delle sezioni 7 e 9.1–9.2 usano float32 e non hanno
quantizzato il modello. La conversione della rete INT8 è una prova successiva,
separata, descritta nella sezione 9.5.

## 9. Perdita controllata: spiegazione e prima implementazione

Il seguente esempio conserva la spiegazione iniziale; la prova effettivamente
eseguita il 17 ottobre usa la griglia uniforme descritta nella sezione 9.1.

Si può scegliere di approssimare differenze piccole per ottenere più zeri o meno
valori distinti da codificare. Esempio concettuale:

```text
Riferimento:           1,2000
Valore corrente:       1,2007
Differenza:            0,0007
Soglia ipotetica:      0,001
Differenza codificata: 0
Valore ricostruito:    1,2000
Errore:                0,0007
```

Il tensore ricostruito sarebbe diverso. La soglia dell'esempio non è stata
selezionata o validata sperimentalmente e non coincide automaticamente col passo
usato nella nuova prova. L'accettabilità dell'errore per l'applicazione resta aperta.

"Controllata" significa definire esplicitamente soglie e codifica, misurare errore
nelle attivazioni e cambiamenti dell'uscita della rete, ed eventualmente valutare
le rilevazioni su annotazioni corrette. Un piccolo errore nel tensore non garantisce
automaticamente rilevazioni invariate.

Client e server devono usare lo **stesso riferimento ricostruito** per l'aggiornamento
successivo. Usare sul client il precedente originale e sul server un'approssimazione
può desincronizzare il calcolo. Rimangono necessari identificatori di sequenza e
riferimento, rinnovi completi e recupero dopo errori o cambio di split.

Abbiamo ora confrontato compressione indipendente e differenziale a pari precisione,
misurando byte ed errore insieme. La convenienza su ESP32 rimane una domanda
sperimentale anche dopo buoni risultati preliminari sul PC.

L'idea di saltare del tutto i frame simili è un'altra pista, conservata in
[IDEE_DA_ESPLORARE.md](IDEE_DA_ESPLORARE.md), non implementata nella prova attuale.

### 9.1 Prova eseguita il 17 ottobre 2026

Abbiamo rigenerato le attivazioni dal video sulla macchina attuale, verificato i
checksum degli input e lo split Keras (massimo errore osservato 0,0 su 146 frame).
I tensori rigenerati hanno un hash diverso da quelli del 15 ottobre: la nuova prova
confronta tutti i metodi sugli stessi nuovi tensori e conserva controlli senza
perdita misurati nella stessa esecuzione. I tempi storici non sono stati sostituiti.

Quantizzazione uniforme: `q = rint(float64(x)/passo)` in int32, senza clipping;
ricostruzione `float32(q*passo)`. Passi esplorati: 0,0001, 0,001, 0,01, 0,1, 0,5, 1.
Limite d'errore per valore: circa mezzo passo, più arrotondamenti numerici,
verificato su tutti i dati. La rete resta float32; non è una conversione INT8.

Indipendente: q completo compresso con byte shuffle e zlib livello 1.
Temporale: differenza intera di q corrente e precedente, stesso shuffle e zlib.
Il riferimento intero corrisponde alla stessa attivazione ricostruita sui due lati;
non deriva dal precedente float originale. Completo iniziale e ogni 5 secondi;
scelta del payload minore e fallback raw. I due metodi ricostruiscono gli stessi
tensori approssimati: il confronto in byte è a qualità identica.

| Passo, a 5 fps | Riduzione indipendente/raw | Riduzione temporale/raw | Vantaggio temporale/indipendente | Celle cambiate a soglia 0,5 |
|---|---:|---:|---:|---:|
| 0,001 | 40,61% | 48,66% | 13,57% | 0 |
| 0,01 | 52,50% | 57,47% | 10,48% | 1 |
| 0,1 | 60,79% | 68,28% | 19,09% | 2 |
| 0,5 | 67,81% | 79,01% | 34,78% | 49 |

Le 151 celle oggetto del riferimento su 21.024 celle-frame non sono 151 oggetti
distinti. Le metriche scelgono la classe oggetto col punteggio maggiore sopra
soglia; non applicano componenti connesse o altro postprocessing FOMO. Sono proxy
di fedeltà al modello originale, non accuratezza su etichette corrette. Con passo
0,5 vengono perse 20 celle e introdotte 29: il risparmio maggiore ha un costo
osservabile. Anche il massimo errore sui punteggi, non solo la media, va valutato.

Il riferimento delle metriche è il suffisso eseguito sulle attivazioni originali
con gli stessi batch delle approssimazioni; la parità col modello completo è
verificata entro tolleranza e gli scarti numerici sono registrati. Nessuna soglia
è stata dichiarata accettabile per l'applicazione. Un video/split e l'assenza di
annotazioni non consentono di generalizzare o di scegliere una precisione definitiva.

Il protocollo AQST/AQF1 è distinto dalla baseline ACT1 e da SCIoT; conta sessione,
header da 24 byte, checksum sugli interi, wrapper e rinnovi. Restano esclusi rete
reale, picco RAM, energia e tempi ESP32. Il riferimento occupa ancora 18.432 byte
per lato, oltre a workspace e temporanei. Tutti i 15 test dei prototipi passano.

Risultati completi a 5 e 1 fps, ambiente, hash e istruzioni:
[lossy_2026-10-17](experiments/activation_compression/lossy_2026-10-17/README.md).

### 9.2 Cosa abbiamo misurato con il client e il server TCP — 18 ottobre

Prima distinguiamo le operazioni. Per ogni immagine elaborata dalla prima parte
della rete otteniamo un tensore di attivazioni. Possiamo inviarlo in tre modi:

| Modalità | Cosa prepara il client | Cosa occorre al server |
|---|---|---|
| Raw | Tutti i valori float32, senza compressione | Il messaggio e i parametri di sessione |
| Indipendente | Il tensore corrente arrotondato e compresso | Il messaggio e i parametri di sessione |
| Temporale attuale | Le differenze intere compresse rispetto al tensore arrotondato precedente; un completo quando necessario o più piccolo | Anche il riferimento precedente se arriva una differenza |

Nell'indipendente ogni tensore viene compresso e inviato quando è disponibile:
non si inviano due tensori insieme per comprimere la coppia. Per ricostruire il
secondo non serve conservare il primo. Nel temporale, invece, il server somma
le differenze al riferimento condiviso. La sottrazione da sola non riduce i byte;
il vantaggio dipende da quanto il compressore riesce a codificare quelle differenze.
Temporale e perdita sono scelte distinte: esiste anche la baseline temporale
senza perdita descritta nella sezione 7.

La nuova prova riproduce le attivazioni già salvate e usa un server separato che
esegue il suffisso Keras. Entrambi i programmi girano sullo stesso computer:
TCP loopback trasferisce i messaggi attraverso il sistema operativo, senza Wi-Fi.
Per il campione di 146 frame confrontiamo i tre metodi, tre volte ciascuno,
con una riconnessione volontaria prima del frame 73. Sono 1.314 richieste e 18
connessioni. A ogni riconnessione ripartono sessione, sequenza e riferimento.

| Metodo | Byte applicativi client → server | Risparmio sul raw | Tempo tipico di codifica + scambio + suffisso |
|---|---:|---:|---:|
| Raw | 2.696.760 | 0% | 0,673 ms/frame |
| Indipendente, passo 0,001 | 1.602.438 | 40,58% | 1,181 ms/frame |
| Temporale, passo 0,001 | 1.385.197 | 48,63% | 1,483 ms/frame |

I tempi sono la mediana dei tre p50 per metodo, non il tempo di ogni singolo frame.
Il cronometro parte dal tensore già disponibile, prima della codifica, e si ferma
alla ricezione della risposta: include invio, decodifica, inferenza del suffisso,
hash e risposta. Esclude camera, prefisso della rete, file, caricamento/compilazione
iniziale del modello, handshake e verifica locale del client. Il server restituisce
anche 261.146 byte per metodo e giro, conteggiati separatamente. I conteggi includono
il formato applicativo, escludono header TCP/IP e ritrasmissioni.

**Più lento rispetto a cosa?** Il temporale ha richiesto più tempo sia del raw sia
dell'indipendente. Comprimere, decomprimere e gestire le differenze richiede calcolo;
inoltre il prototipo temporale prova completo e differenza per scegliere il minore.
Sul loopback trasferire pochi kilobyte costa così poco che il risparmio nel
trasferimento non compensa quel lavoro. Su una rete lenta il bilancio potrebbe
cambiare; questo esperimento non lo misura e non riproduce il costo CPU dell'ESP32.

Verificati tutti i tensori tramite hash, le uscite raw rispetto all'estrazione e
l'identità byte per byte tra le uscite indipendenti e temporali a pari passo.
Nessuna cella cambiata a soglia 0,5 nel campione, senza annotazioni. I 20 test sono
passati. La riconnessione è tra frame confermati: non prova recupero automatico
da guasti durante un messaggio.

Artefatti e riproduzione: [tcp_2026-10-18](experiments/activation_compression/tcp_2026-10-18/README.md).
Gli hash degli input differiscono dalla prova con perdita del 17: sono esecuzioni
distinte, non numeri intercambiabili.

### 9.3 Risultati del paper e differenze dal nostro metodo

Riferimento: **Delta Coding With Dead-Zone Quantization for Bandwidth-Efficient
Split Computing on Video Streams**, Shiba et al., IEEE Access 2026,
[DOI](https://doi.org/10.1109/ACCESS.2026.3690477).

- **VI-B:** DPCM conserva la classe del modello originale altrettanto bene o meglio
  dell'indipendente in 472/480 configurazioni. Il 98,3% conta configurazioni,
  non predizioni corrette; top-1 agreement misura accordo col modello originale.
- **VI-C:** D+DZ riduce l'entropia in 31/36 configurazioni; è comprimibilità teorica,
  non una percentuale di byte risparmiati. Zlib conferma l'ordinamento in tutti i
  12 casi a 4 bit e 11/12 a 8 bit. Le analisi dei delta usano il modello ideale
  DnD, distinto dal DPCM pratico.
- **VII-E.3/5/7:** classificazione su una macchina; niente validazione su ESP32,
  collegamenti reali, latenza complessiva o perdite/ritardi di rete.
- **III-B–D:** DPCM quantizza il residuo rispetto alla ricostruzione precedente;
  D+DZ amplia la fascia centrale mappata a zero. Il nostro codec quantizza prima
  il tensore e poi codifica differenze intere esatte: non replica D+DZ.

Verifica sul [PDF primario](https://da.lib.kobe-u.ac.jp/da/kernel/0100504251/0100504251.pdf)
del 18 ottobre 2026; V-C definisce le metriche. La fonte motiva il confronto,
senza dimostrare la convenienza sul nostro sistema.

### 9.4 Prossimo esperimento proposto: confronto con DPCM e dead-zone

**Priorità aggiornata il 18 ottobre:** prima di ampliare i codec, verificare
la rappresentazione quantizzata del modello (sezioni 9.5–9.6). Il confronto DPCM/dead-zone
rimane un approfondimento successivo, non ancora implementato.

**Domanda:** sul nostro FOMO, quantizzare le differenze rispetto al riferimento
ricostruito offre un compromesso byte/errore migliore del metodo già provato?

Il primo passo è una spiegazione numerica e una specifica breve: cosa conserva
ciascun lato, quale differenza calcola, come la arrotonda e come aggiorna il
riferimento. Definire anche intervallo, clipping, arrotondamento e invio dei
parametri. Non dare per equivalenti un passo fisso e un numero di bit fissato.
Con lo stesso passo fisso, senza clipping e con riferimento sulla stessa griglia,
quantizzare il residuo può ricostruire gli stessi valori della quantizzazione
diretta, salvo dettagli di arrotondamento. Il solo cambio d'ordine non garantisce
un vantaggio: specificare quali intervalli, precisioni e dead-zone cambiano.

Poi, in un nuovo esperimento isolato, mantenere lo stesso modello, lo split
`block_2_add` e gli stessi input per tutti i metodi. Conservare il codec attuale
come baseline e introdurre separatamente:

1. DPCM con quantizzazione uniforme del residuo, prima di aggiungere dead-zone.
2. DPCM con dead-zone, mantenendo identiche le altre scelte del nuovo confronto.

Confrontare anche raw e quantizzazione indipendente con parametri dichiarati.
Non basta applicare lo stesso numero di bit: verificare byte effettivi ed errore
ottenuto. Per metodi con ricostruzioni diverse valutare curve byte/errore, senza
richiedere l'identità tra i loro tensori. Documentare come vengono scelti gli
intervalli di quantizzazione: se si usano dati di calibrazione, separarli dai dati
di valutazione; se i parametri cambiano, contarne la trasmissione.

**Controlli prima delle prestazioni:** riferimenti client/server identici, errore
misurato sul tensore corrente senza deriva da stati diversi, rinnovi completi,
sequenze e recupero dopo perdita dello stato. Non assumere il limite mezzo passo
del vecchio codec quando si introducono dead-zone o clipping.

**Risultati richiesti:** byte inclusi metadati/rinnovi, tempi del codec sul PC,
errore massimo e medio su tensori e punteggi, celle perse/introdotte e cambi di
classe rispetto al raw. Queste ultime restano proxy senza annotazioni.
Prima prova sul video disponibile per controllare il funzionamento; poi scene
diverse e dati annotati per valutare robustezza e accuratezza delle rilevazioni.

Solo dopo questa scelta provare lo scambio TCP del nuovo metodo ed eventuali
limiti di banda dichiarati. Una prova di rete controllata su PC non è un benchmark
ESP32: tempi e picco di memoria del codec sulla scheda vanno misurati separatamente,
inizialmente anche riproducendo attivazioni registrate.

È una proposta di adattamento a FOMO, non una riproduzione completa degli
esperimenti del paper. DPCM e dead-zone non sono stati implementati in questo
aggiornamento documentale; nessuna nuova configurazione è stata approvata come
qualità accettabile per l'applicazione.

### 9.5 Verifica INT8 del modello — 18 ottobre

**Domanda verificata:** il FOMO candidato già addestrato può essere convertito
in un modello TFLite integer-only ed eseguito sul PC, e quanto cambiano le sue
predizioni? Nessun riaddestramento o modifica dell'architettura.

Codice riproducibile: [check_int8.py](experiments/activation_compression/check_int8.py).
Artefatti: [int8_2026-10-18](experiments/activation_compression/int8_2026-10-18/README.md).
Modello e preprocessing sono quelli identificati dagli hash degli input esistenti.
Primi 48 frame (indici 0–47) per calibrazione, successivi 98 (48–145) per
valutazione. Nessun frame di valutazione entra nella calibrazione. Sono comunque
campioni temporalmente correlati dello stesso video, senza annotazioni: questa
prova non dimostra generalizzazione o accuratezza sulle classi reali.

Si converte prima TFLite float32 come controllo, poi INT8 con pesi e attivazioni
quantizzati, ingresso/uscita int8 e operatori `TFLITE_BUILTINS_INT8`. Il modello
intero viene eseguito su CPU con i delegati predefiniti disabilitati. I tensori
sono conservati per ispezionare anche `block_2_add`; non si misurano latenza o RAM.
L'uscita Keras ricalcolata coincide con quella salvata negli input su tutti i frame.

| Misura | TFLite float32 | TFLite INT8 |
|---|---:|---:|
| Dimensione file | 84.292 byte | 57.088 byte |
| Tipo ingresso/uscita | float32 | int8 |
| Soli valori al confine `block_2_add` | 18.432 byte | 4.608 byte |
| Errore assoluto massimo sui punteggi rispetto a Keras | 0,00000310 | 0,289446 |
| MAE sui punteggi | 0,0000000296 | 0,00223682 |
| Celle cambiate a soglia 0,5 | 0 / 14.112 | 25 / 14.112 |
| Celle oggetto perse / introdotte rispetto a Keras | 0 / 0 | 11 / 14 |

Il file INT8 si riduce del **32,27%**, non del 75%: la dimensione del file
comprende anche strutture e parametri di quantizzazione. Il **75%** si riferisce
ai soli valori del tensore al confine, di forma `(1, 24, 24, 8)`; non è una misura
del traffico SCIoT o del picco di RAM della scheda.

L'accordo globale a soglia 0,5 è 99,82%, ma lo sfondo domina il conteggio. Il
riferimento ha solo 99 celle oggetto: ne vengono perse 11 (11,11%), ne compaiono
14 e non cambia la classe nelle celle che restano oggetto. L'IoU delle celle di
primo piano con classe coincidente è circa 0,779. Sono confronti con il modello
originale, non oggetti distinti, falsi positivi/negativi su annotazioni o risultati
del postprocessing FOMO. Le soglie 0,25 e 0,75 sono conservate nel JSON.

Il confine INT8 osservato ha scala `0.06843240559101105` e zero point `-20`;
ricostruzione `float32((q - zero_point) * scale)`. Il suo errore incorpora anche
le operazioni INT8 precedenti, non solo l'arrotondamento di quel tensore.
162 valori di ingresso su 903.168 vengono effettivamente tagliati ai limiti INT8.
Non è stata identificata la causa delle variazioni nelle predizioni.

**Controlli riusciti:** conversione senza fallback float, allocazione e inferenza
desktop su entrambi i file. INT8 contiene solo tensori int8/int32; operatori
`CONV_2D` v3, `DEPTHWISE_CONV_2D` v3, `ADD` v2, `PAD` v2 e `SOFTMAX` v2.
Gli int32 includono bias e forme. Il ricaricamento dei file salvati e la
ricomputazione delle uscite sono verificati separatamente da `verify_int8.py`.
I 19 test locali senza socket comprendono quattro nuovi controlli sulla mappatura
INT8, clipping e separazione calibrazione/valutazione.

**Limiti e prossima decisione:** INT8 è fattibile sul PC, ma questa configurazione
non viene promossa a baseline di qualità. Prima verificare la calibrazione con
input rappresentativi aggiuntivi separati dalla valutazione; non cercare parametri
sul campione di test. Non sono richieste etichette per calibrare. Le annotazioni
servono invece per misurare l'accuratezza reale, quando disponibili.

La compatibilità con il runtime Micro del firmware resta da provare con build,
allocazione e `Invoke` sulla scheda. Lo split INT8 non è stato esportato come
prefisso/suffisso separati: occorre verificare scale/zero point coerenti al confine
e adattare il protocollo che oggi assume float32. Nessun porting o integrazione
ESP-NN, benchmark ESP32, rete, energia o misura di memoria è stato eseguito.
La rappresentazione scelta diventerà poi il controllo per i nuovi codec:
i risparmi temporali misurati su float32 non si trasferiscono automaticamente a INT8.

### 9.6 Confronto 16×8 con i controlli float32 e INT8 — 18 ottobre

Su richiesta dell'utente abbiamo provato attivazioni INT16 e pesi INT8, senza
riaddestrare. È distinto da float16 e dalla sola quantizzazione dei messaggi.
Codice: [check_16x8.py](experiments/activation_compression/check_16x8.py).
Risultati e riproduzione: [16x8_2026-10-18](experiments/activation_compression/16x8_2026-10-18/README.md).

Stessi hash di modello/input, preprocessing e partizione: 48 frame calibrano,
98 vengono valutati. Sono frame disgiunti ma dello stesso video; nessuna ricerca
di parametri sui dati di valutazione. Float32 e INT8 sono gli stessi binari della
prova precedente, ricaricati: uscite e metriche coincidono con l'archivio.
Solo 16×8 viene convertito, con il set sperimentale integer-only, ingresso e
uscita INT16. Verificati pesi INT8 e bias INT64 in tutte le convoluzioni, senza
fallback float. Non è una conversione di tutti i numeri del modello a 16 bit.

| Misura sui 98 frame | TFLite float32 | INT8 | 16×8 |
|---|---:|---:|---:|
| Byte del file | 84.292 | 57.088 | 69.056 |
| Byte dei soli valori al confine | 18.432 | 4.608 | 9.216 |
| Max errore sui punteggi rispetto a Keras | 0,00000310 | 0,289446 | 0,285753 |
| MAE sui punteggi | 0,0000000296 | 0,00223682 | 0,000776675 |
| Celle cambiate a soglia 0,5 | 0 | 25 | 18 |
| Celle oggetto perse / introdotte | 0 / 0 | 11 / 14 | 7 / 11 |
| IoU delle celle di primo piano con classe coincidente | 1 | 0,779 | 0,836 |

Il riferimento ha 99 celle oggetto su 14.112 celle-frame: per 16×8 ne vengono
perse 7 (7,07%) rispetto alle 11 di INT8. Il risultato migliora nelle metriche
riportate, ma il massimo scostamento resta circa 0,286. Sono proxy di fedeltà
nelle celle, senza annotazioni o postprocessing FOMO, non accuratezza sugli oggetti.
Non attribuiamo a una causa specifica gli errori residui senza una prova dedicata.

Il file 16×8 si riduce del 18,08% rispetto a TFLite float32, meno di INT8. Il
50% al confine riguarda i soli valori del tensore, non il file o la RAM totale.
Il confine INT16 ha scala `0.00030756735941395164` e zero point `0`; i tipi nel
modello sono int16/int8/int64/int32. Operatori/versioni: `CONV_2D` v3,
`DEPTHWISE_CONV_2D` v3, `ADD` v2, `PAD` v2 e `SOFTMAX` v2. La stessa versione di
un operatore non certifica che il runtime Micro supporti anche i suoi tipi INT16.

Verificati allocazione e inferenza CPU, hash delle uscite dei controlli, tipi
delle convoluzioni e ricaricamento dei binari in un percorso separato. Passati
23 test senza socket, inclusi quattro nuovi controlli sul range INT16 e sulla
coerenza della mappatura INT8. Gli archivi e i sorgenti precedenti sono conservati.

**Prossimo passo:** verificare il supporto delle varianti INT8/INT16 nel runtime
Micro effettivo prima del porting, poi misurare memoria/tempo e verificare lo
split sulla scheda. Ampliare calibrazione e valutazione su sequenze distinte per
generalizzare. Nessuna variante è approvata come qualità accettabile; nessuna
misura ESP32 o integrazione del protocollo quantizzato è stata eseguita.

## 10. File da conservare e ripresa su un'altra macchina

### Documenti e risultati stabili

- Questo documento: spiegazioni e stato dell'intera chat.
- [SCALETTA_TIROCINIO.md](SCALETTA_TIROCINIO.md): percorso di lavoro aggiornato.
- [README dell'esperimento](experiments/activation_compression/README.md): script e comandi.
- [Copia dei risultati del 15 ottobre](experiments/activation_compression/baseline_2026-10-15/README.md):
  JSON, CSV, metadati, ambiente e report salvati fuori dalla directory ignorata `results/`.
- [Prova con perdita del 17 ottobre](experiments/activation_compression/lossy_2026-10-17/README.md).
- [Prova TCP del 18 ottobre](experiments/activation_compression/tcp_2026-10-18/README.md):
  report, CSV, JSON, test e checksum; i valori sono una misura storica su PC.

Al primo consolidamento del 17 ottobre questi file erano ancora locali. Ora la
baseline e i documenti iniziali risultano nei commit locali `d38a489` e `087fef9`;
la prova con perdita è nel commit locale `78eac02`. La prova TCP del 18 ottobre e
questo aggiornamento documentale sono modifiche locali non ancora in un commit.
Non è stata verificata la corrispondenza con il remoto. `results/` e il `uv.lock` della radice
restano ignorati: i nuovi report stabili sono fuori da `results/`.

La cartella `baseline_2026-10-15` conserva una copia del lock come
`environment.uv.lock`, con un nome non escluso dal `.gitignore`. La copia conserva
le dipendenze risolte, non un ambiente virtuale già installato.

### Ambiente

Ambiente verificato: Linux x86_64, Python 3.11.17, TensorFlow/Keras 2.15.0,
NumPy 1.26.4, h5py 3.11.0 e SciPy 1.14.1. FFmpeg e ffprobe sono programmi esterni
richiesti dall'estrazione video. La versione zlib della prova è 1.3.2.

Ricreare `.venv` sulla macchina di destinazione. Quella attuale fa riferimento a
un Python installato nella cartella utente locale e non è un ambiente trasferibile.
Con uv disponibile, dalla radice del progetto in una shell Linux:

```bash
cp experiments/activation_compression/baseline_2026-10-15/environment.uv.lock uv.lock
uv sync --locked --python 3.11 --extra test
source .venv/bin/activate
python --version
ffmpeg -version
ffprobe -version
```

Per installare uv fare riferimento alla [guida ufficiale](https://docs.astral.sh/uv/getting-started/installation/).
Su un'altra architettura la compatibilità delle dipendenze e le differenze numeriche
vanno ricontrollate. I tempi misurati sulla macchina originale rimangono una misura
storica, non una previsione per la nuova macchina.

### Dati e riproduzione

Conservare nella radice `VideoWithCan.mp4`, lo ZIP del modello e `canCoke.jpeg`.
I loro hash e quelli dei risultati stabili sono nel manifest della baseline.
Il contenuto di `results/input/` può essere rigenerato con
`extract_activations.py`, seguito da `compare.py`, come documentato nel README.

Sulla macchina d'origine l'archivio `experiments/activation_compression/results/SCIoT-ripresa-2026-10-17.tar.gz`
conteneva una copia del progetto con documenti, input e risultati generati, incluso
il lock. Esclude `.git`, `.venv` e cache. È una copia di lavoro, non un repository
con cronologia. Al suo interno `TRANSFER_SHA256SUMS.txt` permette di controllare
l'integrità dei file dopo l'estrazione con `sha256sum -c TRANSFER_SHA256SUMS.txt`.
L'archivio è presente localmente in questa macchina ma non è versionato: è una
copia storica e non include automaticamente gli aggiornamenti successivi.

### Punto esatto da cui riprendere

1. Leggere le sezioni 9.2–9.6: TCP, paper, confronto DPCM proposto, INT8 e 16×8.
2. Ricreare l'ambiente se necessario; eseguire i 23 test senza socket documentati
   nell'archivio 16×8. I cinque test TCP aggiuntivi richiedono socket locali;
   non sono stati rieseguiti durante le prove di quantizzazione del modello.
3. Preservare le baseline; ogni nuova esecuzione deve identificare input e tempi.
4. Verificare il supporto INT8/INT16 nel runtime Micro effettivo; il confronto
   PC favorisce 16×8 in fedeltà, ma non ne dimostra la convenienza sulla scheda.
5. Ampliare calibrazione e valutazione su sequenze distinte. Provare runtime e
   split sul target con scala/zero point coerenti e misurare memoria/tempo.
   Conservare float32 come controllo; nessuna qualità approvata per ora.
6. Definire DPCM/dead-zone e confrontare byte ed errore sulla rappresentazione
   scelta, distinguendo le misure PC, di rete e sulla scheda.

## Fonti consultate nella chat

Le proprietà dei file e i numeri delle prove derivano dal codice e dagli artefatti
locali. Le fonti online sotto sono quelle consultate durante la discussione;
non sono state tutte ricontrollate durante gli aggiornamenti. Il paper di Shiba
è stato verificato sul PDF primario il 18 ottobre, come indicato nella sezione 9.3.

- [FOMO](https://docs.edgeimpulse.com/studio/projects/learning-blocks/blocks/object-detection/fomo).
- [Tutorial sui centroidi](https://docs.edgeimpulse.com/tutorials/end-to-end/object-detection-centroids).
- [Blocco Image: grigio e normalizzazione](https://docs.edgeimpulse.com/studio/projects/processing-blocks/blocks/image).
- [Dashboard ed esportazione dei modelli](https://docs.edgeimpulse.com/studio/projects/dashboard#block-outputs).
- [Miglioramento del modello](https://docs.edgeimpulse.com/docs/increasing-model-performance).
- [Concetti di reinforcement learning](https://spinningup.openai.com/en/latest/spinningup/rl_intro.html).
- [XOR in NumPy](https://numpy.org/doc/stable/reference/generated/numpy.bitwise_xor.html).
- [zlib in Python 3.11](https://docs.python.org/3.11/library/zlib.html).
- [Quantizzazione post-training](https://developers.google.com/edge/litert/conversion/tensorflow/quantization/post_training_quantization).
- [TensorFlow Lite Micro di Espressif e integrazione ESP-NN](https://github.com/espressif/esp-tflite-micro).

Le ultime due fonti sono state ricontrollate il 18 ottobre per la prova INT8;
non certificano la compatibilità della libreria Arduino dichiarata nel firmware.
