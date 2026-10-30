# INT8 ESP-NN: attivazioni raw o compresse senza perdita

**Risultati:** [rapporto del 28 ottobre 2026](2026-10-28/report.md) e
[dati riassunti](2026-10-28/summary.json), due sessioni con 816 richieste validate.

Confronto su una ESP32-S3-EYE e un server HTTP sul PC: inviare i 4.608 byte INT8
di `block_2_add` direttamente oppure comprimere ogni tensore con miniz 3.0.2,
formato zlib, livello 1. Le due modalità usano **lo stesso interprete INT8**,
modello, input, preprocessing e punto di divisione del precedente
[benchmark ESP-NN](../esp32_representation_benchmark/README.md).

La compressione è indipendente per frame e senza perdita aggiuntiva: non è
compressione temporale, riaddestramento, quantizzazione del residuo o EON.
Si invia sempre il risultato zlib, anche quando espande i dati: nessun fallback
adattivo confonde il confronto. I risultati non si trasferiscono automaticamente
al server originale SCIoT o a client concorrenti.

## Protocollo e timer

`POST /infer`, intestazione applicativa little endian `<8I>` di 32 byte:
magic `SCC2`, versione 2, codec (0 raw / 1 zlib), frame, iterazione,
lunghezza ricostruita, lunghezza trasmessa, CRC32 dei byte originali.
La ricostruzione deve essere esattamente 4.608 byte; massimo payload 8.192 byte.
Il decoder limita l'output a 4.609 byte per rilevare espansioni abusive, rifiuta
stream incompleti, concatenati o seguiti da dati, e verifica dimensioni e checksum.
Il suffisso riceve gli stessi int8 e gli stessi parametri di quantizzazione.

La risposta mantiene 1.760 byte: otto uint32 (`SCR1`, versione 2, frame,
iterazione, 432 valori, tempi decode/invoke/post in microsecondi), seguiti
da 432 punteggi FLOAT32. Il postprocessing FOMO è incluso nel tempo server.

Il tempo completo include input, prefisso, checksum, reset e compressione,
impacchettamento, connessione TCP, HTTP, decode, suffisso e risposta completa.
Sulla camera include `esp_camera_fb_get` e preprocessing, senza misurare l'età
del frame già in coda o l'inizio esposizione. I tempi server sono già dentro HTTP.
Allocazione del workspace e inizializzazione sono fuori dal timer; il reset
per ciascun tensore è incluso. Hash diagnostici e stampa seriale sono dopo il
timer del campione. Per le sequenze continue, controlli hash e cleanup sono
compresi e le stampe sono rinviate a fine sequenza.

## Campioni e verifiche

Ogni sessione comprende 408 richieste:

- Tre immagini canoniche × 20 ripetizioni × due modalità, ordine alternato.
- Tutte le 84 foto annotate × due modalità su ingressi identici.
- 20 coppie camera alternate con frame distinti.
- Quattro sequenze continue da 20 frame, ordine raw/zlib/zlib/raw.

Due sessioni usano lo stesso firmware. Il checker verifica campioni attesi,
identità del modello e degli input, chiamate ai kernel ottimizzati, pacchetti,
checksum, hash dispositivo/server e postprocessing. Sui 87 ingressi fissi
richiede identità esatta di attivazioni e punteggi fra raw/zlib e ripetizioni.
Le immagini camera hanno un CRC del tensore originale, ma ingressi distinti.

I test nativi compilano i veri sorgenti miniz e provano il riutilizzo del
compressore su dati reali, ripetitivi e incomprimibili; Python deve ricostruire
esattamente i byte C. I test del parser coprono intestazioni, limiti, stream
corrotti, troncati e concatenati. L'esito nativo non misura velocità ESP32.

La qualità usa lo stesso decoder del benchmark precedente. I conteggi ignorano
la classe, perché l'ordine beer/can nell'H5 non è confermato; la corrispondenza
tra dataset pubblico e training del modello non è dimostrata. Il test lossless
richiede uguaglianza rispetto a INT8 raw, non una nuova approvazione della qualità.

## Preparazione e riproduzione

Richiede gli artefatti locali del benchmark precedente, la venv TensorFlow del
repository e PlatformIO 6.1.18 con `espressif32@6.10.0` / ESP-IDF 5.4.0.
Usare una cache PlatformIO dedicata per evitare interferenze fra sessioni.
Le revisioni Espressif sono quelle del manifest della baseline; miniz è fissato
a `293d4db1b7d0ffee9756d035b9ac6f7431ef8492`.

```sh
.venv/bin/python experiments/esp32_int8_compression_benchmark/prepare.py
python3 experiments/esp32_int8_compression_benchmark/idf/fetch_components.py
python3 experiments/esp32_int8_compression_benchmark/idf/fetch_miniz.py
.venv/bin/python -m unittest discover -s experiments/esp32_int8_compression_benchmark -p 'test_*.py' -v
pio run -d experiments/esp32_int8_compression_benchmark/idf
```

`prepare.py` verifica e copia modelli/input senza conversione o calibrazione.
Per la prima preparazione copia le credenziali locali dalla baseline nel file
ignorato `include/network.local.h`: verificare indirizzo PC e porta 8783.
Credenziali, firmware, backup e dati grezzi restano fuori da Git.

Prima del caricamento salvare l'intera flash e verificarne il digest **senza
riavviare l'applicazione tra lettura e verifica**, perché il firmware può scrivere
il proprio stato persistente durante l'avvio. Usare esptool con `--after no-reset`
per la lettura e `--before no-reset --after no-reset` per `verify-flash`.

```sh
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 .venv/bin/python -u experiments/esp32_int8_compression_benchmark/server.py --port 8783 --output experiments/esp32_int8_compression_benchmark/results/NUOVO-RUN/server
```

In un secondo terminale, caricare e catturare la sessione:

```sh
pio run -d experiments/esp32_int8_compression_benchmark/idf -t upload --upload-port PORTA
python experiments/esp32_representation_benchmark/capture.py --port PORTA --log experiments/esp32_int8_compression_benchmark/results/NUOVO-RUN/device.log --timeout 900
.venv/bin/python experiments/esp32_int8_compression_benchmark/analyze.py --run experiments/esp32_int8_compression_benchmark/results/NUOVO-RUN
```

Per la seconda sessione riavviare il server sulla stessa porta con output nuovo,
poi usare `capture.py --reset` con un nuovo log. Pubblicare con:

```sh
.venv/bin/python experiments/esp32_int8_compression_benchmark/publish_report.py --runs experiments/esp32_int8_compression_benchmark/results/RUN1 experiments/esp32_int8_compression_benchmark/results/RUN2 --output experiments/esp32_int8_compression_benchmark/2026-10-28
```

Al termine ripristinare tutta la flash dal backup verificato e verificare hash
di scrittura e avvio del firmware preesistente. Confrontare byte/frame a pari
frequenza di elaborazione per parlare di riduzione del traffico/s. Meno byte
non implica automaticamente meno attesa: riportare entrambi i risultati.

Fonti: [miniz 3.0.2](https://github.com/richgel999/miniz/tree/3.0.2),
[ESP-NN](https://github.com/espressif/esp-nn),
[esp-tflite-micro](https://github.com/espressif/esp-tflite-micro).
