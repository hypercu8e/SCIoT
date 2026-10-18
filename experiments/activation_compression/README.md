# Primo confronto della compressione delle attivazioni

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
