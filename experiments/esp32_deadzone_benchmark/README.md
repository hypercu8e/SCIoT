# DPCM e dead-zone su FOMO INT8, ESP32-S3-EYE

**Risultati:** [rapporto del 29 ottobre](2026-10-29/report.md),
[grafico](2026-10-29/tradeoff.png) e [verifiche](2026-10-29/verification.json).
Campagna completa: 4224 richieste misurate e 720 diagnostiche, video e camera,
due giri in ordine invertito; flash originale ripristinata e verificata.

Esperimento isolato: prefisso INT8 con ESP-NN sulla scheda, codec C++, HTTP al PC,
ricostruzione e suffisso TFLite INT8. Modello e runtime sono quelli del
[benchmark fisico precedente](../esp32_int8_compression_benchmark/README.md).
Non modifica il server SCIoT o il firmware multi-client.

Il metodo adatta [Shiba et al., IEEE Access 2026, sezioni III e V](https://da.lib.kobe-u.ac.jp/da/kernel/0100504251/0100504251.pdf)
al FOMO già quantizzato. Non riproduce i modelli, dataset e risultati originali.

## Confronto

Dodici configurazioni: INT8 raw, zlib 1, zlib 6, e tre metodi a 4/6/8 bit:
quantizzazione indipendente, DPCM uniforme, DPCM con dead-zone. Zlib indica il
formato DEFLATE prodotto da miniz 3.0.2 fissato alla revisione
`293d4db1b7d0ffee9756d035b9ac6f7431ef8492`; il paper misura la libreria zlib a
livello 6. Non si assume identità di byte o prestazioni fra le implementazioni.
Nessun compressore ad hoc o fallback adattivo.

Si dequantizza l'INT8 originale con scala/zero-point del confine. Il riferimento
condiviso e le ricostruzioni sono float32. Il server converte la ricostruzione in
INT8 con i parametri del suffisso: misuriamo sia l'errore float sia quello dopo
questa conversione. Il confronto raw usa le attivazioni prodotte dalla scheda,
non attivazioni inferite da un prefisso desktop.

## Specifica numerica

- Ordine C del tensore `(24,24,8)`, 4608 elementi. Dequantizzazione in double e
  arrotondamento esplicito a float32; residuo da differenza in double poi float32.
- `R` è P99 di `abs(x)` con rango `ceil(.99*N)`; per i P-frame `x` è il residuo
  rispetto alla precedente ricostruzione. Ogni messaggio trasmette R come float32.
  Si calcola sul solo tensore corrente, senza calibrazione su frame futuri.
- `step=2*R/2^b`, `index=rint(x/step)`, pareggi al pari, saturazione all'intervallo
  `[-2^(b-1), 2^(b-1)-1]`. Questa politica esplicita gli estremi dell'adattamento:
  l'estremo positivo ricostruibile è R-step, quello negativo -R.
- Sui soli P-frame D+DZ, `abs(x)<.75*step` produce indice zero; fuori dalla zona
  si applica la stessa quantizzazione uniforme. R=0 produce tutti indici zero.
- Dequantizzazione del simbolo in double poi float32, aggiunta al riferimento in
  double poi float32. Indice zero sempre positivo prima della moltiplicazione,
  per evitare divergenze del checksum dovute a `-0.0`.
- Primo frame completo, poi un completo ogni 30 frame elaborati; la dead-zone non
  si applica ai completi. Tutti i metodi nuovi usano un byte firmato per indice,
  senza bit packing o shuffle, seguito da un flusso zlib indipendente a livello 6.
- La riconversione al suffisso usa `rint(value/scale+zero)` e saturazione INT8.
  Non si assume il limite mezzo passo in presenza di clipping/dead-zone.

## Protocollo SDZ1

Header little endian di 80 byte, 20 uint32 nell'ordine:

`magic, version, device, session, config, seq, ref, kind, frame, source, bits,
level, radius_bits, count, length, original_crc, state_crc, input_crc,
diagnostic_source, header_crc`.

`magic=SDZ1`, versione 1; device è CRC32 del MAC, session è un nuovo numero
casuale per sequenza. `ref=0xffffffff` sui completi; altrimenti seq-1. `kind` è
0 completo/1 differenziale, `source` è 0 video/1 camera/2 diagnostica. R è
serializzato come bit IEEE754. CRC header sui primi 76 byte; CRC stato sui 18432
byte float32 little endian. Il CRC dell'originale diagnostica il riferimento raw,
non è usato per ricostruire il segnale con perdita. Payload massimo 8192 byte,
ricostruzione dei simboli limitata a esattamente 4608 byte. Stream zlib troncati,
concatenati, espansi oltre il limite o seguiti da dati vengono rifiutati.

Risposta SDR1: 12 uint32 (`magic, version, device, session, config, seq, frame,
decode_us, invoke_us, post_us, state_crc, activation_crc`) e 432 punteggi float32.
Il dispositivo correla e verifica la risposta prima di impegnare il riferimento.
Il server conserva solo l'ultima sessione per dispositivo, massimo quattro
dispositivi; è un benchmark con un singolo worker e una singola scheda.

Errore di comunicazione interrompe e invalida la prova: al successivo avvio si
creano sessioni nuove con completi iniziali. Nessun tentativo silenzioso di
continuare da uno stato incerto. Cambi di configurazione nella stessa sessione,
delta senza riferimento e sequenze duplicate/fuori ordine sono rifiutati.

## Misure fisiche

Ogni esecuzione comprende due giri, ordine configurazioni crescente/decrescente:

- Video: 146 ingressi originali float32 a 5 fps, incorporati in flash; ogni frame
  viene realmente inferito sulla ESP32. Il replay procede senza attese, quindi
  5 fps è il campionamento della sorgente, non un throughput misurato.
- Camera: 30 frame consecutivi per configurazione e giro. Le attivazioni INT8
  originali vengono salvate in un buffer diagnostico e inviate DOPO la sequenza.
  Il server le inferisce come riferimento raw per quegli stessi frame.
- Totale: 4224 richieste misurate, 720 richieste diagnostiche separate.

Il ciclo include preparazione ingresso, inferenza, quantizzazione/ricostruzione,
compressione, checksum, pacchetto, HTTP con apertura/chiusura della connessione,
suffisso e risposta, cleanup e commit del riferimento. Nella camera include
acquisizione e preprocessing, non l'età del frame o l'inizio esposizione.
Il tempo server è già dentro rete/ciclo. Il server salva i pacchetti prima
della risposta: quel costo comune è incluso. Allocazione/cambio livello miniz
fuori misura, reset per frame incluso. Copie diagnostiche incluse nel throughput,
stampe e upload diagnostici fuori dall'intervallo di sequenza. I byte TCP/IP,
ACK e ritrasmissioni non sono catturati.

Il limite d'attesa HTTP sulla scheda è 60 secondi, uguale per tutte le modalità:
attese lunghe riuscite restano interamente nei tempi e nel throughput. Un errore
interrompe comunque la prova. Sonde GET prima/dopo l'inizializzazione camera
sono fuori misura e registrano RSSI/canale; non vengono contate come inferenze.
Le prove preliminari con limite 15 secondi hanno riprodotto timeout di apertura
o risposta anche in modalità raw. Trattenere il framebuffer non li ha risolti,
quindi il firmware finale conserva il comportamento della baseline.
Anche la pausa esplicita DMA/interrupt non ha risolto i timeout ed è stata rimossa.
Il clock camera finale è **20 MHz**, come nell'esempio del driver ufficiale,
contro i 16 MHz dei benchmark precedenti. La verifica breve a 20 MHz ha completato
30 frame raw e 30 diagnostici; la sequenza misurata è durata 7,394 secondi.
Il confronto completo rimisura tutte le modalità con lo stesso clock; non isola
il beneficio del solo cambio di clock dalle condizioni radio variabili.

Tutte le modalità condividono un interprete, arena riservata di 1 MiB in PSRAM,
buffer di stato/riferimento da 18432 byte ciascuno, scratch da 18432, simboli da
4608, buffer compressione da 8192 e messaggio da 8272, diagnostica da 138240 e
buffer di campioni per 146 frame. Le minime heap sono cumulative dal boot e non
dimostrano il picco di firmware separati. Il livello 1 del vecchio benchmark va
rimisurato con la nuova strumentazione, non confrontato come tempo assoluto.

## Preparazione e verifica

Richiede gli artefatti locali precedenti, Python 3.11/TensorFlow 2.15 nella venv
del repository, compilatore C/C++ host e PlatformIO 6.1.18, ESP-IDF 5.4.0.
I sorgenti Espressif vengono copiati dalle revisioni immutabili già disponibili.

```sh
.venv/bin/python experiments/esp32_deadzone_benchmark/prepare.py
python3 experiments/esp32_deadzone_benchmark/idf/fetch_components.py
python3 experiments/esp32_deadzone_benchmark/idf/fetch_miniz.py
.venv/bin/python -m unittest discover -s experiments/esp32_deadzone_benchmark -p 'test_*.py' -v
PLATFORMIO_CORE_DIR="$PWD/experiments/esp32_deadzone_benchmark/results/platformio-core" experiments/esp32_deadzone_benchmark/results/build-tools/bin/pio run -d experiments/esp32_deadzone_benchmark/idf
```

Preparare un ambiente separato sotto `results/build-tools` con PlatformIO
6.1.18, pyserial 3.5 ed esptool 5.1.0. Le credenziali locali vengono copiate nel
file ignorato `include/network.local.h`, porta 8785; non stampare o pubblicare
quel file o firmware/backup che possono contenerle.

Avviare il server, scegliendo una directory di esecuzione nuova:

```sh
.venv/bin/python -u experiments/esp32_deadzone_benchmark/server.py --output experiments/esp32_deadzone_benchmark/results/NUOVO-RUN/server
```

In un secondo terminale, con uso esclusivo della scheda:

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_deadzone_benchmark/run_hardware.py --port /dev/ttyACM0 --run experiments/esp32_deadzone_benchmark/results/NUOVO-RUN
.venv/bin/python experiments/esp32_deadzone_benchmark/analyze.py --run experiments/esp32_deadzone_benchmark/results/NUOVO-RUN
```

Il runner salva e verifica tutti gli 8 MB senza riavviare fra lettura e verifica.
Carica il firmware solo dopo la verifica e ripristina la flash originale in
`finally`, verificandola prima del boot e conservando il log d'avvio.
Richiede accesso USB e rete esterno alla sandbox. Non scollegare la scheda finché
non è completato il ripristino; i backup restano nella directory ignorata.

`--seed-backup PERCORSO` permette di riusare un precedente backup verificato:
aggiorna i primi 64 KiB contenenti boot/partizioni/NVS e verifica comunque il
digest di tutti gli 8 MB contro la scheda corrente. Se non coincide, rilegge
l'intera flash. Lettura/verifica/scrittura usano una sola connessione esptool.
`--camera-only` esegue una diagnosi separata di 30 frame raw e 30 originali;
l'analizzatore del confronto completo la rifiuta deliberatamente.
`--video-only` esegue entrambi i giri delle 12 modalità sul video nella ESP32,
senza attivare il sensore. Per questa fase l'audit richiede esplicitamente
`analyze.py --video-only`; controlla 3504 richieste e 24 sequenze complete e
indica nel rapporto che la camera dal vivo non è stata validata.

L'analizzatore rifiuta run incompleti, errori dispositivo, modelli/kernel/input
errati, riferimenti diversi e percorsi lossless non esatti. Produce report,
CSV per frame e JSON con byte, tempi, memoria ed errori prima/dopo INT8.
Le celle e i rilevamenti sono fedeltà al raw, non accuratezza annotata; nessuna
tolleranza applicativa è assunta accettabile.

Per il grafico usare il Python di sistema con matplotlib già installato; non è
una dipendenza del runtime TensorFlow o del firmware. Per esportare gli artefatti
piccoli, dopo audit e ripristino verificati:

```sh
MPLCONFIGDIR="$PWD/experiments/esp32_deadzone_benchmark/results/mpl-cache" python3 experiments/esp32_deadzone_benchmark/plot_report.py --run experiments/esp32_deadzone_benchmark/results/NUOVO-RUN
python3 experiments/esp32_deadzone_benchmark/publish_report.py --run experiments/esp32_deadzone_benchmark/results/NUOVO-RUN --output experiments/esp32_deadzone_benchmark/DATA-NUOVA
```

L'esportazione include CSV, JSON, report, grafico, esito test, digest e riepilogo
delle diagnosi preliminari. Esclude flash, firmware, credenziali e pacchetti.
