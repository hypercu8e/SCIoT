# Dove va il tempo del ciclo camera, e due leve

**12 novembre 2026, primo tentativo interrotto** (`results/2026-11-12-board-B-interrupted`,
scheda B su una porta USB del portatile): fasi 1, 3 e 4 chiuse all'11° errore
HTTP, la 2 completa. Con la camera spenta (input incorporati) la richiesta
dura 20–33 ms in tutte le fasi; appena la camera è attiva sale a 150 ms nella
fase buona e a 1,7–5,6 s con 408 nelle altre. È lo stesso guasto del 5
novembre, che seguiva cavo e porta USB (alimentazione). Interrotto alla fase 5,
flash ripristinata e avvio confermato. Dati già utili: la tabella porta
conversione e preparazione dell'ingresso da **46,3 a 0,8 ms** e coincide su
tutti i pixel di controllo; la connessione riusata porta l'apertura della
connessione da 12–13 a 2 ms (input incorporati). Da ripetere con
un'alimentazione adeguata.

Domanda: il ciclo camera del client dura circa 280 ms in condizioni buone.
Due interventi semplici lo accorciano senza cambiare i byte inviati?

## Da dove si parte (run del 12 novembre, prova di capienza)

Ciclo camera p50 in condizioni di rete buone (fase 1 N,
`esp32_client_fit_benchmark/results/2026-11-12-board-B-02`):

| Passo | p50 |
|---|---:|
| Attesa e acquisizione del frame (`esp_camera_fb_get`) | 75 ms |
| RGB565 → float in scala di grigi | 8,5 ms |
| float → int8 (ingresso del modello) | **38,6 ms** |
| Inferenza del prefisso (arena in PSRAM) | 95 ms |
| Impacchettamento | 1,1 ms |
| Richiesta e risposta HTTP (4.640 B su, 1.760 B giù) | 65 ms (p95 213) |
| **Ciclo** | **284 ms** |

Il server lavora circa 1 ms. Con rete peggiore la richiesta sale a 360 ms
p50 (fase 3 della prova `psramnet`).

## Le due leve

1. **Tabella per l'ingresso** (bit 0). Oggi ogni pixel passa per un calcolo
   in `double`, che l'ESP32-S3 esegue in software: 9.216 divisioni da circa
   4 µs. L'uscita int8 dipende solo dal valore RGB565 del pixel, quindi
   all'avvio si costruisce una tabella di 65.536 byte (in PSRAM) con le stesse
   funzioni compilate del percorso originale. Per ogni frame resta una
   lettura in tabella per pixel. Stessi byte per costruzione; all'avvio la
   tabella viene confrontata con il percorso originale su tutti i 65.536
   valori. La tabella si costruisce in tutte le varianti (stessa memoria),
   ma si usa solo dove il bit è attivo.
2. **Connessione HTTP riusata** (bit 1). Oggi il client apre una connessione
   TCP nuova per ogni frame (`Connection: close`). Con il bit attivo usa un
   solo handle `esp_http_client` per tutto il run (HTTP/1.1 keep-alive, uvicorn
   lo supporta). Se la connessione risulta chiusa all'apertura, riconnette una
   volta e lo conta (`reconnects`). Dopo un errore la connessione si chiude e
   si riapre.

Il firmware è una copia del client (`src/client/esp32-s3-eye-multiclient`),
con stessa configurazione e stessi componenti. Unica differenza nel
percorso originale: le due conversioni sono diventate funzioni non inline,
condivise con la costruzione della tabella. La variante si sceglie da
seriale all'avvio (`0`–`3`). Il campione registra anche i tempi della
richiesta: apertura e invio intestazioni, invio del corpo, attesa delle
intestazioni di risposta, lettura del corpo.

## Prova

Scheda B, rete `FASTWEB`, server HTTP v2 sul PC (`audit_server.py`), un solo
flash. Otto fasi in ordine ABBA, **0 1 2 3 3 2 1 0**, ciascuna dopo un
riavvio: 60 input incorporati e 500 frame camera. Così la deriva della rete
pesa allo stesso modo su ogni variante. Backup verificato e ripristino in
`finally`. Il runner chiude una fase all'11° errore.

## Criteri, fissati prima della misura

- **Correttezza, obbligatoria:** tabella senza differenze su tutti i 73.728
  pixel di controllo e identica in tutte le fasi. Attivazioni e risposte
  degli input incorporati identiche in tutte le fasi.
- **Funzionamento, per fase:** 60 incorporati; al massimo 10 frame camera
  persi su 500 per errori HTTP transitori (408/410); nessun panic o riavvio.
- **Effetto di una leva:** differenza del ciclo camera p50 rispetto alla
  variante 0 **dello stesso round**. La leva è "più veloce" se risparmia almeno
  **5 ms in entrambi i round**. Riportati: la media dei due round e i passi in
  cui cambia il tempo.
- **Esito:** `faster` / `not_confirmed`. `environment_problem` se una fase non
  funziona, `invalid` se cambiano i byte.

Limiti: una scheda, una rete, 500 frame per fase. Il frame camera arriva al
ritmo del sensore, quindi un risparmio di calcolo può trasformarsi in più
attesa del frame successivo: per questo conta il ciclo osservato, non la
somma dei passi.

## Riproduzione

```sh
C=src/client/esp32-s3-eye-multiclient
mkdir -p experiments/esp32_cycle_benchmark/idf/include
cp -a $C/components $C/managed_components $C/dependencies.lock experiments/esp32_cycle_benchmark/idf/
cp $C/include/network.local.h experiments/esp32_cycle_benchmark/idf/include/   # credenziali locali, ignorate da Git
(cd experiments/esp32_cycle_benchmark && ../../.venv/bin/python -m unittest test_analysis)
T=experiments/esp32_lossless_codec_benchmark/results/build-tools/bin
$T/pio run -d experiments/esp32_cycle_benchmark/idf
$T/python experiments/esp32_cycle_benchmark/run.py --run experiments/esp32_cycle_benchmark/results/NUOVO_RUN --board B --seed BACKUP_VERIFICATO
.venv/bin/python experiments/esp32_cycle_benchmark/analyze.py --run experiments/esp32_cycle_benchmark/results/NUOVO_RUN --output experiments/esp32_cycle_benchmark/results/NUOVO_RUN/audit.json
```

Il firmware compilato e la sua copia nei risultati contengono le credenziali
Wi-Fi: restano nelle cartelle ignorate.
