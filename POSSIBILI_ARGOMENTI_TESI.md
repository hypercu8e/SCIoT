# SCIoT — possibili argomenti per la tesi

Documento del 17 ottobre 2026. Proposte da discutere con il relatore; nessun
argomento viene scelto definitivamente con questo documento.
Aggiornamento del 18 ottobre: prova TCP e chiarimenti sul paper nella direzione
compressione; la priorità tra i possibili argomenti non viene cambiata.

## Contesto e obiettivo

Gli appunti del progetto indicano un tirocinio interno da 300 ore, una possibile
tesi triennale in Informatica a UNIMORE con il prof. Luca Bedogni e il titolo
generale concordato **Multi Device Split Computing**. La comunicazione di rete
e la gestione di più dispositivi sono le esigenze riportate nella
[scaletta del tirocinio](SCALETTA_TIROCINIO.md).

L'obiettivo è individuare un lavoro con una domanda precisa, un contributo
riconoscibile e risultati riproducibili. Il massimo punteggio dipende dai criteri
del corso e dalla valutazione del relatore e della commissione: nessuna delle
proposte lo garantisce. Una buona strategia è concordare presto quali risultati
rendano il lavoro completo, lasciando le estensioni fuori dal perimetro iniziale.

Le priorità sotto sono valutazioni progettuali, non una graduatoria scientifica
né una dimostrazione di novità rispetto a tutta la letteratura.

## Confronto delle direzioni

| Direzione | Punto di forza | Rischio principale | Priorità proposta |
|---|---|---|---|
| Più dispositivi e scelta dello split in base al carico | Coerenza con il titolo concordato e problema di sistema misurabile | Gestione della concorrenza e complessità degli esperimenti | Prima proposta da discutere |
| Compressione adattiva delle attivazioni | Esperimenti preliminari già disponibili | Risparmio di byte che non si traduce in minore latenza su ESP32 | Alternativa principale |
| Selezione dei frame da elaborare | Possibilità di evitare sia calcolo sia trasmissione | Perdita di eventi e rilevazioni tardive | Alternativa da circoscrivere |
| Split corretto per reti con rami | Migliora la generalità del framework | Ampiezza del lavoro su grafi, conversione e memoria | Alternativa più impegnativa |
| Ottimizzazione del firmware ESP32 | Risultati concreti su tempi e memoria | Lavoro disperso in molte piccole correzioni | Possibile tesi sperimentale embedded |

Il confronto MQTT/HTTP/WebSocket può supportare queste direzioni. I tre trasporti
sono già presenti: aggiungere WebSocket non è, da solo, un nuovo argomento per
questo checkout. Un confronto tra trasporti dovrebbe spiegare anche il motivo
delle differenze osservate.

## 1. Più dispositivi e scelta dello split in base al carico

**Titolo possibile:** Gestione di dispositivi concorrenti e selezione dello split
consapevole del carico nel framework SCIoT.

### Domanda di ricerca

Come cambia la scelta del punto di split quando più dispositivi condividono lo
stesso server e la stessa rete? Considerare il carico del server migliora le
prestazioni rispetto alla strategia attuale e a uno split fisso?

### Collegamento con il codice

L'[algoritmo attuale](src/server/offloading_algo/offloading_algo.py) stima il costo
come somma di calcolo sul dispositivo, trasmissione e calcolo sul server. Non
include esplicitamente l'attesa in coda causata da altri client.

Nel percorso esaminato, i [profili temporali dei dispositivi](src/server/commons.py)
usano un file condiviso; il [server HTTP](src/server/communication/http_server.py)
registra identificativi di dispositivi ma conserva un solo
`best_offloading_layer`. Questi elementi motivano una revisione dello stato per
client; non dimostrano, da soli, il comportamento di ogni trasporto sotto carico.

### Contributo e perimetro iniziale

- Separare sessioni, profili, risultati e decisioni dei singoli dispositivi.
- Introdurre una coda esplicita e una gestione concorrente delle richieste con
  accesso controllato alle risorse condivise.
- Realizzare una strategia semplice che consideri anche l'attesa sul server.
- Gestire il costo del cambio di split, evitando oscillazioni a ogni richiesta.
- Partire da un modello, un trasporto e pochi punti di split validi.

### Esperimenti e metriche

Confrontare split fisso, strategia attuale e strategia proposta. Variare numero
di client, frequenza delle richieste, capacità del server e condizioni di rete.
Una prima matrice possibile è 1, 2 e 4 client, da adattare alle risorse disponibili.

Misurare latenza dall'acquisizione al risultato, mediana e percentile 95,
tempo in coda, richieste completate al secondo e prestazioni per dispositivo.
Se si introducono scadenze, contare anche risultati arrivati troppo tardi.

Client software possono generare carico aggiuntivo, ma i risultati devono
distinguere dispositivi reali, riproduzione di tracce e simulazione. Un computer
che esegue il modello non riproduce automaticamente i tempi di un ESP32.

**Criterio di completamento:** sessioni isolate e una valutazione riproducibile
che mostri quando considerare il carico aiuta, quando è indifferente e quando
comporta costi aggiuntivi. La compressione resta un'estensione facoltativa.

## 2. Compressione adattiva delle attivazioni

**Titolo possibile:** Compressione temporale delle attivazioni per l'inferenza
distribuita su ESP32: compromesso tra traffico, latenza e qualità.

### Domanda di ricerca

Quando conviene inviare il tensore completo, comprimerlo indipendentemente o
codificarlo rispetto a un riferimento precedente? Il risparmio di trasmissione
compensa il costo del codec e la memoria aggiuntiva sul dispositivo?

### Stato attuale

Sono già disponibili esperimenti isolati su PC, su un video e uno split FOMO:

- [Baseline senza perdita del 15 ottobre](experiments/activation_compression/baseline_2026-10-15/comparison/report.md):
  a 5 fps, XOR con riordino dei byte e zlib risparmia il 14,96% sul raw; il
  vantaggio rispetto al completo compresso con lo stesso riordino è il 5,71%.
- [Prova con perdita del 17 ottobre](experiments/activation_compression/lossy_2026-10-17/README.md):
  a 5 fps e passo 0,001, il temporale risparmia il 48,66% sul raw contro il
  40,61% dell'indipendente. Il beneficio temporale è il 13,57% rispetto
  all'indipendente, a identica ricostruzione.
- [Prova TCP del 18 ottobre](experiments/activation_compression/tcp_2026-10-18/README.md):
  replay delle attivazioni e suffisso Keras in processi distinti sullo stesso PC.
  Il temporale risparmia il 13,56% dei byte in salita sull'indipendente, ma aumenta
  il tempo di codifica + scambio + suffisso rispetto sia al raw sia all'indipendente.
  Sono misure su loopback; non su Wi-Fi o ESP32.

Le prove offline del 15 e del 17 ottobre hanno attivazioni con hash diversi:
i loro numeri sono risultati storici distinti. Per un confronto diretto occorre
usare gli stessi input e tensori. La prova con perdita quantizza i dati al confine;
non converte la rete in
un modello INT8 e non replica il metodo di un paper.

Sono byte del flusso applicativo sperimentale, non misure del traffico Wi-Fi.
L'accordo con le uscite originali non è accuratezza rispetto a oggetti annotati.
Non è ancora dimostrata la convenienza complessiva su ESP32.

Il [confronto col paper e il prossimo esperimento proposto](ANALISI_COMPRESSIONE_ATTIVAZIONI.md#93-risultati-del-paper-e-differenze-dal-nostro-metodo)
chiariscono cosa è già misurato e cosa resta da implementare. Il confronto DPCM,
prima senza e poi con dead-zone, resta un possibile approfondimento sullo stesso
FOMO; specificare le differenze di intervallo e precisione, perché con passo fisso
il solo cambio d'ordine può lasciare quasi identiche le ricostruzioni.

La priorità è stata poi aggiornata alla rappresentazione del modello:
[prima verifica INT8 sul PC](experiments/activation_compression/int8_2026-10-18/README.md)
completata senza riaddestramento. TFLite da 84.292 a 57.088 byte (-32,27%),
conversione integer-only e inferenza desktop riuscite; 25 celle cambiate a soglia
0,5 nei 98 frame di valutazione, con 11 celle oggetto perse sulle 99 del riferimento
e 14 introdotte. Calibrazione su 48 frame separati dello stesso video. Questa
variante non è approvata come baseline di qualità e non è verificata su ESP32.
Verificare input di calibrazione più rappresentativi mantenendo la valutazione
separata, poi runtime, split e costi sul target. Calibrare non richiede annotazioni;
la valutazione dell'accuratezza reale le richiede.

Completato poi il [confronto 16×8](experiments/activation_compression/16x8_2026-10-18/README.md)
con la stessa calibrazione/valutazione e controlli float32/INT8 invariati:
attivazioni INT16, pesi INT8 e bias INT64, nessun fallback float. Il file occupa
69.056 byte; il confine 9.216 byte. Celle cambiate a soglia 0,5 da 25 a 18,
perse da 11 a 7 sulle 99 del riferimento e introdotte da 14 a 11. Migliore
fedeltà nelle metriche riportate, con dimensioni maggiori di INT8 e massimo
errore sui punteggi ancora circa 0,286. Nessuna qualità approvata; verificare
il supporto INT8/INT16 nel runtime Micro prima di scegliere il porting.

La riduzione del 75% dei soli valori al confine (18.432 → 4.608 byte) è osservata
nel modello intero; non è una misura del traffico del protocollo o della memoria
totale. Il contributo temporale va confrontato anche con questa eventuale base
INT8 o 16×8: i precedenti risparmi float32 non dimostrano il vantaggio sulle
nuove rappresentazioni.
Questo percorso resta un adattamento sperimentale e non definisce ancora
l'argomento definitivo della tesi.

### Contributo e perimetro iniziale

- Scegliere un codec compatibile con la RAM disponibile e integrarlo in un solo
  trasporto SCIoT.
- Mantenere riferimenti coerenti, sequenze, rinnovi completi e recupero dopo
  perdita di stato o riconnessione.
- Definire una regola di scelta della modalità considerando byte e costo del
  codec. Provare sempre tutte le modalità può costare troppo sul dispositivo.
- Partire da uno split fisso; valutare altri split solo dopo il primo risultato.

### Esperimenti e metriche

Confrontare raw, compressione indipendente e temporale a parità di input,
precisione e regole di conteggio. Per separare il beneficio temporale da quello
della quantizzazione, usare come controllo un metodo indipendente con qualità
equivalente; quando possibile, con lo stesso tensore ricostruito.

Usare più sequenze separate per scene statiche, movimento, cambi di luce e tagli
di scena. Misurare byte effettivamente trasferiti, tempo del codec, latenza
completa, picco di RAM e qualità delle rilevazioni su annotazioni. Misurare
l'energia solo se è disponibile strumentazione adeguata.

**Criterio di completamento:** individuare le condizioni in cui il codec è
conveniente sul target e il limite di qualità accettato. Un beneficio nullo o
negativo, se spiegato con misure corrette, resta un risultato utile.

La codifica differenziale delle attivazioni ha già un riferimento in letteratura:
[Shiba et al., IEEE Access 2026](https://doi.org/10.1109/ACCESS.2026.3690477).
Il contributo specifico proposto qui è l'integrazione e la valutazione su SCIoT,
con eventuale selezione adattiva; la sua novità va approfondita prima di fissare
il titolo definitivo.

## 3. Selezione dei frame da elaborare

**Titolo possibile:** Selezione adattiva dei frame per ridurre calcolo e
comunicazione nell'inferenza IoT distribuita.

### Domanda di ricerca

Un controllo leggero sull'immagine permette di saltare inferenze e invii senza
perdere eventi importanti o introdurre ritardi eccessivi?

L'idea è già raccolta in [IDEE_DA_ESPLORARE.md](IDEE_DA_ESPLORARE.md).
Il controllo avverrebbe prima della rete: l'eventuale vantaggio comprende quindi
anche il calcolo locale evitato.

### Contributo e valutazione

Definire un criterio di cambiamento, l'aggiornamento del riferimento e un intervallo
massimo senza nuova inferenza. Confrontare tutti i frame, campionamento periodico
e selezione adattiva, anche a parità di numero medio di frame elaborati.

Servono video annotati con entrata e uscita degli oggetti, movimenti lenti,
oggetti piccoli, scene stabili e variazioni di luce. Misurare inferenze evitate,
byte, latenza, eventi persi, ritardo nella prima rilevazione ed età dell'ultimo
risultato disponibile.

**Rischio principale:** una scena che cambia poco nei pixel può contenere un
evento importante. La sola percentuale di frame saltati non basta per sostenere
la validità del metodo.

**Criterio di completamento:** mostrare il compromesso tra lavoro evitato e
tempestività del riconoscimento, con soglie definite su sequenze diverse da
quelle usate per la valutazione finale.

## 4. Split corretto per reti con rami e connessioni residue

**Titolo possibile:** Partizionamento di reti neurali a grafo per l'inferenza
distribuita su dispositivi IoT.

### Domanda di ricerca

Come identificare punti di split eseguibili e i tensori da trasferire quando una
rete ha più rami o collegamenti che saltano alcuni layer?

Il [generatore di sott modelli](src/server/models/model_split.py) e il percorso
di esecuzione vanno considerati insieme. Il confine tra dispositivo e server
può richiedere più di un tensore; il numero del layer non descrive da solo tutte
le dipendenze. Contesto e proposte sono in
[ANALISI_MIGLIORAMENTI_SCIOT.md](ANALISI_MIGLIORAMENTI_SCIOT.md).

### Contributo e valutazione

Limitare il lavoro a poche architetture e operatori compatibili. Ricavare le
dipendenze, identificare i tensori che attraversano il confine e produrre un
manifest con forma, tipo e identificatore. Confrontare rete intera e rete
partizionata, poi misurare traffico, memoria e latenza sui tagli validi.

**Rischio principale:** trasformarlo in un convertitore universale per qualunque
rete. La prima dimostrazione può fermarsi al PC; una tesi centrata su ESP32
richiede anche di verificarne conversione ed esecuzione sul target.

**Criterio di completamento:** partizionamento corretto e riproducibile su una
famiglia limitata di grafi, con dipendenze e costi del confine documentati.

## 5. Ottimizzazione del firmware ESP32

**Titolo possibile:** Analisi e ottimizzazione di tempi e memoria nel firmware
ESP32 per lo split computing.

### Domanda di ricerca

Quali costi del runtime limitano l'inferenza distribuita e quanto si recupera
intervenendo su caricamento, copie dei tensori e gestione della memoria?

L'[analisi del firmware](ANALISI_OTTIMIZZAZIONI_FIRMWARE_SCIOT.md) raccoglie
riscontri statici e interventi candidati, ancora da verificare sulla scheda.
È una base di partenza, non un benchmark hardware già concluso.

### Contributo e valutazione

Stabilire prima una baseline corretta, poi separare acquisizione, preprocessing,
preparazione degli interpreti, copie, inferenza e invio. Scegliere pochi interventi
in base ai costi osservati e misurarli singolarmente e insieme.

Confrontare gli output sugli stessi input, i tempi delle fasi, la latenza completa,
RAM interna, PSRAM e stabilità durante esecuzioni prolungate. Per questo percorso
serve accesso continuativo alla scheda.

**Rischio principale:** raccogliere molte piccole modifiche senza una domanda
comune. Le correzioni di correttezza sono prerequisiti: non usare un'esecuzione
con risultati invalidi come riferimento prestazionale da battere.

**Criterio di completamento:** spiegare quali costi dominano sul target e
dimostrare il contributo delle ottimizzazioni scelte, mantenendo output validi.

## Scelta consigliata e dimensione del lavoro

La prima proposta da portare al relatore è **multi-dispositivo con scelta dello
split in base al carico**, per la coerenza con il titolo concordato. La seconda
è **compressione delle attivazioni con valutazione reale su ESP32**, perché
dispone già di risultati preliminari.

Scegliere un asse principale. Evitare di rendere obbligatori nella stessa tesi
multi-dispositivo, nuovo codec, più protocolli, supporto generico ai grafi e
ottimizzazione completa del firmware.

Una possibile ripartizione di 300 ore, da correggere dopo il primo prototipo:

| Attività | Ore indicative |
|---|---:|
| Definizione della domanda, letteratura e protocollo sperimentale | 30 |
| Baseline corretta e infrastruttura di misura | 60 |
| Implementazione del contributo principale | 75 |
| Esperimenti e analisi dei risultati | 70 |
| Documentazione e materiale per la tesi | 45 |
| Margine per imprevisti | 20 |
| **Totale** | **300** |

Questa ripartizione non assume che tutte le ore di scrittura della tesi possano
essere conteggiate nel tirocinio: va concordata con il relatore. Il primo
traguardo deve verificare disponibilità di hardware, correttezza del modello e
misurabilità del fenomeno prima di investire nella soluzione completa.

## Cosa rende il risultato convincente

- Una domanda verificabile, con un criterio di completamento concordato.
- Un confronto con una baseline corretta e sufficientemente competitiva.
- Una matrice di esperimenti sostenibile, con ripetizioni e variabilità riportata.
- Dati di taratura separati da quelli di valutazione; per i video, separazione
  per sequenza o ripresa, evitando frame quasi uguali nei due insiemi.
- Tempi PC, tempi ESP32, simulazione e rete reale identificati esplicitamente.
- Conteggio di costi e overhead, oltre ai risparmi.
- Codice, configurazioni, versioni, dati e comandi necessari a riprodurre i risultati.
- Discussione dei casi sfavorevoli e dei limiti, oltre alle condizioni migliori.

Una pubblicazione può essere un esito da valutare con il relatore, ma non è un
requisito assunto da queste proposte. Il valore della tesi va sostenuto con il
contributo effettivamente realizzato e verificato.

## Riferimenti e documenti di partenza

- [Scaletta del tirocinio](SCALETTA_TIROCINIO.md): contesto e stato del lavoro.
- [Analisi della compressione](ANALISI_COMPRESSIONE_ATTIVAZIONI.md): concetti e limiti.
- [Esperimenti di compressione](experiments/activation_compression/README.md): script e riproduzione.
- [Analisi dei miglioramenti](ANALISI_MIGLIORAMENTI_SCIOT.md): generalizzazione e comunicazione.
- [Analisi del firmware](ANALISI_OTTIMIZZAZIONI_FIRMWARE_SCIOT.md): interventi candidati sul dispositivo.
- [Idee da esplorare](IDEE_DA_ESPLORARE.md): selezione dei frame.
- [SCIoT, CCNC 2026](https://iris.unimore.it/handle/11380/1401417): pubblicazione sul framework.
- [Shiba et al., IEEE Access 2026](https://doi.org/10.1109/ACCESS.2026.3690477): riferimento per la codifica differenziale delle attivazioni.

Le fonti esterne sono quelle consultate nella discussione. L'assenza di una
funzionalità in SCIoT non prova che l'idea sia nuova: ogni argomento richiede una
ricerca bibliografica mirata prima di formulare rivendicazioni di originalità.
