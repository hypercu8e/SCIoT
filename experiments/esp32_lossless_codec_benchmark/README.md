# Codec lossless INT8: Rice indipendente e temporale

Ultima verifica mirata su FOMO INT8, split `block_2_add`, 4608 byte/frame.
Obiettivo: ridurre il ciclo completo conservando esattamente le attivazioni del
raw e le uscite del medesimo suffisso. Esperimento isolato dal servizio SCIoT.

## Stato

Il confronto PC è in [pc_2026-10-30/report.md](pc_2026-10-30/report.md).
Gli ingressi rigenerati coincidono con l'hash archiviato. Attivazioni desktop,
non misure ESP32. Test nativi e TCP verificano lossless e packing a qualità identica.
Firmware compilato e verificato (ESP-IDF 5.4.0, ESP-NN, CPU 240 MHz); 18 test superati, inclusi decoder nativo e TCP reale.
**Campagne concluse:** [rapporto unico](report.md), [riepilogo numerico](campaign-summary.json).
16128 richieste fisiche misurate e 360 diagnostiche, quattro campagne auditate;
firmware originale ripristinato e avvio verificato dopo ciascuna.
Rice temporale riduce il payload del 45,01% preservando tutti i byte e le uscite
rispetto al raw INT8. Sulla rete ordinaria non supera il criterio di latenza;
con proxy 128/512 kbit/s le mediane aggregate scendono rispettivamente del
26,91% e dell'8,51%, con criterio superato in tutte le tre coppie.
Il recupero dichiarato di un prefisso identificativo USB a 128 kbit/s è descritto
nel rapporto; tutti i tempi originali sono integri, nessuna stima.
Le prove restano isolate dal servizio SCIoT.

Aggiornamento del 1 novembre: la [nuova campagna hardware della soglia](../esp32_rice_threshold_benchmark/sweep_2026-11-01/report.md)
è isolata in un'altra cartella e usa l'hotspot attuale. Su 7008 richieste,
600/800 kbit/s superano il criterio completo, 900/1000 no: fascia osservata
800–900 kbit/s per il margine operativo, non pareggio. I dati e le campagne
storiche di questa cartella restano riferiti alla rete di ottobre.

## Metodi

- `raw`: INT8 originale, senza dequantizzazione e senza stato float.
- `zlib1`: miniz al livello 1 fissato alla revisione della campagna precedente.
- `rice_independent`: sottrazione dello zero-point in INT16, ZigZag e Rice.
- `rice_temporal`: sottrazione del precedente INT8 ricostruito, stessa codifica.
- `deadzone4_zlib` e `deadzone4_packed`: stesso quantizzatore C++ D+DZ4 precedente,
  codifica finale miniz6 o due simboli a 4 bit per byte. Sono con perdita rispetto
  al raw; il packing preserva esattamente la ricostruzione D+DZ4.

Rice seleziona k=0..8 per ogni canale, minimizzando il numero esatto di bit
(compreso il terminatore unario); a parità sceglie k minore. I primi otto byte
sono i parametri; i simboli seguono l'ordine C del tensore, MSB-first. Il quoziente
è una sequenza di zeri terminata da uno; seguono k bit di resto. Padding finale
nullo. ZigZag: 2*r per r>=0, -2*r-1 altrimenti. Nessun parametro usa frame futuri.
Se il Rice completo non è più piccolo di 4608 byte, si invia raw; la selezione
resta inclusa nel tempo. Completo iniziale e ogni 30 frame; ogni ACK valido
impegna il nuovo riferimento, inclusi i fallback raw.

## Preparazione PC

Dalla radice, usare la venv TensorFlow 2.15 già documentata nel progetto:

```sh
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 TF_NUM_INTRAOP_THREADS=1 TF_NUM_INTEROP_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python experiments/activation_compression/extract_activations.py --video VideoWithCan.mp4 --model-zip ei-object-detection-with-fomo---bottles-vs.-cans-object-detection-keras-h5-model-model.5.zip --output-dir experiments/activation_compression/results/input
.venv/bin/python experiments/esp32_representation_benchmark/prepare.py
.venv/bin/python experiments/esp32_lossless_codec_benchmark/prepare.py
.venv/bin/python -m unittest discover -s experiments/esp32_lossless_codec_benchmark -p 'test_*.py' -v
.venv/bin/python experiments/esp32_lossless_codec_benchmark/benchmark_pc.py --output experiments/esp32_lossless_codec_benchmark/results/NUOVO-PC
```

La preparazione verifica gli hash canonici e riusa gli stessi modelli convertiti,
senza calibrazione o addestramento. Il benchmark PC invoca il suffisso su ogni
ricostruzione; non dimostra equivalenza tra prefisso desktop ed ESP-NN.

Creare `results/build-tools` con Python 3.11 e installare PlatformIO 6.1.18,
pyserial 3.5, esptool 5.1.0 e matplotlib 3.10.8 (grafici). `idf/fetch_components.py` e `idf/fetch_miniz.py`
recuperano revisioni immutabili. Preparazione strumenti dalla radice:

```sh
.venv/bin/python -m venv experiments/esp32_lossless_codec_benchmark/results/build-tools
experiments/esp32_lossless_codec_benchmark/results/build-tools/bin/pip install platformio==6.1.18 pyserial==3.5 esptool==5.1.0 matplotlib==3.10.8
python3 experiments/esp32_lossless_codec_benchmark/idf/fetch_components.py
python3 experiments/esp32_lossless_codec_benchmark/idf/fetch_miniz.py
```

Compilare dalla radice con:

```sh
experiments/esp32_lossless_codec_benchmark/results/build-tools/bin/pio run -d experiments/esp32_lossless_codec_benchmark/idf
```
Per Rice il timer `compression_us` include residui, scelta k e bitstream;
`quantize_reconstruct_us` riguarda il percorso float del controllo D+DZ.
Credenziali nel solo
`include/network.local.h` ignorato, SERVER_URL al PC porta 8786 `/infer`.

Dopo ogni build riuscita eseguire `.venv/bin/python experiments/esp32_lossless_codec_benchmark/verify_build.py`; il runner rifiuta binari o sorgenti diversi dalla verifica.

## SLC2, protocollo sperimentale

Header little endian `<20I`, 80 byte, stessi campi strutturali SDZ1:
`magic,version,device,session,config,seq,ref,kind,frame,source,bits,level,
radius_bits,count,length,original_crc,state_crc,input_crc,diagnostic_source,header_crc`.
Magic SLC2, versione 2; risposta SLR2, versione 2, `<12I` e 432 float32,
come struttura SDR1. Nessuna compatibilità implicita col decoder precedente.

Per configurazioni lossless `radius_bits` identifica il payload: 0 raw, 1 zlib,
2 Rice; `state_crc` copre i 4608 byte INT8. Per D+DZ è il raggio float32 come
SDZ1, e il CRC copre lo stato float32. Raw diagnostico: campi bits/level/radius
nulli e CRC INT8. Il server dequantizza soltanto i punteggi finali, non gli INT8
lossless destinati al suffisso. Payload massimo 8192 byte; Rice ricostruisce
esattamente 4608 valori. Parametri illegali, overflow, dati aggiunti, padding
non nullo, riferimenti mancanti e sequenze errate vengono rifiutati.

## Hardware

Avviare il server in una nuova directory, poi il runner con uso esclusivo USB:

```sh
.venv/bin/python -u experiments/esp32_lossless_codec_benchmark/server.py --output experiments/esp32_lossless_codec_benchmark/results/NUOVO-RUN/server
experiments/esp32_lossless_codec_benchmark/results/build-tools/bin/python experiments/esp32_lossless_codec_benchmark/run_hardware.py --port /dev/ttyACM0 --run experiments/esp32_lossless_codec_benchmark/results/NUOVO-RUN
.venv/bin/python experiments/esp32_lossless_codec_benchmark/analyze.py --run experiments/esp32_lossless_codec_benchmark/results/NUOVO-RUN
```

Sei giri video, ordine alternato: 5256 richieste; nei primi due giri anche
30 frame camera per sei configurazioni, 360 richieste e 360 diagnostiche.
Totale completo 5616 richieste misurate. `--video-only` esclude la camera;
`--bandwidth-only` esegue sei giri video dei quattro metodi lossless (3504).
`--camera-only` è solo diagnostica raw, non una campagna confrontabile.

Il runner salva/verifica tutti gli 8 MB prima del flash, ripristina in finally
e verifica prima dell'avvio. Non scollegare durante una prova. Backup, firmware,
credenziali e pacchetti rimangono ignorati. `--seed-backup` riusa solo un'immagine
verificata, aggiornando i primi 64 KiB e verificando comunque tutti gli 8 MB.

Per banda limitata avviare `proxy.py --kbps 128` (poi 512), porta 8787,
upstream 8786. Impostare SERVER_URL del firmware sulla porta del proxy,
ricompilare, eseguire `verify_build.py` e usare `--bandwidth-only`. Il proxy scandisce blocchi di upload
a tempo e registra il rate effettivo; risposta non limitata. È una limitazione
applicativa, non una simulazione Wi-Fi, di contesa o di perdita.

## Criterio di conclusione

Un candidato deve preservare ogni byte e ogni uscita. Per dichiarare vantaggio
operativo: ciclo mediano almeno -5% e p95 non oltre +5% rispetto al raw in
ciascuna delle tre coppie video. I vantaggi solo a banda limitata sono condizionati.
Camera e memoria cumulativa sono controlli aggiuntivi, non confronti a scena
identica o picchi di applicazioni separate. Byte HTTP escludono TCP/IP e radio.
La preparazione e i tempi PC non sostituiscono le misure sulla scheda.

Su Linux l'utente deve avere accesso in lettura/scrittura alla porta seriale.
Il runner verifica esclusività, ma non modifica permessi del sistema.
La suite storica D+DZ completa richiede inoltre i pacchetti hardware grezzi
del 29 ottobre (locali/ignorati), assenti in questo checkout: non va dichiarata
interamente superata quando quei prerequisiti mancano. Il nuovo esperimento
verifica separatamente C++/Python, miniz effettivo e ricostruzioni sui dati PC.

## Verifica del costo del decoder sul server

Il primo giro fisico ha evidenziato un costo rilevante nel decoder Rice Python.
`server_native.py` usa lo stesso protocollo/server con un decoder Rice C++ nel
percorso misurato. `analyze.py` mantiene il decoder Python indipendente per
verificare ogni pacchetto salvato, inclusi CRC, riferimenti e uscite rispetto al
raw della stessa campagna. I backend vengono riportati separatamente.

`campaign.py` avvia server e proxy dedicati, esegue il runner con ripristino,
chiude i processi e produce audit e grafico. Il proxy può ascoltare sulla stessa
porta 8786 del firmware spostando il backend sulla 8788: non occorre cambiare
URL o firmware per confrontare 128 e 512 kbit/s. La limitazione copre il corpo
applicativo della richiesta, non gli header HTTP o la risposta.

Il confronto nativo ordinario usa soltanto i quattro codec lossless, sei giri
video (3504 richieste); i controlli camera e D+DZ rimangono nella campagna
completa iniziale. I file `backend-proof.json` e `proxy.jsonl` registrano sorgenti
del backend e rate effettivo, verificati nell'audit. L'opzione seriale `b`
seleziona i quattro metodi lossless; il dispositivo non applica alcuna limitazione
di banda e la sua etichetta storica `bandwidth_only` indica solo questo sottoinsieme.

Esempio di campagna nativa ordinaria (directory nuove):

```sh
.venv/bin/python experiments/esp32_lossless_codec_benchmark/campaign.py --run experiments/esp32_lossless_codec_benchmark/results/NUOVO-NATIVE --backend native --lossless-video-only --publish experiments/esp32_lossless_codec_benchmark/NUOVO-REPORT
```

Per i due regimi limitati usare `--rate 128` o `--rate 512` al posto di
`--lossless-video-only`. `--seed-backup` può indicare un backup integrale già
verificato; il runner ne verifica comunque l'identità con la scheda corrente.
Ogni campagna ripristina l'immagine originale prima di avviare la successiva.

## Integrità dei log seriali

La campagna a 128 kbit/s contiene una riga USB con prefisso identificativo
troncato. Tutti i tempi e i campi CRC della riga sono integri; sul server sono
presenti tutti i 3504 pacchetti. `serial-recovery.json` identifica il frammento
tramite hash e riga. `serial_recovery.py` ricostruisce solo il prefisso del primo
campione usando header originale e contesto sequenziale adiacente; verifica
CRC, dimensioni e tempi server contro la risposta. Nessun tempo viene stimato.
Il log grezzo resta invariato; report e riepilogo dichiarano il recupero.
Se manca un tempo o una verifica fallisce, il recupero viene rifiutato.
Quattro test specifici coprono recupero, log modificato, tempi mancanti e
pacchetto non corrispondente; la suite complessiva comprende 18 test.

Lo snapshot finale dei sorgenti è in [source-sha256.json](source-sha256.json);
i digest storici dei file effettivamente usati nelle misure rimangono nelle
verifiche delle singole campagne.

## Soglia: analisi offline del 1 novembre 2026

[Stima separata](offline_threshold_2026-11-01/report.md), senza nuove misure hardware:
circa 0,70 Mbit/s per il solo guadagno mediano del 5%, sensibilità 0,60–0,85.
Fit su soli due rate; non è una soglia verificata e non predice il p95.
Semplice pareggio stimato circa 1,2 Mbit/s, molto meno identificato.
Il modello ideale CPU+byte darebbe invece circa 4,1 Mbit/s: questa discrepanza
impedisce di trattare l'estrapolazione come un risultato hardware.
Riproduzione: `estimate_threshold.py --output NUOVA-DIRECTORY` con la venv del
progetto, poi `plot_threshold.py --input NUOVA-DIRECTORY` con build-tools.
