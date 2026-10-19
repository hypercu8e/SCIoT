# Primo confronto della compressione delle attivazioni

Aggiornamento del 19 ottobre 2026: esportato e verificato lo
[split INT8](esp32_prep_2026-10-19/README.md) senza nuova conversione/calibrazione.
Equivalenza byte per byte col modello INT8 intero sui 146 frame; preparati tre
vettori di prova e compilati i firmware `full`, `prefix` e `suffix`. Nessuna prova
ESP32 ancora eseguita. La libreria selezionata non implementa la depthwise
convolution con ingresso INT16 richiesta dal modello 16×8.

Aggiornamento del 18 ottobre 2026: completato anche il
[confronto 16×8](16x8_2026-10-18/README.md), sugli stessi 48/98 frame e con gli
stessi binari float32/INT8 della prova precedente. Attivazioni INT16, pesi INT8,
bias INT64, nessun fallback float. A soglia 0,5: 18 celle cambiate contro 25
di INT8; 7 perse contro 11 sulle 99 del riferimento. File 69.056 byte e confine
9.216 byte. Più fedeltà nel campione, con dimensioni maggiori di INT8 e nessuna
validazione di qualità, prestazioni o compatibilità sul target.

Aggiornamento del 18 ottobre 2026: completata una
[verifica INT8 del modello su PC](int8_2026-10-18/README.md), senza riaddestramento.
Conversione integer-only riuscita; file TFLite da 84.292 a 57.088 byte (-32,27%).
Sui 98 frame separati dai 48 di calibrazione cambiano 25 celle a soglia 0,5:
11 perse e 14 introdotte rispetto alle 99 celle oggetto del riferimento.
INT8 è fattibile sul PC, ma non è approvato come baseline di qualità o validato
sull'ESP32. La prossima verifica riguarda input di calibrazione più rappresentativi.

Aggiornamento del 18 ottobre 2026: disponibile anche una
[prova client–server TCP su PC](tcp_2026-10-18/README.md), con riproduzione delle
attivazioni registrate, inferenza del suffisso in un processo separato e rinnovo
dello stato dopo riconnessione. Il formato resta separato dal protocollo SCIoT.

Aggiornamento del 17 ottobre 2026: è stata aggiunta una prima prova con perdita
controllata. I paragrafi seguenti descrivono la baseline senza perdita; la nuova
prova è documentata [più sotto](#prima-prova-con-perdita-controllata).
La cronologia del percorso è nel [diario del tirocinio](../../DIARIO_TIROCINIO.md).

Esperimento isolato su PC. Usa il FOMO esportato in `model.h5`, uno split fisso
dopo `block_2_add` e il video `VideoWithCan.mp4`. Non modifica il server o il firmware.

Per la trascrizione delle spiegazioni e la ripresa su un'altra macchina, leggere
[ANALISI_COMPRESSIONE_ATTIVAZIONI.md](../../ANALISI_COMPRESSIONE_ATTIVAZIONI.md).
La [baseline del 15 ottobre](baseline_2026-10-15/README.md) conserva report e dati
numerici fuori dalla directory `results/` ignorata da Git.

Ogni frame elaborato genera un tensore `24 x 24 x 8`, cioè 4.608 valori float32
e 18.432 byte. Un file NPY raccoglie i tensori dei frame lungo il primo asse:
`(numero_frame, 24, 24, 8)`. Il confronto usa 5 fps e il sottoinsieme a 1 fps.

## Esecuzione dalla radice del repository

```bash
source .venv/bin/activate
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 python experiments/activation_compression/extract_activations.py \
  --video VideoWithCan.mp4 \
  --model-zip ei-object-detection-with-fomo---bottles-vs.-cans-object-detection-keras-h5-model-model.5.zip \
  --output-dir experiments/activation_compression/results/input

python experiments/activation_compression/compare.py \
  --input-dir experiments/activation_compression/results/input \
  --output-dir experiments/activation_compression/results/comparison

python -m unittest discover -s experiments/activation_compression -p 'test_*.py' -v
```

Richiede l'ambiente già configurato e `ffmpeg`/`ffprobe`. Le impostazioni di input
sono ritaglio quadrato centrale, resize Lanczos, grigio BT.601 e normalizzazione
in [0,1], coerenti con la configurazione del progetto pubblico. Non è stata
verificata l'uguaglianza pixel per pixel con Edge Impulse Studio.

L'estrazione verifica prima parte + seconda parte rispetto al modello completo
su ciascun frame. Tutta la prova avviene in Keras sul PC, nello stesso processo.

## Metodi confrontati

| Metodo | Contenuto del messaggio |
|---|---|
| `raw` | Tensore completo, senza compressione |
| `full_zlib` | Tensore completo compresso separatamente per ciascun frame |
| `delta64_zlib` | Differenze numeriche tra float32 calcolate e trasmesse in float64, poi compresse |
| `xor_zlib` | XOR tra i byte del tensore attuale e del precedente, poi compresso |
| `full_shuffle_zlib` | Tensore completo con byte raggruppati per posizione dentro i float32, poi compresso |
| `xor_shuffle_zlib` | XOR con lo stesso raggruppamento di byte, poi compresso |

Zlib usa livello 1 e finestra predefinita da 32 KiB: è un riferimento sperimentale,
non un codec già validato per i vincoli di memoria dell'ESP32.

Il raggruppamento dei byte cambia l'ordine, senza eliminare informazioni. Il suo
controllo indipendente (`full_shuffle_zlib`) permette di misurare quanto guadagno
proviene dal riferimento temporale e quanto dalla disposizione dei byte.
XOR descrive differenze nei bit, non sottrazioni numeriche delle attivazioni.

La semplice sottrazione/somma float32 non garantisce ricostruzione esatta. Il
report misura separatamente questo errore. Il metodo numerico float64 controlla
che l'operazione sia reversibile sui dati effettivi; se fallisce torna al completo.
Anche float64 non garantisce reversibilità per qualunque combinazione float32.

## Ricostruzione e conteggio dei byte

I metodi differenziali inviano un completo iniziale e un completo ogni 5 secondi.
Per ogni altro frame scelgono il payload più piccolo tra completo e differenziale.
Anche i completi compressi tornano al raw se la compressione espande i dati.
Il riferimento è sempre l'ultimo tensore ricostruito e coincide byte per byte
con l'originale in questo esperimento senza perdita.

Ogni sessione include un'intestazione serializzata con forma, dtype, hash del
modello, layer di split, frequenza di campionamento e parametri del codec.
Ogni frame include un header binario di 24 byte: firma, versione, codifica,
flags, numero di sequenza, riferimento, lunghezza del payload e CRC32 del tensore.
Sono contati anche i wrapper/checksum zlib. I file NPY non sono usati come payload.
Questo formato è sperimentale e non è integrato nel protocollo SCIoT.

Il decoder rifiuta aggiornamenti con riferimento mancante, frame duplicati,
dimensioni errate e checksum incoerenti. Un nuovo completo può ripristinare il
riferimento. I test verificano anche perdita di un aggiornamento e recupero.
Non sono simulati o misurati tassi reali di perdita o ritrasmissioni.

## Risultati e limiti

Prima esecuzione sul video fornito: 146 frame a 5 fps, tre ripetizioni per codec.
Il totale senza compressione è 2.694.815 byte, inclusi 239 byte di sessione e
24 byte di header per frame. Il completo con zlib richiede 2.508.837 byte;
XOR + zlib richiede 2.401.249 byte. Con il riordino dei byte, il controllo completo
richiede 2.430.375 byte e XOR richiede 2.291.562 byte.

La riduzione migliore è quindi 14,96% rispetto al raw, ma il vantaggio attribuibile
al riferimento temporale, confrontando lo stesso riordino e compressore, è 5,71%.
Sul sottoinsieme a 1 fps questo vantaggio scende al 2,78%. Si tratta di questo
video e di questo split, non di una previsione per altri scenari o per ESP32.

La codifica delle differenze numeriche float64 non viene scelta in nessuno dei
frame: il payload candidato è sempre più grande del completo compresso. Il
fallback la porta alle stesse dimensioni di `full_zlib`, con lavoro aggiuntivo.
Questo risultato riguarda questa codifica, non tutte le codifiche differenziali.
La sottrazione/somma float32 diagnostica modifica invece 21.868 valori su 668.160
confrontati a 5 fps; errore assoluto massimo circa 4,77e-7. Non viene usata come
strategia senza perdita. Tutti i metodi riportati ricostruiscono byte identici.

I sei test dei codec e del recupero del riferimento sono passati. Sul PC il metodo
XOR con riordino richiede circa 0,58 ms/frame in codifica e 0,10 ms/frame in
decodifica in questa esecuzione; questi valori non stimano i tempi su ESP32.

I file generati sono esclusi da Git sotto `results/`:

- `input/`: modello estratto, frame preparati, attivazioni, uscite, metadati e anteprima.
- `comparison/report.md`: tabella leggibile dei risultati.
- `comparison/summary.json`: risultati, versioni, hash e limiti delle misure.
- `comparison/frames.csv`: dimensioni e codifica selezionata per ciascun frame.

La ricostruzione è verificata byte per byte per ogni frame in ciascuna delle tre
ripetizioni. I tempi riportati sono la mediana delle tre medie per frame, misurate
su questo PC; includono la selezione adattiva e il CRC, escludono inferenza,
conversione iniziale del tensore in byte, file e rete. Il decoder verifica anche il CRC.
La prova non valuta accuratezza di detection o codec con perdita.

I byte sono quelli del flusso applicativo sperimentale, non il traffico effettivo
Wi-Fi/TCP/MQTT/HTTP/WebSocket. Il riferimento aggiuntivo è un tensore per lato nei
metodi differenziali: 18.432 byte. Questo numero non include workspace zlib,
buffer temporanei, modello, tensor arena o runtime Python. Non è una misura
del picco di RAM su ESP32. Un singolo video e uno split non bastano per
generalizzare i vantaggi.

Riferimento per il compressore: [documentazione zlib di Python](https://docs.python.org/3.11/library/zlib.html).

## Prima prova con perdita controllata

Eseguita il 17 ottobre 2026, sempre su CPU PC. Il report e i dati numerici sono
conservati fuori da `results/` in [lossy_2026-10-17](lossy_2026-10-17/README.md).
La baseline del 15 ottobre non è stata modificata.

**Compressione indipendente:** ogni tensore si codifica e ricostruisce senza
usare attivazioni precedenti. **Temporale:** si conserva un riferimento tra frame.

La nuova prova arrotonda le attivazioni su una griglia:

```text
q = rint(float64(attivazione) / passo)       # interi int32, senza clipping
attivazione ricostruita = float32(q * passo)
```

Con passo `0,01`, per esempio, `1,234` diventa circa `1,23`: l'errore per valore
è al massimo circa `0,005`, più l'arrotondamento numerico. Non si cambiano i pesi
o gli operatori del modello, che rimane float32. Non è una conversione INT8.

- `independent`: q completo, byte shuffle e zlib livello 1.
- `temporal`: differenza intera tra q corrente e q precedente, stesso shuffle e
  compressore; completo iniziale e ogni 5 secondi, scelta del payload minore nei
  frame intermedi e fallback raw.

I due metodi ricostruiscono **gli stessi tensori approssimati** a ciascun passo:
il loro confronto in byte è a qualità identica. Il riferimento è il precedente
tensore di interi condiviso e verificato, senza usare il precedente float originale.
È una prima quantizzazione uniforme, non un'implementazione del metodo del paper
con dead-zone o una ricerca esaustiva dei codec con perdita.

Precisazione sul riferimento di Shiba et al., IEEE Access 2026,
[Delta Coding With Dead-Zone Quantization for Bandwidth-Efficient Split Computing
on Video Streams](https://da.lib.kobe-u.ac.jp/da/kernel/0100504251/0100504251.pdf),
sezioni III-B–D: nel loro DPCM si calcola prima il residuo rispetto alla precedente
ricostruzione condivisa e si quantizza il residuo; la variante D+DZ usa una zona
centrale più ampia mappata a zero nei frame predetti. Nel nostro prototipo si
quantizza prima l'intero tensore corrente e poi si codifica senza ulteriore perdita
la differenza tra gli interi. Non sono lo stesso quantizzatore né la stessa prova.
L'indipendente serve a isolare il beneficio temporale a identica ricostruzione;
il confronto di quantizzazione diretta e DPCM del paper può produrre ricostruzioni
diverse. La replica specifica di DPCM/dead-zone resta da implementare e valutare.

I chiarimenti del 18 ottobre su indipendente/temporale, significato dei tempi
TCP e risultati del paper sono nelle [sezioni 9.2–9.4 dell'analisi](../../ANALISI_COMPRESSIONE_ATTIVAZIONI.md#92-cosa-abbiamo-misurato-con-il-client-e-il-server-tcp--18-ottobre).
La proposta DPCM senza e con dead-zone resta un approfondimento sullo stesso
FOMO e sugli stessi input, dopo avere spiegato e specificato il nuovo codec.
La priorità successivamente concordata è verificare la rappresentazione INT8:
la prima prova PC è ora disponibile nell'archivio collegato all'inizio del README.
Con passo fisso e senza clipping, cambiare solo l'ordine tra sottrazione e
quantizzazione può lasciare quasi identica la ricostruzione: dichiarare le
differenze effettive di intervallo, precisione e dead-zone prima del confronto.
Le ricostruzioni dei nuovi metodi potranno differire: misurare byte ed errore,
senza estendere loro l'identità di ricostruzione dei due metodi attuali.

Il formato sperimentale AQST/AQF1 include metodo, passo, forma, dtype, parametri
zlib, hash modello, split, frequenza, rinnovi, sequenze, riferimento, lunghezza
e CRC degli interi ricostruiti. Il decoder riceve i parametri dal messaggio di
sessione; non consulta i tensori originali. Le verifiche contro gli originali
avvengono fuori dalle misure di tempo.

### Riproduzione

Su questa macchina `.venv` è stato ricreato come ambiente minimo per gli esperimenti.
Per ricrearlo su un'altra macchina Linux x86_64, con uv installato:

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r experiments/activation_compression/lossy_2026-10-17/requirements.txt
```

Quindi dalla radice del repository:

```bash
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python experiments/activation_compression/extract_activations.py \
  --video VideoWithCan.mp4 \
  --model-zip ei-object-detection-with-fomo---bottles-vs.-cans-object-detection-keras-h5-model-model.5.zip \
  --output-dir experiments/activation_compression/results/input_nuova_prova

CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 OMP_NUM_THREADS=1 \
  .venv/bin/python experiments/activation_compression/compare_lossy.py \
  --input-dir experiments/activation_compression/results/input_nuova_prova \
  --output-dir experiments/activation_compression/results/lossy_nuova_prova

.venv/bin/python -m unittest discover -s experiments/activation_compression -p 'test_*.py' -v
```

Il confronto rifiuta una directory che contiene già `summary.json`, per evitare
di sovrascrivere una misura precedente. Servono ffmpeg e ffprobe per l'estrazione.
Default: passi `0.0001 0.001 0.01 0.1 0.5 1.0`, 3 ripetizioni, 5 fps e sottoinsieme
a 1 fps. Opzioni: `--steps` e `--rounds`.

### Risultato preliminare e limiti

A 5 fps, passo `0,001`: indipendente **40,61%** di risparmio sul raw;
temporale **48,66%**, cioè **13,57%** di vantaggio aggiuntivo rispetto
all'indipendente allo stesso passo. Nessuna cella cambiata alla soglia 0,5 su
questo video rispetto al riferimento; i punteggi numerici cambiano comunque.
Passo `0,1`: risparmio temporale **68,28%**, con due celle cambiate alla soglia 0,5.
Passo `0,5`: risparmio **79,01%**, con 49 celle cambiate (20 perse, 29 introdotte).

Il riferimento presenta 151 celle oggetto su 21.024 celle-frame a soglia 0,5.
Non sono 151 oggetti distinti. Le metriche confrontano l'uscita con il modello
non compresso usando gli stessi batch del suffisso; non sono accuratezza rispetto
a etichette corrette e non applicano il postprocessing FOMO a componenti connesse.
Il massimo errore sull'uscita è riportato insieme alle celle cambiate: una media
piccola su molte celle di sfondo può nascondere differenze locali importanti.

Nessuna precisione è stata validata come accettabile per l'applicazione. Mancano
annotazioni, altri video/split e misure su dispositivo/rete/energia. Tempi solo PC;
18.432 byte di riferimento per lato non includono workspace e buffer temporanei.
I 15 test dei due prototipi sono passati.

## Verifica INT8 del modello

La prova [check_int8.py](check_int8.py) converte il modello intero prima in
TFLite float32 e poi in INT8, con ingresso/uscita int8 e nessun fallback float.
I primi 48 frame calibrano gli intervalli; i successivi 98 vengono valutati
rispetto a Keras. L'ispezione del tensore `block_2_add` avviene nel modello
intero: prefisso e suffisso INT8 separati non sono ancora esportati o verificati.

```bash
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 \
TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 \
.venv/bin/python experiments/activation_compression/check_int8.py \
  --input-dir experiments/activation_compression/results/input \
  --output-dir experiments/activation_compression/results/int8-new-run \
  --calibration-frames 48
```

La directory di destinazione deve essere vuota. Per ricaricare e verificare i
file salvati, vedere il [README dell'archivio INT8](int8_2026-10-18/README.md).
I 19 test senza socket comprendono i quattro nuovi test INT8. Modello, runtime
e protocollo SCIoT originali non sono stati modificati. Le precedenti prove di
compressione continuano a riferirsi a float32: non usare i loro risparmi come
previsione del beneficio temporale su INT8.

## Verifica 16×8 del modello

[check_16x8.py](check_16x8.py) converte una nuova variante integer-only con
ingresso/uscita INT16 e riusa i binari dei due controlli. La partizione è letta
dall'archivio INT8: nessun frame o parametro viene scelto in base al risultato.
Sono conservati tipi dei tensori/operatori, scale/zero point, predizioni, errori
e conteggi per frame. I sorgenti e gli archivi precedenti sono preservati.

```bash
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 \
TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 \
.venv/bin/python experiments/activation_compression/check_16x8.py \
  --input-dir experiments/activation_compression/results/input \
  --int8-archive experiments/activation_compression/int8_2026-10-18 \
  --output-dir experiments/activation_compression/results/16x8-new-run
```

Usare una directory vuota; istruzioni complete e verifica dei binari nel
[nuovo archivio](16x8_2026-10-18/README.md). I 23 test senza socket includono i
quattro nuovi controlli INT16. Prossimo passo: verificare il supporto INT8/INT16
del runtime Micro prima del porting e delle misure sulla scheda, ampliando poi
calibrazione e valutazione su sequenze distinte. I byte del confine sono osservati
nel modello intero; split distribuito e protocollo quantizzato restano da verificare.

## Esecuzione Micro sul PC e prefissi raggruppati

Il [report del 19 ottobre](../micro_execution_2026-10-19/README.md) raccoglie
la verifica INT8 con il runtime Micro e il confronto float32 fra layer separati,
prefisso ricreato e persistente. `compose_float_prefix.py` unisce direttamente
i binari originali; i comandi riproducibili sono in
[tests/firmware](../../tests/firmware/README.md#esperimenti-micro-int8-e-prefissi-float32).
Il confronto INT8 con l'archivio fallisce pur coincidendo con `BUILTIN_REF`;
questa distinzione è conservata nel report e nel codice di uscita.
