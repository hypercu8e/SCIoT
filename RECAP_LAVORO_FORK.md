# SCIoT — recap del lavoro sul fork

**Stato al 20 ottobre 2026.** Questo documento riunisce ciò che abbiamo studiato,
realizzato e capito dall'inizio del lavoro sul fork. Il dettaglio cronologico è
nel [diario](DIARIO_TIROCINIO.md); qui conta soprattutto il filo del ragionamento.
Le date delle attività seguono i resoconti conservati, mentre i commit possono
essere successivi. Non ricostruiamo ore svolte o date amministrative mancanti.

Aggiornamento del 18 ottobre: raccolti 84 input di test pubblici
Beer/can e le sequenze OTB Coke/Liquor; eseguite inferenze su 148 input e una
prova dei veri componenti HTTP SCIoT con client Python. Istruzioni, risultati e
limiti in [TEST_SU_PC.md](TEST_SU_PC.md). UDP è stato discusso, non implementato.

Aggiornamento del 20 ottobre: documentati percorso di lettura del survey e
[valutazione di FOMO con early exiting](ANALISI_FOMO_EARLY_EXITING.md), già
presente come tema 6 nel [catalogo](TEMI_DI_TESI_E_RICERCA.md). È una proposta
da discutere: nessuna testa addestrata, nuova misura o approvazione del relatore.

## 1. Dove siamo arrivati

Abbiamo costruito una base sperimentale su PC per capire come ridurre i dati
scambiati durante l'inferenza distribuita tra ESP32 e server. Abbiamo verificato
uno split del modello, confrontato diversi codec, provato uno scambio TCP e
convertito il modello in INT8 e 16×8.

Abbiamo trovato risparmi di byte e misurato gli effetti sulle predizioni.
**Non abbiamo ancora dimostrato un miglioramento complessivo sull'ESP32.**
Gli esperimenti restano separati dalle applicazioni originali. Dal 19 ottobre
sono applicate ai firmware originali correzioni di interprete, buffer e messaggi,
verificate sul PC e compilate per i tre trasporti; server, modelli e algoritmo
di offloading non sono modificati. Non è ancora una verifica hardware.

Gli [esperimenti Micro nativi del 19 ottobre](experiments/micro_execution_2026-10-19/README.md)
aggiungono un confronto misurato fra layer separati e prefissi raggruppati.
Il test INT8 rileva una differenza rispetto ai vettori desktop archiviati:
Micro coincide con i kernel desktop di riferimento, e il modello intero con
la catena delle sue due parti. L'uguaglianza con l'archivio resta un controllo
fallito, senza modificare i vettori per nasconderlo.

La domanda che guida il lavoro è diventata più precisa:

> Quando il risparmio di trasmissione compensa il costo di calcolo e memoria
> sul dispositivo, mantenendo predizioni sufficientemente fedeli?

## 2. Da cosa siamo partiti e cosa abbiamo capito del progetto

SCIoT contiene già il meccanismo per distribuire una rete tra dispositivo e server:

```text
immagine → primi layer sull'ESP32 → attivazioni trasmesse → layer rimanenti sul server
```

Il **punto di split** stabilisce dove interrompere il calcolo sul dispositivo.
Le **attivazioni** sono i risultati intermedi necessari al server per continuare.
L'algoritmo originale sceglie il punto considerando costi di calcolo e trasmissione.

Abbiamo letto struttura del repository, configurazione, generazione dei modelli,
firmware e percorso di inferenza sul server. I principali riscontri sono:

- **MQTT, HTTP e WebSocket erano già presenti.** Non abbiamo aggiunto WebSocket
  al framework; il nuovo esperimento di rete usa TCP in programmi separati.
- Il percorso originale esaminato trasmette attivazioni **float32**, senza il
  codec temporale sviluppato nei nostri esperimenti.
- I firmware inviano anche l'immagine originale. Ridurre le attivazioni non
  equivale a ridurre della stessa percentuale tutto il traffico.
- Alcuni layer espandono i dati: eseguire più layer sul dispositivo non garantisce
  un messaggio più piccolo.
- La rete contiene rami residui. Un taglio arbitrario può richiedere più di un
  tensore per proseguire; bisogna verificare le dipendenze del grafo.
- Modello, preparazione delle immagini, protocollo e firmware sono legati a FOMO.
  Cambiare soltanto il nome del modello non garantisce il supporto di altre reti.
- Sono emersi limiti nello stato condiviso tra client e nella scelta dello split
  in presenza di carico concorrente. La gestione di più client resta da sviluppare.

Abbiamo anche analizzato duplicazioni, file probabilmente superflui e firmware.
Tra i problemi documentati: durata non valida dell'interprete, serializzazione
degli identificativi e lunghezze incoerenti dei tempi inviati. **Questi tre difetti
sono corretti dal 19 ottobre**, con test nativi e compilazione. Altre proposte
restano da applicare; le stime di pulizia non sono accelerazioni misurate.

Approfondimenti: [spiegazione del repository](SPIEGAZIONE_REPOSITORY.md),
[miglioramenti](ANALISI_MIGLIORAMENTI_SCIOT.md),
[duplicazioni](ANALISI_CODICE_SUPERFLUO.md),
[firmware](ANALISI_OTTIMIZZAZIONI_FIRMWARE_SCIOT.md).

## 3. Le distinzioni che hanno orientato gli esperimenti

| Concetto | Significato pratico |
|---|---|
| Compressione indipendente | Ogni tensore si codifica senza usare il precedente. |
| Compressione temporale | Si sfrutta un riferimento condiviso tra mittente e ricevitore. |
| Senza perdita | La ricostruzione conserva esattamente i dati originali. |
| Con perdita | Si accetta un'approssimazione, misurandone gli effetti. |
| Quantizzazione del messaggio | Si approssimano le attivazioni da inviare; il calcolo della rete può restare float32. |
| Quantizzazione del modello | Si cambia la rappresentazione usata anche nell'esecuzione della rete, come INT8 o 16×8. |

Appiattire un tensore o sottrarre due tensori, da solo, non riduce i byte. Occorre
una codifica che rappresenti i dati con meno spazio. Il riferimento temporale
deve coincidere sui due lati e va ripristinato dopo perdita dello stato.

Abbiamo inoltre distinto **meno byte** da **meno attesa**: comprimere richiede
calcolo e memoria. Su un collegamento molto rapido il lavoro aggiuntivo può
superare il tempo risparmiato nel trasferimento.

## 4. Il percorso concreto e i risultati

### A. Preparare un modello e uno split verificabili — 15 ottobre

Le etichette del modello originario incluso in SCIoT non erano state identificate.
Abbiamo usato separatamente un FOMO pubblico candidato, senza addestrarlo:
ingresso in grigio `96×96×1`, uscita `12×12×3` con sfondo e due classi.
Preparazione usata: ritaglio quadrato centrale, resize Lanczos, grigio BT.601,
normalizzazione in `[0,1]`. Restano aperte la conferma dell'ordine delle etichette
e la parità pixel per pixel con Edge Impulse Studio.

Dal video `VideoWithCan.mp4`, circa 29,26 secondi, abbiamo estratto 146 frame
a 5 fps e un sottoinsieme di 30 frame a 1 fps. Sono frequenze di campionamento,
non velocità raggiunte dalla scheda.

Lo split dopo **`block_2_add`** richiede un solo tensore `24×24×8`:
4.608 valori float32, **18.432 byte per frame**. Prima parte e seconda parte
Keras hanno riprodotto l'uscita del modello intero sui 146 frame, con differenza
massima osservata pari a zero. Questo valida quel taglio in Keras sul PC.

La prima prova sulla foto `canCoke.jpeg` non aveva prodotto rilevazioni alla
soglia 0,5; è un risultato storico descritto nel diario, con artefatti temporanei
non conservati. Non abbiamo validato l'accuratezza generale del candidato.

### B. Compressione senza perdita — baseline del 15 ottobre

Abbiamo confrontato dati non compressi, zlib indipendente, differenze numeriche,
XOR tra i bit e riordino dei byte (*byte shuffle*) prima della compressione.
La ricostruzione viene controllata byte per byte.

| Campione | Risparmio del migliore metodo sul raw | Vantaggio temporale sullo stesso compressore indipendente |
|---|---:|---:|
| 5 fps | 14,96% | 5,71% |
| 1 fps | 12,31% | 2,78% |

Il metodo migliore è XOR + shuffle + zlib. **Il 14,96% non è tutto merito del
riferimento temporale:** il suo beneficio aggiuntivo è il 5,71% a 5 fps.
La sottrazione/somma float32 non è sempre esatta nei bit; la codifica numerica
float64 provata non batte il completo compresso in questo campione.

Abbiamo implementato header, sequenze, riferimenti, checksum, completi iniziali
e periodici, scelta del payload più piccolo e recupero tramite un completo.
Sono meccanismi del prototipo, separati dal protocollo originale SCIoT.

Fonte: [baseline senza perdita](experiments/activation_compression/baseline_2026-10-15/README.md).

### C. Perdita controllata sulle attivazioni — 17 ottobre

Abbiamo arrotondato le attivazioni con passi diversi, mantenendo la rete float32.
L'indipendente comprime l'intero tensore arrotondato; il temporale può comprimere
la differenza tra gli interi correnti e precedenti. A parità di passo, i due
metodi ricostruiscono **gli stessi valori**, isolando il beneficio temporale.

A 5 fps e passo `0,001`:

- indipendente: **40,61%** di riduzione rispetto al raw;
- temporale: **48,66%** rispetto al raw;
- beneficio temporale aggiuntivo: **13,57%** rispetto all'indipendente;
- nessuna etichetta di cella cambiata a soglia 0,5 nel campione, pur con punteggi
  numerici diversi. A passi più grossi crescono risparmio ed effetti sulle celle.

Abbiamo provato sei passi e due frequenze. I 15 test di quella fase coprono
ricostruzione, riferimenti, corruzione, perdita di aggiornamenti, recupero e limiti
numerici. I dati rigenerati hanno hash diversi dalla baseline storica: i due
archivi sono esperimenti distinti, senza confronti diretti tra input diversi.

Fonte: [prova con perdita](experiments/activation_compression/lossy_2026-10-17/README.md).

### D. Scambio client–server TCP — 18 ottobre

Abbiamo realizzato un client che riproduce le attivazioni salvate e un server
separato che ricostruisce il tensore ed esegue il suffisso Keras. Entrambi girano
sullo stesso PC, tramite TCP loopback, senza Wi-Fi o ESP32.

146 frame, tre metodi, tre ripetizioni: **1.314 richieste e 18 connessioni**,
con riconnessione programmata tra frame confermati e nuovo riferimento.

| Metodo | Byte applicativi in salita per sequenza | Tempo tipico misurato |
|---|---:|---:|
| Raw | 2.696.760 | 0,673 ms/frame |
| Indipendente, passo 0,001 | 1.602.438 | 1,181 ms/frame |
| Temporale, passo 0,001 | 1.385.197 | 1,483 ms/frame |

I tempi sono la mediana dei tre p50, dal tensore pronto alla risposta del server:
includono codifica, scambio, decodifica, suffisso, hash e risposta; escludono camera,
prefisso e inizializzazione. Sono conteggiati i byte applicativi, non header
TCP/IP o ritrasmissioni; le risposte sono conteggiate separatamente.

**Il temporale risparmia il 13,56% in salita sull'indipendente, ma qui aumenta
l'attesa.** Il loopback è tanto rapido che il lavoro del codec non viene compensato.
Questo non predice il bilancio su Wi-Fi o su una CPU ESP32. Verificati tensori,
uscite e ripartenza tra connessioni; 20 test passati in quella fase. Non è stato
provato il recupero automatico da un guasto durante un messaggio.

Fonte: [prova TCP](experiments/activation_compression/tcp_2026-10-18/README.md).

### E. Quantizzazione del modello INT8 e 16×8 — 18 ottobre

Abbiamo verificato se il modello già addestrato può usare rappresentazioni
numeriche più piccole. Abbiamo separato i primi **48 frame di calibrazione**
dai successivi **98 di valutazione**; restano campioni correlati dello stesso video.
La calibrazione non richiede etichette; l'accuratezza reale su oggetti le richiede.

Prima abbiamo convertito TFLite float32 come controllo, poi INT8. Successivamente
abbiamo convertito il **16×8: attivazioni INT16, pesi INT8 e bias INT64**,
ricaricando gli stessi binari float32/INT8 per un confronto coerente. Non è float16.

| Misura sui 98 frame | TFLite float32 | INT8 | 16×8 |
|---|---:|---:|---:|
| File del modello | 84.292 byte | 57.088 byte | 69.056 byte |
| Soli valori al confine | 18.432 byte | 4.608 byte | 9.216 byte |
| Max errore nei punteggi rispetto a Keras | 0,00000310 | 0,289446 | 0,285753 |
| MAE nei punteggi | 0,0000000296 | 0,00223682 | 0,000776675 |
| Celle cambiate a soglia 0,5 | 0 | 25 | 18 |
| Celle oggetto perse / introdotte | 0 / 0 | 11 / 14 | 7 / 11 |

Il riferimento ha **99 celle oggetto** su 14.112 celle-frame. L'accordo globale
vicino al 100% è dominato dallo sfondo: per capire gli effetti guardiamo anche
celle perse/introdotte ed errore massimo. Le celle non sono oggetti distinti e
queste misure non sono accuratezza su annotazioni.

Entrambe le conversioni intere funzionano sul PC senza fallback float. Il 16×8
è più fedele nelle metriche riportate, occupando più spazio dell'INT8; resta
uno scostamento massimo vicino a 0,286. Non abbiamo approvato la qualità di
nessuna variante per l'applicazione né stabilito la causa degli errori residui.

Il 75% di riduzione INT8 e il 50% INT16 riguardano **i soli valori del tensore**.
Non sono riduzioni del file TFLite, del traffico totale o della RAM totale.
Abbiamo osservato il confine nel modello intero; due sottomodelli quantizzati
separati con parametri coerenti sono ancora da esportare e verificare.

Archivi: [INT8](experiments/activation_compression/int8_2026-10-18/README.md)
e [16×8](experiments/activation_compression/16x8_2026-10-18/README.md).
I binari sono stati ricaricati in verifiche separate, confrontando hash delle
uscite, metriche e CSV. L'ultima suite senza socket comprende **23 test passati**;
i cinque test TCP precedenti non sono stati rieseguiti durante queste prove.

### F. Split INT8 e preparazione ESP32 — 19 ottobre

Diviso il binario INT8 già salvato in prima parte (16.400 byte) e seconda parte
(41.168 byte), senza nuova conversione/calibrazione. Conservati pesi e parametri
numerici; confine INT8 `24×24×8`, 4.608 byte. Su tutti i 146 frame, rigenerati con
hash identico alla prova precedente, confine e uscita dello split coincidono
byte per byte con il modello INT8 intero.

Preparati tre input fissi e tre firmware isolati (`prefix`, `full`, `suffix`),
compilati e collegati per ESP32-S3. Registrano confronto delle uscite, tempi di
sola inferenza, arena e heap. Non sono stati caricati su hardware e non usano
camera, rete o codec. Nel runtime effettivamente scaricato TensorFlowLite_ESP32
1.0.0 manca la depthwise convolution con ingresso INT16 richiesta da sei nodi
del nostro 16×8; per quella variante occorre aggiornare/estendere il runtime.

Passati 31 test degli esperimenti (inclusi cinque socket e tre nuovi test sul
taglio) e quattro del verificatore seriale, questi ultimi con log sintetici.
[Risultati e artefatti](experiments/activation_compression/esp32_prep_2026-10-19/README.md),
[istruzioni hardware](experiments/esp32_int8_firmware/README.md).

### G. Correzioni dei tre firmware — 19 ottobre

Applicate ai client float32 HTTP/MQTT/WebSocket correzioni di durata dell'interprete,
verifica di allocazioni/tensori e serializzazione condivisa. Nei template il buffer
messaggio passa da 922.253 a 461.261 byte: 460.992 byte in meno richiesti in PSRAM,
senza misura di picco o prestazioni hardware. Compilati tutti i client.

Le funzioni C++ usate dai client sono eseguite sul PC con il runtime Micro 1.0.0:
1.170 invocazioni e 33.363.072 valori intermedi identici al riferimento TFLite
sugli stessi binari; nessun errore ASan/UBSan. Quattro pacchetti verificati col
parser originale, passati anche 35 test di regressione degli esperimenti/probe.
Il confronto finale del riferimento TFLite con Keras ha errore massimo 4,77e-7
sui tre input sintetici. Nessun risultato di accuratezza su annotazioni.

[Report e limiti](experiments/firmware_fixes_2026-10-19/README.md),
[riproduzione dei test](tests/firmware/README.md). Camera, rete e concorrenza dei
trasporti restano da provare sulla scheda; server e modelli non sono modificati.

## 5. Rapporto con i paper e idee ancora aperte

Abbiamo confrontato il codice con la documentazione SCIoT e studiato il diverso
paper 2026 di **Shiba et al., “Delta Coding With Dead-Zone Quantization for
Bandwidth-Efficient Split Computing on Video Streams”**.

Il nostro codec attuale quantizza prima il tensore e poi codifica differenze
intere. Nel DPCM del paper si quantizza il residuo rispetto alla ricostruzione
precedente; la dead-zone azzera una fascia più larga di piccole differenze.
**Non abbiamo ancora implementato DPCM/dead-zone del paper.** Con passo fisso
e senza clipping, cambiare il solo ordine può lasciare quasi uguali le ricostruzioni:
il confronto deve specificare intervalli, precisione e dead-zone effettivi.

I risultati del paper riguardano classificazione e simulazione su una macchina;
non dimostrano la convenienza della nostra variante su ESP32 con FOMO. Il nostro
possibile contributo è adattare e valutare la soluzione nel sistema concreto,
senza rivendicare l'invenzione della compressione temporale.

Abbiamo mantenuto altre piste: gestione di più client e scelta dello split in
base al carico, supporto generale ai grafi e selezione preventiva dei frame simili.
L'ultima potrebbe evitare anche inferenza e invio; è diversa dal comprimere
attivazioni già calcolate. Sono proposte, non funzionalità realizzate.

Sono state documentate anche fonti di sequenze aggiuntive Coke/Liquor e un piano
per il benchmark ESP32. I confronti storici qui sopra usano il primo video.
Le sequenze sono state successivamente riscaricate, insieme al set pubblico
Beer/can, nella nuova cache `results/public_test_data/`; la nuova prova su 148
input è descritta nella guida PC. Non è stata usata per ricalibrare i modelli.

Rimandi: [confronto col paper e spiegazioni](ANALISI_COMPRESSIONE_ATTIVAZIONI.md),
[possibili tesi](POSSIBILI_ARGOMENTI_TESI.md),
[selezione dei frame](IDEE_DA_ESPLORARE.md),
[fonti e piano hardware](FONTI_VIDEO_E_PROVE_ESP32.md).

## 6. Cosa abbiamo prodotto e cosa manca

| Ambito | Stato |
|---|---|
| Studio di struttura, protocollo, firmware e limiti | Documentato con riferimenti al codice |
| Ambiente PC, modello candidato, video e split Keras | Preparati ed eseguiti |
| Codec senza perdita e con perdita controllata | Implementati e provati offline |
| Client/server TCP sperimentali | Implementati e provati su loopback |
| Modelli TFLite float32, INT8 e 16×8 | Convertiti ed eseguiti sul PC |
| Report, JSON, CSV, hash, verifiche e test | Conservati negli archivi degli esperimenti |
| Correzioni firmware originali | Interprete, buffer e messaggi corretti; test nativi e tre build riusciti; hardware da provare |
| Refactoring/server e altre proposte | Ancora da sviluppare |
| Runtime Micro | Percorsi INT8 ispezionati; manca depthwise INT16 nella libreria scelta; esecuzione hardware da provare |
| Split quantizzato | INT8 esportato e verificato sul PC, firmware di prova compilati |
| Protocollo SCIoT aggiornato | Ancora da integrare e verificare |
| Tempi, picco RAM, energia e rete sull'ESP32 | Non misurati |
| Accuratezza su un dataset annotato rappresentativo | Non valutata |
| DPCM/dead-zone, più client e selezione dei frame | Proposte da implementare se scelte |

Non abbiamo riaddestrato il modello. Le prove di compressione su float32 e le
conversioni INT8/16×8 sono filoni collegati ma distinti: **i risparmi temporali
su float32 non si trasferiscono automaticamente ai tensori quantizzati**.

## 7. Punto di ripresa

Il prossimo controllo è **allocazione e inferenza INT8 sulla scheda**, usando
i firmware di prova già compilati e confrontando i log con i tre vettori attesi.
Il risultato CPU e il build non certificano l'esecuzione sulla scheda.
Per INT16 serve prima un runtime che implementi la depthwise INT16 mancante
nella libreria scelta.

Poi occorre verificare sul target anche le correzioni float32, camera e rete,
e misurare memoria e tempi reali. In parallelo
serve ampliare calibrazione e valutazione su sequenze distinte, senza scegliere
parametri in base allo stesso campione di test. L'accuratezza richiederà annotazioni
adatte quando disponibili; la sola calibrazione può usare immagini non annotate.

La scelta della rappresentazione e del codec deve confrontare tre aspetti insieme:
**byte, costo sul dispositivo e fedeltà delle predizioni**. Da questi dipenderà
l'integrazione in un solo percorso SCIoT e l'eventuale approfondimento DPCM/dead-zone.

## 8. Dove ritrovare il lavoro e cosa è salvato in Git

| Per orientarsi | File |
|---|---|
| Recap del percorso e delle conclusioni | Questo documento |
| Cronologia dettagliata delle attività | [DIARIO_TIROCINIO.md](DIARIO_TIROCINIO.md) |
| Concetti, metodi, risultati e limiti | [ANALISI_COMPRESSIONE_ATTIVAZIONI.md](ANALISI_COMPRESSIONE_ATTIVAZIONI.md) |
| Prossimi controlli e contesto del tirocinio | [SCALETTA_TIROCINIO.md](SCALETTA_TIROCINIO.md) |
| Comandi e archivi sperimentali | [README degli esperimenti](experiments/activation_compression/README.md) |
| Dataset pubblici e prove eseguibili senza ESP32 | [TEST_SU_PC.md](TEST_SU_PC.md) |

Il fork configurato come `origin` è `hypercu8e/SCIoT`; il progetto originale
configurato come `upstream` è `UBICO/SCIoT`. La base locale del lavoro è
`0cfeb9b`; il ramo locale `main`, al momento del recap, è a `4f35e1b`.
Il remoto non è stato interrogato durante questa ricostruzione.

La cronologia aggiunta comprende il prototipo e la baseline (`d38a489`),
la documentazione (`087fef9`), la prova con perdita (`78eac02`), l'analisi firmware
(`c6f168d`), le proposte di tesi (`508de5a`) e il diario (`4f35e1b`). I primi due
commit sono del 17 ottobre, i successivi del 18: la data del commit può differire
da quella dell'attività o dell'esperimento descritto.

**Il lavoro recente non è tutto nei commit:** TCP, INT8, 16×8, i relativi script
e archivi, questo recap e ulteriori aggiornamenti ai documenti sono ancora nella
cartella di lavoro. `git status` identifica lo stato attuale. La cache `results/`
e l'ambiente `.venv` sono ignorati da Git: i report permanenti contengono hash
e istruzioni, ma non sostituiscono automaticamente tutti gli input necessari.
L'archivio di trasferimento del 17 ottobre è una copia storica e non include
automaticamente il lavoro successivo.
