# SCIoT — Temi di tesi, sfide aperte e direzioni di ricerca

Documento creato il 19 ottobre 2026; revisione critica del 20 ottobre 2026.

Questo documento raccoglie proposte di **tesi triennale** collegate al tirocinio da 300 ore con il Prof. Luca Bedogni, Università di Modena e Reggio Emilia, sul framework **SCIoT**. Le proposte restano da discutere con il relatore.

La revisione conserva le undici direzioni precedenti, corregge riferimenti e affermazioni tecniche e aggiunge sei direzioni. Le difficoltà sono stime progettuali, non garanzie di completamento nelle ore disponibili.

## Come leggere le evidenze

- **Codice ispezionato:** comportamento dedotto dai sorgenti del checkout; non prova di prestazioni, concorrenza o funzionamento fisico su ESP32.
- **Esperimenti documentati:** risultati già registrati negli artefatti citati; questa revisione non li ha rieseguiti.
- **Letteratura:** risultati o problemi descritti dalle fonti nei loro specifici contesti.
- **Proposta SCIoT:** domanda e possibile esperimento. L'assenza di una funzione nel repository non dimostra novità scientifica.

Le direzioni di [POSSIBILI_ARGOMENTI_TESI.md](POSSIBILI_ARGOMENTI_TESI.md) restano utili come contesto. La [rassegna bibliografica](LETTERATURA_E_PAPER_SCIOT.md) contiene ancora riferimenti da correggere: per i lavori interessati usare quelli verificati nella sezione 5 di questo documento.

---

## Mappa Sinottica dei Temi

| # | Macro-Area | Titolo del Tema | Difficoltà | Hardware Richiesto | Principale Paper di Riferimento |
|---|---|---|---|---|---|
| **1** | **Multi-Device** | **Offloading multi-client basato sul carico** *(Asse principale proposto)* | Media/Alta | PC con client simulati; poi 2-4 ESP32 | [Shi et al., 2206.06304](https://arxiv.org/abs/2206.06304) |
| **2** | **Compressione** | **Compressione Temporale delle Attivazioni (DPCM + Dead-Zone)** | Media | 1 ESP32 + PC Server | Shiba et al. (IEEE Access 2026), SC2 (TMLR 2023) |
| **3** | **Selezione Frame** | **On-Camera Frame Filtering (Scarto Intelligente dei Frame Ridondanti)** | Facile/Media | 1 ESP32-CAM | Reducto (SIGCOMM 2020) |
| **4** | **Architetture Rete** | **Tagli corretti su grafi con rami (DAG)** | Alta | PC; ESP32 per la fattibilità embedded | [Auto-Split, KDD 2021](https://arxiv.org/abs/2108.13041) |
| **5** | **Embedded System** | **Ottimizzazione Low-Level del Firmware C++ su ESP32-S3** | Media/Alta | 1 ESP32 + Debugger/Profiler | TFLite Micro (MLSys 2021) |
| **6** | **SC + EE** | **Uscite anticipate sul microcontrollore** | Media/Alta | Dati per addestramento e valutazione, PC e ESP32 | [Survey SC/EE](https://arxiv.org/abs/2103.04505) |
| **7** | **Server** | **Batching con scadenze** | Media/Alta | PC e generatori di carico; poi client reali | [Cang et al., 2307.14350](https://arxiv.org/abs/2307.14350) |
| **8** | **Privacy** | **Offuscamento delle feature e valutazione degli attacchi** | Alta | PC, dati e modello di attaccante | Meccanismo gaussiano: riferimento in §2.3 |
| **9** | **Networking** | **Trasporto ESP-NOW con gateway** | Media/Alta | 2 ESP32 e collegamento gateway-server | Documentazione Espressif in §2.4 |
| **10** | **Energia** | **Sleep e consumo per inferenza** | Media | ESP32 e strumento di misura della potenza | Documentazione Espressif in §2.5 |
| **11** | **Device-to-Device** | **Inferenza cooperativa tra microcontrollori** | Alta | 2-3 MCU interconnessi | [Lu et al., WoWMoM 2026](https://arxiv.org/abs/2605.09357) |
| **12** | **Servizio in tempo reale** | **Freschezza dei risultati sotto carico (§3.1)** | Media | PC, video annotati; poi più ESP32 | [Timely Communications for Remote Inference](https://arxiv.org/abs/2404.16281) |
| **13** | **Affidabilità** | **Recupero dello stato della compressione temporale (§3.2)** | Media | PC con interruzioni controllate; poi ESP32 | Replay TCP locale e Shiba et al. |
| **14** | **Adattamento** | **Scelta congiunta di split e compressione (§3.3)** | Media/Alta | PC e ESP32 | Auto-Split; estensione progettuale per SCIoT |
| **15** | **Multi-Device** | **Equità tra dispositivi diversi (§3.4)** | Media | Client simulati eterogenei; poi più ESP32 | [Fast and fair split computing](https://www.sciencedirect.com/science/article/pii/S2405959524001164) |
| **16** | **Valutazione** | **Quando lo split conviene davvero (§3.5)** | Media | PC, ESP32 e dati annotati | Survey SC/EE, sezione 6 |
| **17** | **Generalità** | **Applicazioni oltre la visione (§3.6)** | Media/Alta | Un modello e dataset audio o di sensori | Survey SC/EE, sezione 6 |

---

## 1. Direzioni già presenti negli appunti di progetto

### 1.1 Multi-Device: Offloading Dinamico Consapevole della Coda del Server (Raccomandato)

* **Contesto:** Il titolo generale riportato nella [scaletta](SCALETTA_TIROCINIO.md) è *"Multi Device Split Computing"*. L'[algoritmo attuale](src/server/offloading_algo/offloading_algo.py) somma calcolo locale, trasmissione e calcolo remoto, senza un termine esplicito per la coda.
* **Cosa fare:**
  1. Stimare l'attesa considerando quando arriva una richiesta, quanto lavoro delega e come viene servita:
     $$\widehat T_i(k_i\mid S_t,\pi)=T_{dev,i}(k_i)+T_{tx,i}(k_i)+\widehat W_i(k_i\mid S_t,\pi)+T_{srv,i}(k_i)+T_{return,i}.$$
     $S_t$ è lo stato osservato di rete e server; $\pi$ è la politica di servizio. La dipendenza dell'attesa $\widehat W_i$ dal taglio va modellata e verificata, non solo scritta nella formula. **Aggiungere lo stesso `T_queue(M)` a ogni candidato non cambia il minimo.** In alcuni regimi l'attesa può risultare quasi indipendente dal taglio.
  2. Isolare sessioni, profili e risposte. Il [server HTTP](src/server/communication/http_server.py) conserva un solo attributo `best_offloading_layer` per istanza; l'endpoint che lo restituisce non seleziona il client. Il [gestore delle richieste](src/server/communication/request_handler.py) aggiorna profili condivisi. Un nuovo protocollo non risolve da solo questi problemi.
  3. Correlare richieste e decisioni, limitare le code e controllare l'accesso agli interpreti. Considerare il costo del cambio di split ed evitare oscillazioni frequenti.
* **Esperimento iniziale:** Un modello, un trasporto e pochi tagli validi; confrontare split fisso, algoritmo attuale e politica proposta con 1, 2 e 4 client. Misurare attesa, latenza completa, scadenze mancate e richieste completate per client.
* **Riferimento:** [Shi et al.](https://arxiv.org/abs/2206.06304) studiano offloading e batching multiutente; i loro risultati non sono automaticamente trasferibili a SCIoT.

---

### 1.2 Compressione Temporale delle Attivazioni (DPCM con Dead-Zone)

* **Contesto:** La correlazione delle feature dipende da scena, movimento, frequenza e taglio. Gli [esperimenti disponibili](experiments/activation_compression/README.md) non vanno identificati automaticamente con il metodo DPCM con dead-zone del paper.
* **Cosa fare:**
  1. Usare il riferimento **ricostruito** condiviso: $e_t=x_t-\hat{x}_{t-1}$, $q_t=Q_{DZ}(e_t)$, $\hat{x}_t=\hat{x}_{t-1}+Q^{-1}_{DZ}(q_t)$.
  2. Allargare la zona associata allo zero per rendere i residui più comprimibili; non per «aumentare l'entropia». Distinguere frame completi e differenziali.
  3. Confrontare tensore non compresso, compressione indipendente e temporale sullo stesso modello, taglio e sequenza. Misurare codifica, decodifica, RAM inclusi riferimenti e buffer temporanei, byte, latenza completa, energia e qualità del compito su dati annotati.
* **Limite:** Risparmiare byte non garantisce minore latenza su ESP32. Il tema 13 approfondisce il recupero quando i riferimenti si disallineano.
* **Paper di riferimento:** [Hiroki Shiba et al., IEEE Access 2026](https://da.lib.kobe-u.ac.jp/da/kernel/0100504251/0100504251.pdf).

---

### 1.3 On-Camera Frame Filtering (Selezione Intelligente dei Frame)

* **Domanda:** Quanto calcolo e traffico si possono evitare senza perdere eventi o rilevarli troppo tardi? Una scena apparentemente statica non garantisce che sia corretto evitare ogni aggiornamento.
* **Cosa fare:**
  1. Implementare una funzione leggerissima a livello di pixel prima di invocare il modello neurale (differenza tra blocchi o campionamento sparso).
  2. Confrontare invio periodico, soglia fissa e soglia adattiva, eventualmente con aggiornamento periodico obbligatorio. Anche un frame scartato ha un costo di acquisizione e confronto.
  3. Misurare energia, costo del filtro, eventi persi, falsi allarmi e ritardo della prima rilevazione su cambi di luce, movimenti piccoli e ingressi rapidi di oggetti.
* **Paper di riferimento:** [Reducto, SIGCOMM 2020](https://dl.acm.org/doi/10.1145/3387514.3405874); i suoi risultati non sono una garanzia per ESP32.

---

### 1.4 Split su Grafi Complessi e Reti con Connessioni Residue (DAG)

* **Codice ispezionato:** [model_split.py](src/server/models/model_split.py) contempla layer con ingressi multipli. [Edge.run_inference](src/server/edge/edge_initialization.py) ricostruisce dipendenze tra layer, ma riceve un solo array al confine di offloading. Il limite da generalizzare è il taglio che richiede di trasferire più tensori, non l'incapacità assoluta di rappresentare rami.
* **Esperimenti documentati:** Lo [split INT8 dopo `block_2_add`](experiments/activation_compression/esp32_prep_2026-10-19/README.md) ha già una verifica su PC di equivalenza con il modello INT8 intero su 146 frame. Lo strumento rifiuta tagli con più tensori di confine; non è un partizionatore generico. Non è una nuova misura di accuratezza né una prova fisica sul dispositivo.
* **Cosa fare:**
  1. Estrarre tutti i tensori che attraversano il confine del DAG (grafo diretto aciclico), preservando identità, forme, tipi e dipendenze. Verificare prima l'equivalenza numerica.
  2. Cercare il taglio considerando byte, calcolo e picco di memoria. Minimizzare soltanto il numero di tensori può scegliere un confine costoso. Un algoritmo min-cut richiede una formulazione compatibile con i vincoli.
* **Paper di riferimento:** [Auto-Split, KDD 2021](https://arxiv.org/html/2108.13041v1), che studia anche split e precisione congiunti; non è una ricetta generica di min-cut.

---

### 1.5 Ottimizzazione Low-Level del Firmware ESP32-S3

* **Contesto:** Usare l'[analisi del firmware](ANALISI_OTTIMIZZAZIONI_FIRMWARE_SCIOT.md) come inventario da confrontare con il checkout corrente.
* **Cosa fare:**
  1. Profilare acquisizione, preprocessing, preparazione degli interpreti, inferenza, copie, serializzazione e trasmissione.
  2. Valutare riuso degli interpreti, esecuzione di gruppi di layer, rimozione delle copie compatibile con la durata dei buffer e kernel ESP-NN effettivamente supportati.
  3. Confrontare una modifica alla volta, includendo memoria e correttezza numerica. Il [firmware INT8 preparato](experiments/activation_compression/esp32_prep_2026-10-19/README.md) è documentato come privo di ESP-NN: l'accelerazione non deriva automaticamente dal nome del processore. Compilazione e test su PC non sostituiscono le misure sulla scheda.

---

## 2. Altre direzioni del catalogo originale

Queste sono proposte da circoscrivere, non tutte elencate esplicitamente nella sezione 6 di Matsubara. La corrispondenza con il survey è chiarita nella sezione 4.

---

### 2.1 Uscite anticipate sul microcontrollore

* **L'Intuizione:** Perché scegliere a priori se fare split o locale per tutti i frame? Molti frame contengono input "facili" (sfondo vuoto, oggetto chiarissimo) e altri "difficili" (oggetto parzialmente occluso, rumore).
* **Come funziona:**
  1. Progettare e addestrare una piccola uscita locale, misurandone costo e qualità.
  2. Calibrare la decisione di fermarsi: confidenza elevata non significa necessariamente correttezza. Per FOMO serve una decisione adatta alla mappa di rilevazione, evitando che il predominio dello sfondo nasconda oggetti difficili.
  3. Delegare al server gli input che non soddisfano il criterio. Evitare l'offloading non implica necessariamente spegnere la radio: notifiche e riattivazione hanno costi.
* **Esperimento:** Confrontare split senza uscita, soglia fissa e decisione adattiva, separando calibrazione e valutazione. Misurare frazione di uscite locali, qualità del compito, costo aggiuntivo e latenza. Il precedente «60–70%» non era un risultato dimostrato per SCIoT.
* **Riferimento di inquadramento:** [Matsubara et al., survey SC/EE](https://arxiv.org/abs/2103.04505).

**Approfondimento del 20 ottobre:** [FOMO con early exiting: spiegazione e valutazione](ANALISI_FOMO_EARLY_EXITING.md).
Il candidato H5 ispezionato ha una sola uscita finale. La nota distingue
architettura e runtime, rilevamento anticipato completo e riconoscimento di
immagini vuote, descrive il precedente BlankSkip e propone una verifica su PC
prima del porting ESP32. Comprende rischi, confronti e formulazione da discutere
con il relatore; nessuna implementazione o approvazione viene dichiarata.

---

### 2.2 Batching al server con scadenze

* **Domanda:** Raggruppare richieste compatibili migliora il servizio abbastanza da compensare l'attesa per formare il gruppo?
* **Codice ispezionato:** [predict_single_layer](src/server/models/model_manager.py) crea e prepara un interprete TFLite per layer e chiamata. Prima del batching verificare riuso del runtime, dimensione batch supportata, memoria e compatibilità di modello, split, forma e rappresentazione dei tensori. Una coda asincrona non rende automaticamente parallela l'inferenza.
* **Esperimento:** Confrontare servizio senza batching e piccoli batch con attesa massima configurabile, a carichi diversi. Il timeout di raccolta non garantisce la scadenza: devono rientrarvi anche esecuzione e ritorno della risposta.
* **Metriche:** Throughput (richieste completate al secondo), latenza e scadenze mancate per client. Non assumere un raddoppio o una triplicazione delle prestazioni.
* **Paper correlati:** [Shi et al.](https://arxiv.org/abs/2206.06304), [Cang et al.](https://arxiv.org/abs/2307.14350).

---

### 2.3 Offuscamento delle feature e privacy

* **Domanda:** Quali informazioni dell'input restano recuperabili dalle feature e quanto costa ridurre questa esposizione?
* **Perimetro:** Definire attaccante, dati e pesi a cui ha accesso e informazione da proteggere. Ricostruzione visiva e inferenza di attributi sensibili sono obiettivi diversi: un'immagine poco riconoscibile non dimostra privacy.
* **Esperimento:** Valutare un attacco senza difesa, poi rumore o azzeramento di canali con un attaccante consapevole della difesa. Misurare successo dell'attacco, qualità del compito legittimo e costo sul dispositivo. Non presumere una qualità «intatta >90%».
* **Distinzione necessaria:** Aggiungere rumore gaussiano è un possibile offuscamento. Per dichiarare *Differential Privacy* servono una definizione di adiacenza, limiti di sensibilità e calibrazione con parametri di privacy, considerando anche le comunicazioni ripetute. Il [meccanismo gaussiano calibrato](https://proceedings.mlr.press/v80/balle18a.html) è un riferimento per questa distinzione, non una dimostrazione per SCIoT. La difficoltà precedente «Facile/Media» sottostimava il lavoro.

---

### 2.4 Trasporto ESP-NOW con gateway

* **Domanda:** ESP-NOW tra camera e gateway conviene rispetto a trasporti IP persistenti per i tensori e i carichi effettivi di SCIoT?
* **Vincoli:** La [documentazione Espressif](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/network/esp_now.html) distingue payload massimi di 250 byte per v1.0 e 1470 byte per v2.0. Verificare il supporto nella toolchain effettiva, senza attribuire automaticamente v2.0 al firmware attuale.
* **Esperimento:** Includere frammentazione, metadati, riordino, conferma applicativa, ritrasmissioni e trasferimento gateway-server. Il successo di invio a livello MAC non prova che l'applicazione abbia ricostruito il tensore. Confrontare stesso payload e affidabilità, distinguendo avvio e regime stabile: TCP persistente non richiede un handshake a ogni frame.
* **Metriche:** Latenza completa, byte, energia e consegne fallite, anche con più client. Non è dimostrato che lo stack domini i tempi di SCIoT né che ESP-NOW porti l'intero trasferimento da «30–50 ms» a «pochi millisecondi».

---

### 2.5 Sleep e consumo per inferenza

* **Domanda:** Per quali intervalli tra acquisizioni il riposo recupera più energia di quanta ne costino risveglio e ripristino del servizio?
* **Vincoli:** Misurare l'intera scheda, inclusi camera, regolatore e periferiche; non attribuire a ogni configurazione un unico intervallo di corrente. La [documentazione ESP32-S3](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/sleep_modes.html) distingue sleep esplicito e modalità che mantengono la connessione tramite modem-sleep e light-sleep automatico. Spegnere semplicemente la radio mentre si attende una risposta non definisce una strategia completa.
* **Esperimento:** Confrontare attività continua, risparmio con connessione mantenuta e cicli con disconnessione. Misurare joule per risultato utile, risveglio, riconnessione, perdita di risposte e ritardo degli eventi. Stimare l'autonomia da consumi misurati e ipotesi esplicite sulla batteria.

---

### 2.6 Inferenza cooperativa tra microcontrollori

* **Domanda:** Distribuire il calcolo su più MCU permette di eseguire un modello incompatibile con la memoria di un solo nodo, con un costo accettabile?
* **Perimetro:** Una catena MCU-MCU-server è una configurazione possibile, non una conseguenza automatica del segnale debole verso il server. Ogni passaggio aggiunge comunicazione e coordinamento.
* **Esperimento:** Scegliere un modello e due nodi; confrontare picco RAM, correttezza e latenza con alternative fattibili. È un lavoro più ampio del caso principale con client indipendenti che condividono un server.
* **Paper correlato:** [Lu et al., WoWMoM 2026](https://arxiv.org/abs/2605.09357) studiano anche partizionamento all'interno dei layer per ridurre il picco RAM. Un semplice taglio tra layer non riproduce quel contributo.

---

## 3. Direzioni aggiunte nella revisione

### 3.1 Freschezza dei risultati sotto carico — tema 12

**Problema:** Completare molte inferenze su immagini ormai vecchie può essere poco utile per osservare la scena corrente.

**Domanda:** In sovraccarico conviene elaborare in ordine di arrivo, scartare richieste scadute o conservare soltanto il frame più recente in attesa per client?

**Esperimento:** Confrontare queste tre politiche con code limitate, stesso modello e frequenze controllate. Misurare età dell'ultima osservazione rappresentata da un risultato disponibile, ritardo della prima rilevazione, eventi persi e scadenze mancate. L'età dell'informazione non coincide con il solo tempo di elaborazione di una richiesta.

[Timely Communications for Remote Inference](https://arxiv.org/abs/2404.16281) fornisce un riferimento per freschezza e qualità; non implica che il frame più recente sia sempre il migliore. Lo scarto deve rispettare le dipendenze di un eventuale codec temporale.

### 3.2 Recupero dello stato della compressione temporale — tema 13

**Problema:** Un residuo è utilizzabile solo se i due lati condividono il riferimento atteso. Riavvii, cambi di split o scarti applicativi possono romperlo. Con TCP la perdita radio normalmente causa ritrasmissioni: non va confusa con la perdita di un frame applicativo o con una nuova sessione.

**Punto di partenza:** Il [replay TCP sperimentale](experiments/activation_compression/socket_benchmark.py) gestisce già una riconnessione controllata e il ripristino del codec. Restano da studiare politiche adattive, più client e integrazione nel firmware.

**Esperimento:** Confrontare riferimenti completi periodici, rinnovo su richiesta e politica adattiva, introducendo interruzioni e cambi di configurazione controllati. Identificare sessione, sequenza, riferimento, modello e split. Misurare tempo di recupero, byte aggiuntivi, richieste inutilizzabili e RAM; verificare l'assenza di contaminazione tra sessioni.

### 3.3 Scelta congiunta di split e compressione — tema 14

**Problema:** Comprimere cambia sia la dimensione trasmessa sia il costo di calcolo e memoria. Scegliere prima il taglio e poi il codec può ignorare questa interazione.

**Domanda:** Una piccola politica che sceglie insieme taglio e codec migliora latenza o energia rispetto alle scelte separate?

**Esperimento:** Pochi tagli validi e due o tre modalità di codifica, con un vincolo sulla qualità del compito. Profilare codifica, decodifica, inferenza e RAM; includere il costo del cambio di configurazione e ripristino dei riferimenti. La frequenza di acquisizione è un'eventuale estensione, non un'altra variabile da ottimizzare subito.

[Auto-Split](https://arxiv.org/html/2108.13041v1) mostra che split e precisione sono già studiati congiuntamente. La proposta specifica è una politica leggera compatibile con codec, risorse e condizioni operative di SCIoT.

### 3.4 Equità tra dispositivi diversi — tema 15

**Problema:** Ottimizzare il totale delle richieste completate può lasciare alcuni dispositivi con ritardi o scarti molto maggiori degli altri.

**Domanda:** Come distribuire il servizio quando i client hanno frequenze, capacità, qualità di rete o scadenze diverse?

**Esperimento:** Confrontare coda comune, turni per client e politica con pesi o scadenze. Definire prima l'equità desiderata: stesso numero di risultati, stessa frazione di richieste servite o rispetto di requisiti diversi. Riportare ritardi e scarti per dispositivo insieme al throughput aggregato.

[Fast and fair split computing](https://www.sciencedirect.com/science/article/pii/S2405959524001164) è un precedente pertinente: l'equità non è un tema inesplorato in assoluto.

### 3.5 Quando lo split conviene davvero — tema 16

**Problema:** Confrontare due strategie di split non basta a dimostrare che convenga dividere la rete.

**Codice ispezionato:** In [OffloadingAlgo.static_offloading](src/server/offloading_algo/offloading_algo.py) il caso interamente sul server viene valutato ma non partecipa alla selezione del minimo; la sua valutazione usa inoltre dimensione trasmessa zero. Non è quindi una baseline completa di invio dell'input. Correggerla e validarla è un prerequisito sperimentale, non un contributo scientifico da solo.

**Esperimento:** Confrontare inferenza locale, invio dell'input compresso al server e split, includendo acquisizione, preprocessing, compressione, comunicazione, esecuzione e disponibilità del risultato. Usare stesso compito e qualità comparabile. Se il modello non entra sul dispositivo, dichiarare l'infattibilità o identificare chiaramente l'eventuale modello locale alternativo.

Variare rete e carico per individuare le regioni di convenienza, includendo energia e memoria. L'accordo tra due esecuzioni non prova che entrambe rilevino correttamente gli oggetti: servono dati annotati. Il [survey](https://arxiv.org/abs/2103.04505) richiama esplicitamente confronti realistici e dimensione dell'input compresso.

### 3.6 Applicazioni oltre la visione — tema 17

**Domanda:** Quali parti di SCIoT devono diventare indipendenti da FOMO e dalla camera per supportare un singolo nuovo compito, per esempio audio o sensori inerziali?

Il [gestore delle richieste](src/server/communication/request_handler.py) e i convertitori contengono assunzioni su immagini RGB565 e tensori float32. Per il nuovo compito servono un contratto di tensore esplicito, preprocessing, forma, tipo, eventuali parametri di quantizzazione e semantica della risposta.

**Esperimento:** Scegliere un solo modello compatibile con il runtime e un dataset annotato; verificarne prima la qualità, poi confrontare esecuzione locale, remota e split. Evitare l'obiettivo iniziale di supportare «qualsiasi rete». È una direzione alternativa al lavoro multi-client, coerente con l'espansione dei domini applicativi discussa nel survey.

## 4. Cosa attribuire al survey e cosa alle proposte SCIoT

La sezione 6 della [copia locale del survey](papers/matsubara_survey.txt) (preprint v4 del 25 marzo 2022, associato al lavoro poi pubblicato in CSUR 2023) discute cinque direzioni:

| Sfida esplicita del survey | Collegamento possibile nel catalogo |
|---|---|
| Valutazioni in condizioni più realistiche | Tema 16 e metodologia comune |
| Progettazione e collocamento dei bottleneck | Tema 14; un bottleneck addestrato è un'estensione distinta da un codec applicato dopo l'addestramento |
| Controllo dinamico delle uscite anticipate | Tema 6 |
| Espansione dei domini applicativi | Tema 17 |
| Interpretazione attraverso la teoria dell'informazione | Inquadramento teorico; nessuna proposta circoscritta per il tirocinio in questo documento |

Non attribuire direttamente a questa lista ESP-NOW, sleep, batching o tutte le altre proposte. Una sfida elencata allora non è automaticamente irrisolta nel 2026. Per sostenere una novità di tesi occorre una ricerca bibliografica mirata alla domanda scelta.

## 5. Correzioni bibliografiche e tecniche registrate

| Voce precedente | Esito della verifica e riferimento da usare |
|---|---|
| Shi et al., `2108.06899` | L'ID rimanda a un [paper di astrofisica](https://arxiv.org/abs/2108.06899). Usare [Multi-user Co-inference with Batch Processing Capable Edge Server, 2206.06304](https://arxiv.org/abs/2206.06304). |
| Joint Batching and Scheduling, `2404.14812` | L'ID rimanda a un [paper sul ragionamento degli LLM](https://arxiv.org/abs/2404.14812). Usare [Cang, Chen e Huang, 2307.14350](https://arxiv.org/abs/2307.14350); la precedente attribuzione a VTC 2024 non è mantenuta senza verifica. |
| Auto-Split, IEEE Access 2021; `2108.13506` nella rassegna collegata | Corretto: [KDD 2021, DOI 10.1145/3447548.3467078](https://scholars.duke.edu/publication/1530614), [arXiv:2108.13041](https://arxiv.org/abs/2108.13041). L'altro ID riguarda economia. |
| Shiba, indicato come T. Shiba e volume 12 nella rassegna collegata | Il [PDF originale](https://da.lib.kobe-u.ac.jp/da/kernel/0100504251/0100504251.pdf) riporta Hiroki Shiba, Zhiyi Zhu, Patrick Finnerty e Chikara Ohta; IEEE Access, volume 14, 2026, DOI 10.1109/ACCESS.2026.3690477. |
| SC2 indicato come TMLR 2022 con autori errati | Il [preprint locale](papers/matsubara_tmlr2022_sc2_supervised_compression.pdf) e la [fonte arXiv](https://arxiv.org/abs/2203.08875) riportano *SC2 Benchmark*, Matsubara, Yang, Levorato e Mandt; TMLR 2023, primo preprint 2022. Corretto il riferimento nella rassegna; conservato il nome storico del PDF. |
| Guadagni del 60–70%, throughput 2–3×, qualità intatta >90%, ESP-NOW in pochi millisecondi | Non sono risultati dimostrati per SCIoT; sostituiti da domande, confronti e metriche. |
| Dead-zone per aumentare l'entropia; filtraggio a costo zero | Corretto lo scopo della dead-zone e contabilizzato il costo di acquisizione e filtraggio. |
| Rumore gaussiano uguale a Differential Privacy | Separata la difesa empirica dalla garanzia formale con ipotesi e parametri espliciti. |

La tabella documenta i problemi individuati; non certifica l'intera bibliografia del repository. I file collegati non sono stati riscritti in questa revisione.

## 6. Perimetro consigliato e criteri di valutazione

**Prima proposta da discutere:** tema 1 con tema 12, cioè servizio multi-client corretto e gestione del sovraccarico orientata alla freschezza dei risultati. Il batching del tema 7 resta un'estensione dopo averne misurato l'utilità. È una valutazione progettuale coerente con il titolo del tirocinio, non una dichiarazione di approvazione del relatore.

Una sequenza circoscritta:

1. Fissare modello, dati, trasporto e tagli; verificare le baseline del tema 16.
2. Isolare stato e risposte dei client; rendere osservabili attesa ed esecuzione.
3. Confrontare poche politiche di coda con carichi controllati su PC.
4. Ripetere i confronti essenziali su ESP32 e Wi-Fi, separando risultati simulati e misure su dispositivi reali.

**Alternative:** temi 2 e 13 per compressione e recupero dello stato; tema 5 per una tesi embedded centrata su pochi costi misurati. Early-exit, privacy, DAG generici e cooperazione tra MCU richiedono un perimetro più stretto prima di stimare l'impegno.

Per ogni esperimento definire almeno:

- **Correttezza:** risultato associato al client e alla richiesta giusti; equivalenza numerica quando attesa; qualità del compito su dati annotati.
- **Tempi:** acquisizione, calcolo locale, codifica, trasmissione, coda, decodifica, calcolo remoto e ritorno. Misurare anche la latenza completa dal lato client; confronti tra timestamp di macchine diverse richiedono di quantificare l'errore di sincronizzazione.
- **Servizio:** mediana e percentili p95/p99 (il 95%/99% dei campioni ha valore non superiore), numero di campioni, ripetizioni, scarti e scadenze mancate per client. Distinguere carico offerto e lavoro completato.
- **Risorse:** byte effettivi, picco RAM, memoria del codec e, se misurabile, energia dell'intera scheda per risultato utile.
- **Riproducibilità:** hash di modelli e dati, versioni, configurazione di rete, split, codec, frequenza degli arrivi e separazione tra calibrazione e test.

Un risultato negativo è utile se delimita quando una tecnica non conviene e ne identifica il costo dominante. Nessuna proposta richiede di promettere in anticipo una percentuale di miglioramento.
