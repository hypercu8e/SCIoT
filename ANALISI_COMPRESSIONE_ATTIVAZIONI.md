# SCIoT: analisi e spiegazioni della chat sulla compressione delle attivazioni

Consolidato il 17 ottobre 2026 e aggiornato con la prima prova con perdita della
stessa giornata. La baseline senza perdita rimane quella del 15 ottobre 2026.
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
binario e il server legge i valori float32. Non vi è il codec temporale provato qui.
Riferimenti nel codice:

- `src/client/esp32-s3-eye-mqtt/src/main.cpp`, copia dell'uscita nel messaggio;
- `src/server/communication/request_handler.py`, parsing di `layer_output`.

Non esiste una regola universale secondo cui ogni sistema comprime i tensori.
La quantizzazione del modello, per esempio con attivazioni int8, è una scelta
numerica distinta dalla compressione del messaggio; le due possono essere combinate.
La prova attuale usa float32 e non ha quantizzato il modello.

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

## 10. File da conservare e ripresa su un'altra macchina

### Documenti e risultati stabili

- Questo documento: spiegazioni e stato dell'intera chat.
- [SCALETTA_TIROCINIO.md](SCALETTA_TIROCINIO.md): percorso di lavoro aggiornato.
- [README dell'esperimento](experiments/activation_compression/README.md): script e comandi.
- [Copia dei risultati del 15 ottobre](experiments/activation_compression/baseline_2026-10-15/README.md):
  JSON, CSV, metadati, ambiente e report salvati fuori dalla directory ignorata `results/`.

Al primo consolidamento del 17 ottobre questi file erano ancora locali. Ora la
baseline e i documenti iniziali risultano nei commit locali `d38a489` e `087fef9`;
non è stata verificata la loro presenza sul remoto. La nuova prova con perdita è
nel lavoro corrente, senza commit o push. `results/` e il `uv.lock` della radice
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
L'archivio non è presente nel checkout attuale e non include automaticamente la
nuova prova con perdita.

### Punto esatto da cui riprendere

1. Leggere le conclusioni e i limiti di questa prova; distinguere byte, tempi PC e hardware.
2. Ricreare l'ambiente se necessario e verificare i 15 test dei due prototipi.
3. Consultare la baseline prima di rigenerare i risultati; ogni nuova esecuzione ha nuovi tempi.
4. Leggere il nuovo report con perdita e discutere precisione, errori locali e
   validazione su più sequenze con annotazioni.
5. Solo dopo i risultati preliminari decidere quali prove giustificano il porting su ESP32.

## Fonti consultate nella chat

Le proprietà dei file e i numeri delle prove derivano dal codice e dagli artefatti
locali. Le fonti online sotto sono quelle consultate durante la discussione;
non sono state ricontrollate durante questa sola trascrizione.

- [FOMO](https://docs.edgeimpulse.com/studio/projects/learning-blocks/blocks/object-detection/fomo).
- [Tutorial sui centroidi](https://docs.edgeimpulse.com/tutorials/end-to-end/object-detection-centroids).
- [Blocco Image: grigio e normalizzazione](https://docs.edgeimpulse.com/studio/projects/processing-blocks/blocks/image).
- [Dashboard ed esportazione dei modelli](https://docs.edgeimpulse.com/studio/projects/dashboard#block-outputs).
- [Miglioramento del modello](https://docs.edgeimpulse.com/docs/increasing-model-performance).
- [Concetti di reinforcement learning](https://spinningup.openai.com/en/latest/spinningup/rl_intro.html).
- [XOR in NumPy](https://numpy.org/doc/stable/reference/generated/numpy.bitwise_xor.html).
- [zlib in Python 3.11](https://docs.python.org/3.11/library/zlib.html).
- [Quantizzazione post-training](https://developers.google.com/edge/litert/conversion/tensorflow/quantization/post_training_quantization).
