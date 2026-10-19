# Come provare modello e comunicazione sul PC

Verifiche del 18 ottobre 2026. Per queste prove non serve acquistare una camera
o una scheda: un programma Python svolge il lavoro del client e un secondo
processo svolge quello del server. I risultati non misurano le prestazioni ESP32.

## 1. Dati raccolti e prova del modello

Sono stati scaricati e verificati:

| Origine | Dati disponibili localmente | Uso nella prova completata |
|---|---:|---|
| [Beer vs. cans FOMO, set pubblico di test](https://studio.edgeimpulse.com/public/89078/latest/acquisition/testing) | 84 immagini con bounding box `beer`/`can` | Tutte le 84 immagini |
| [Visual Tracker Benchmark, Coke](https://rvlab.snu.ac.kr/research/tracker_benchmark) | 291 frame ordinati in ZIP | 32 frame scelti uniformemente |
| Stessa fonte, Liquor | 1.741 frame ordinati in ZIP | 32 frame scelti uniformemente |

I dati sono sotto `experiments/activation_compression/results/public_test_data/`:
immagini, due ZIP e `manifest.json` con URL, hash e annotazioni disponibili.
Il set Edge Impulse è dichiarato di test dal progetto pubblico corrente; non è
dimostrata la corrispondenza con la storia di addestramento del nostro H5 locale.
Le immagini del progetto non sono una sequenza temporale. Per OTB gli fps originali
non sono verificati e le annotazioni di tracking non sono etichette complete
di tutte le bottiglie e lattine presenti. I file immagine/ZIP restano fuori da Git.

Sui 148 input scelti, il FOMO candidato è stato eseguito sul PC sia intero sia
con prefisso e suffisso Keras separati: **massimo scostamento osservato 0,0**.
Sono state rieseguite anche le versioni TFLite float32, INT8 e 16×8 già salvate,
senza modificarle o ricalibrarle su questi dati.

| Variante | Max errore dei punteggi rispetto a Keras | Celle cambiate a soglia 0,5 |
|---|---:|---:|
| TFLite float32 | 0,00000629 | 0 |
| INT8 | 0,630236 | 35 |
| 16×8 | 0,607682 | 33 |

Il riferimento ha 355 celle oggetto su 21.312 celle-frame. Sono proxy di fedeltà,
non oggetti distinti o accuratezza su annotazioni. L'ordine delle classi nei canali
del nostro H5 resta da confermare: l'anteprima usa rosso per il canale 1 e blu per
il canale 2, senza assegnare loro automaticamente `beer` e `can`. Non è applicato
il postprocessing FOMO. Le annotazioni raccolte permettono una successiva
valutazione, dopo aver confermato etichette e preprocessing.

[Anteprima locale delle predizioni](experiments/activation_compression/results/public_images_2026-10-18/predictions.png)
(24 immagini scelte prima di guardare le predizioni; file locale ignorato da Git).
Il preprocessing di questa nuova prova usa Pillow Lanczos, ritaglio centrale,
grigio BT.601 e valori `[0,1]`; non è dimostrata parità pixel con Studio o FFmpeg.

Dalla radice del repository:

```bash
.venv/bin/python experiments/activation_compression/fetch_public_test_data.py \
  --output-dir experiments/activation_compression/results/public_test_data

CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 \
TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 \
.venv/bin/python experiments/activation_compression/check_public_images.py \
  --dataset-dir experiments/activation_compression/results/public_test_data \
  --model-input-dir experiments/activation_compression/results/input \
  --quantized-archive experiments/activation_compression/16x8_2026-10-18 \
  --output-dir experiments/activation_compression/results/public-images-new-run
```

Il downloader richiede Internet; le verifiche successive usano i file locali.
Il programma salva `summary.json`, `images.csv` e `predictions.png`. Usare una
directory di output vuota. I nuovi dati non sono stati usati per calibrare i modelli.

## 2. La comunicazione è già implementata?

**Sì, nel software originale:** sono presenti firmware ESP32 e server per MQTT,
HTTP e WebSocket. Nel codice attuale questi percorsi usano TCP; UDP non è
implementato come trasporto delle attivazioni. Il client Python degli autori
non è disponibile nella cartella `src/client/python/`, che contiene un README.

Esiste inoltre il nostro **prototipo TCP sperimentale**, separato dal protocollo
SCIoT, che include i codec indipendente e temporale. I codec non sono integrati
nei server originali o nel firmware. I due percorsi si provano in modo distinto.

## 3. Prova del vero percorso HTTP di SCIoT

È stato aggiunto [check_original_http.py](experiments/activation_compression/check_original_http.py).
Avvia un server locale in un processo e invia le richieste da un client Python:

```text
client PC: immagine → prefisso Keras → pacchetto binario SCIoT
                                      ↓ HTTP su 127.0.0.1
server PC: route originale → parser → suffisso TFLite → decisione dello split
```

La prova esegue registrazione, invio immagine RGB565, invio attivazioni e richiesta
del nuovo split. Usa le vere route `HttpServer`, `RequestHandler`, `Edge.run_inference`
e `OffloadingAlgo`, mantenendo codice e dati originali del progetto.

```bash
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 \
TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 \
.venv/bin/python experiments/activation_compression/check_original_http.py \
  --output-dir experiments/activation_compression/results/http-new-run
```

**Esito verificato:** richieste riuscite, server e client in processi distinti,
inferenza completata con massimo errore `2,38e-7` rispetto al modello Keras intero.
Lo split usato è `block_2_add`, indice 25 nel protocollo che esclude InputLayer.
Il server ha restituito un indice di split valido.

Questa prova usa il **modello RGB originale SCIoT**, ingresso `96×96×3` e uscita
`12×12×2`, distinto dal candidato in grigio Beer/can. Verifica il flusso software
e la coerenza numerica, senza attribuire nomi alle classi del modello originale.

Per isolare la prova, il programma copia statistiche e valutazioni nella propria
directory; gli originali vengono controllati tramite hash e non sono modificati.
Una sottoclasse di test sostituisce NTP con l'orologio del PC condiviso dai due
processi. Non vengono provati l'avvio ordinario `run_edge.py` e la sua inizializzazione
dei profili. I tempi dispositivo sono fixture nulle: non valutiamo l'ottimalità
della decisione, la latenza realistica o la concorrenza. L'uscita della rete viene
osservata dentro il server e salvata per il controllo; la risposta HTTP originale
conferma il successo e non restituisce le predizioni.

## 4. Prova dei codec attraverso il prototipo TCP

Per ripetere il confronto già disponibile usando le attivazioni del video:

```bash
.venv/bin/python experiments/activation_compression/socket_benchmark.py run \
  --input-dir experiments/activation_compression/results/input \
  --output-dir experiments/activation_compression/results/tcp-new-run \
  --rounds 1
```

Il comando avvia automaticamente il server separato e confronta raw, indipendente
e temporale, verificando tensori e uscite. Salva report e CSV. È un replay di
attivazioni già calcolate e usa il suffisso Keras, non il server HTTP originale.
I 5 fps descrivono il video campionato, non una velocità emulata dell'ESP32.
Non usare un elenco arbitrario di fotografie per dedurre guadagni temporali reali.

Questi programmi aprono socket locali: un ambiente di esecuzione ristretto può
richiedere il permesso di farlo. Non serve un broker per HTTP o per il prototipo TCP.
MQTT e WebSocket originali non sono stati rieseguiti in questa attività.

## 5. TCP e UDP: quando scegliere cosa

TCP fornisce un flusso ordinato e affidabile e ritrasmette dati persi. Un dato
mancante può ritardare la consegna di quelli successivi. HTTP e WebSocket di
questo progetto, come il suo MQTT, usano questo trasporto.

UDP invia datagrammi e non garantisce consegna, ordine o assenza di duplicati.
È utile quando l'applicazione può scartare dati vecchi e continuare, per esempio
in molti flussi multimediali o aggiornamenti di giochi in tempo reale. Le regole
per recuperare o ignorare le perdite dipendono dall'applicazione. UDP non è
automaticamente più veloce nel completare una richiesta corretta.

Qui il server richiede un tensore completo. Se lo suddividiamo tra più datagrammi,
servono identificativi, riordino, verifica dei pezzi e timeout. Con i codec temporali,
scartare un aggiornamento può invalidare il riferimento dei successivi: occorrono
anche regole per ripristinarlo. Alla richiesta di chiarimento dell'utente abbiamo
lasciato fermo l'esperimento UDP: **nessun nuovo trasporto UDP è stato implementato**.

## Artefatti della verifica completata

[Archivio dei risultati](experiments/activation_compression/public_pc_2026-10-18/README.md):
manifest dei dati, metriche sui 148 input, conteggi per immagine, controllo HTTP
e hash di integrità. Non abbiamo eseguito test o misure sulla scheda ESP32.
