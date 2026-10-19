# Esecuzione Micro sul PC e costo dei layer separati — 19 ottobre 2026

**Esperimenti implementati ed eseguiti. Float32 supera le verifiche numeriche;
INT8 fallisce il confronto esatto con i vettori archiviati, ma coincide con i
kernel desktop di riferimento. Nessuna misura o verifica ESP32.**

## Cosa fa l'interprete e cosa confrontiamo

L'interprete legge il modello, prepara lo spazio per i tensori e richiama le
operazioni di calcolo. Nel client originale ciascun layer è un modello distinto:
si ricrea un interprete per layer e per immagine. Non è un requisito intrinseco
della rete. Per la rete completa sono 59 modelli, contenenti complessivamente
88 operatori TFLite; layer e operatore non sono sinonimi.

Sono stati composti quattro prefissi (0/11/25/58 inclusivi) dai FlatBuffer
originali, senza riconversione o riaddestramento. Conservati operatori, versioni,
opzioni e costanti; collegati i rami residui 16→25, 34→43, 43→52. La verifica
strutturale e numerica è automatizzata. I prefissi e gli eseguibili sono artefatti
generati nelle directory ignorate, con hash nel report.

Tre modalità usano lo stesso runtime, resolver di sette operatori e ingressi:

1. **Separati:** la funzione di produzione `runFloatLayer` prepara un interprete
   per ogni layer, copia gli ingressi, esegue e copia l'uscita.
2. **Raggruppato ricreato:** un interprete per prefisso, ricreato per immagine.
3. **Raggruppato persistente:** un interprete per prefisso, preparato inizialmente
   e riutilizzato. Il costo iniziale è registrato separatamente.

## Risultati float32

Tutte le uscite confrontate coincidono nei casi provati: errore massimo osservato
**0**, sia nella verifica nativa con sanitizer sia in Release, rispetto alla
catena dei binari originali eseguita con i kernel desktop `BUILTIN_REF`.
Tolleranza dichiarata invariata: `rtol=1e-5`, `atol=1e-5`. Tre input sintetici:
zero, casuale con seed 20261019, gradiente. Non è una valutazione di accuratezza.

Tempi in millisecondi, mediana dei 90 campioni per modalità/split (30 per ciascuno
dei tre input), dopo cinque riscaldamenti per combinazione. Riduzione temporale
calcolata rispetto ai separati. CSV con tutti i **1.080 campioni** e JSON con
mediana/percentili 10 e 90 separati per input.

| Split | Separati ms | Raggruppato ricreato ms | Raggruppato persistente ms | Riduzione persistente sul PC |
|---|---:|---:|---:|---:|
| 0 | 1.257 | 1.259 | 1.263 | -0.48% |
| 11 | 3.514 | 3.428 | 3.421 | 2.63% |
| 25 | 4.992 | 4.854 | 4.866 | 2.52% |
| 58 | 7.185 | 7.012 | 7.025 | 2.23% |

Il persistente non risulta sistematicamente più rapido del raggruppato ricreato.
La differenza fra queste due modalità è piccola in questa sessione; il benchmark
non stabilisce che una sia sempre preferibile. Anche il controllo a un solo
layer mostra una piccola variazione sfavorevole al persistente.

Il timer comprende copia iniziale nell'area di lavoro, preparazioni per immagine,
calcolo, copia finale e distruzione degli interpreti temporanei. Caricamento dei
file, riserva delle arene, costruzione del resolver, verifiche e stampa sono
esclusi. Ordine delle modalità alternato deterministicamente; input alternati.
CPU non vincolata a un core e carico esterno non controllato: questi dati sono
una sessione sul PC, non una stima del vantaggio sull'ESP32.

| Split | Copie esplicite separati, byte/frame | Copie raggruppati, byte/frame | Massimo arena separati, byte PC | Arena raggruppato, byte PC |
|---|---:|---:|---:|---:|
| 0 | 368,640 | 368,640 | 258,848 | 258,848 |
| 11 | 5,400,768 | 682,176 | 903,984 | 907,296 |
| 25 | 8,055,168 | 239,616 | 903,984 | 911,920 |
| 58 | 11,026,560 | 222,336 | 903,984 | 924,768 |

Le copie sono conteggi delle operazioni esplicite dell'applicazione, inclusa la
copia iniziale dell'immagine (110.592 byte); non sono tutto il traffico fisico
della memoria. Il conteggio precedente di 10.915.968 byte per la rete completa
escludeva questa copia iniziale. La rappresentazione e questi conteggi restano
validi indipendentemente dalla velocità del PC; i tempi e l'uso dell'arena
sono legati alla piattaforma.

Tutte le modalità float usano arene con capacità sperimentale di **8 MiB**.
Il percorso richiede logicamente un buffer esterno di lavoro da 460.992 byte;
il percorso separato richiede anche il buffer residuo da 460.992 byte.
Il banco mantiene più arene/buffer per alternare le modalità: la tabella non è
il picco RAM del processo e non misura la RAM dell'ESP32. I prefissi raggruppati
usano un poco più arena nativa, ma evitano il buffer residuo esterno nel loro
percorso di esecuzione. Nessun dimensionamento del firmware è stato cambiato.

## INT8: fallimento del riferimento archiviato e diagnosi

Usati i binari e i vettori originali, con hash verificati. Frame 48, 96 e 145;
arena 512 KiB, resolver di cinque operatori, interprete persistente per stadio.
**144 invocazioni** con ASan/UBSan, incluse due warmup e dieci prove per ciascuno
dei tre input nei quattro percorsi. Risultati stabili con ingressi alternati;
nessuna segnalazione dei sanitizer.

| Stadio | Massimo valori diversi dall'archivio per frame | Massimo errore in unità INT8 | Arena usata, byte PC |
|---|---:|---:|---:|
| full | 15 | 15 | 239,328 |
| prefix | 680 | 4 | 230,704 |
| suffix | 0 | 0 | 66,816 |
| suffix_chain | 15 | 15 | 66,816 |

`suffix` riceve il confine archiviato; `suffix_chain` riceve il confine realmente
prodotto da Micro. Gli output sono conservati in `int8-actual-outputs.npz`.

Controlli diagnostici indipendenti sui tre frame:

- Micro coincide byte per byte con TensorFlow Lite desktop **BUILTIN_REF** per
  full, prefix e suffix.
- I vettori archiviati coincidono con **BUILTIN_WITHOUT_DEFAULT_DELEGATES**,
  il percorso desktop usato in precedenza.
- Il modello completo Micro e prefix→suffix Micro coincidono byte per byte.
- La prima parte Micro differisce dal confine archiviato; la seconda parte
  Micro, alimentata con il confine archiviato, riproduce le uscite archiviate.

Queste prove localizzano una differenza fra percorsi numerici del runtime,
già visibile nel prefisso. Non identificano ancora il primo operatore o la
regola di arrotondamento responsabile. Non dimostrano una perdita di accuratezza
su annotazioni. Non sono stati modificati runtime, modello o vettori per far
passare il test: `int8-summary.json` mantiene **passed=false** e il comando
restituisce **2**. Prima di usare i vettori come oracolo hardware occorre scegliere
esplicitamente il riferimento numerico; il confronto esatto precedente resta aperto.

## Riproduzione e verifiche

Ambiente di questa prova: **AMD Ryzen 7 8845HS w/ Radeon 780M Graphics**,
c++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0, TensorFlow 2.15.0,
TensorFlowLite_ESP32 1.0.0. Versioni complete, hash sorgenti/runtime/eseguibili
e comandi del compilatore nei due JSON.

```bash
.venv/bin/python tests/firmware/check_experiments.py int8 \
  --output-dir experiments/activation_compression/results/int8-reproduction

.venv/bin/python tests/firmware/check_experiments.py float \
  --output-dir experiments/activation_compression/results/float-reproduction

.venv/bin/python -m unittest discover -s experiments/activation_compression -p 'test_*.py'
.venv/bin/python -m unittest discover -s experiments/esp32_int8_firmware -p 'test_*.py'
.venv/bin/python tests/firmware/check_firmware.py
```

Usare directory di output nuove. Entrambi i comandi accettano `--runtime` per
la directory `src` della stessa versione della libreria. I log precedenti non
vengono sovrascritti. L'uscita 2 della prova INT8 è attualmente attesa e non va
confusa con un successo. Errori di configurazione/esecuzione terminano con 1.

Passati **36 test degli esperimenti**, inclusi cinque nuovi test del compositore,
e **4 test del verificatore seriale**. Il controllo nativo originale ripetuto
supera **1.170 invocazioni**, confronto di 33.363.072 float senza differenze e
quattro pacchetti letti dal parser originale. I messaggi di errore nel suo
stderr sono le prove negative intenzionali.

Build di correttezza con ASan/UBSan e `-O1`; benchmark con `-O3`, senza sanitizer.
Entrambe mantengono i controlli con `-UNDEBUG`, `-ffp-contract=off` e
`-fno-fast-math`. I benchmark partono solo dopo la verifica di correttezza.
I log di compilazione e i report sono conservati in questa cartella.

Questa fase non integra i prefissi nei client, non cambia server o protocollo,
e non misura camera, rete, energia o selezione dinamica dello split. I tempi
escludono ricerca dei modelli per nome e watchdog del firmware. Rimangono da
valutare sull'ESP32 tempi/memoria e il compromesso fra conservazione dei prefissi
in flash e possibilità di cambiare split durante l'esecuzione.
