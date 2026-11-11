# Confronto lungo originale / sola LUT — 10 novembre 2026

**Confronti individuali e simultanei superati; ora di stabilità fallita.**
La LUT riduce la mediana descrittiva del ciclo individuale del 27,2%, ma A
riceve HTTP 408 dopo circa 34 minuti della fase continua. Nessuna promozione
al client operativo; la causa del timeout non è isolata.

**Decisione finale concordata:** chiudere la valutazione della LUT come
ottimizzazione utile e numericamente equivalente. Il vantaggio nella
conversione locale vale indipendentemente dal trasporto; il guadagno
percentuale sul ciclo completo dipende dalle condizioni di rete. Il timeout
è ritenuto probabilmente legato al particolare percorso Pixel/ADB, senza
attribuzione causale dimostrata. Nessuna ulteriore diagnostica o ripetizione
dell'ora richiesta per chiudere questo filone; i risultati della prova
interrotta restano invariati.

## Protocollo

ESP32-S3-EYE, INT8 congelato, ESP-NN, split `block_2_add`, camera RGB565 96×96, un framebuffer trattenuto fino al termine HTTP. Rete Pixel 9a hotspot 2,4 GHz + USB/ADB reverse; suffisso PC con un worker e un thread. HTTP e archiviazione sono inclusi nei tempi. Timeout invariati.

Solo originale e LUT: tre ripetizioni da 1.000 frame camera misurati ciascuna su A, ordini 0-1, 1-0, 0-1. Ogni comando include 60 input incorporati e 20 frame camera di warmup esclusi dalle statistiche camera. Successivamente 1.000 frame per variante per scheda insieme; ora della LUT solo dopo conferma su entrambe. Grayscale e rilascio anticipato esclusi.

Criteri fissati prima delle misure: ciclo p50 almeno -5%; p95 del ciclo ed età al risultato non oltre +5%; nessun errore, frame ripetuto o perdita rilevata dallo screening memoria. La selezione individuale usa mediane delle statistiche delle tre ripetizioni; la conferma simultanea applica i margini separatamente ad A e B. Memoria: mediane iniziali/finali dei campioni heap, tolleranza 4 KiB; non prova assenza di leak né misura completa del picco RAM.

## Individuale: tutte le ripetizioni

| Ripetizione | Variante | Ciclo p50 ms | Ciclo p95 ms | Risultati/s | Età p95 ms | Max intervallo ms |
|---|---|---:|---:|---:|---:|---:|
| 1 | Originale | 336,232 | 515,677 | 2,655 | 502,571 | 3106,301 |
| 1 | LUT | 244,757 | 307,675 | 3,875 | 270,108 | 960,082 |
| 2 | Originale | 255,556 | 315,839 | 3,673 | 291,881 | 1735,296 |
| 2 | LUT | 371,885 | 545,387 | 2,489 | 513,693 | 3020,964 |
| 3 | Originale | 375,927 | 512,165 | 2,449 | 489,908 | 5498,303 |
| 3 | LUT | 229,293 | 280,062 | 4,209 | 253,555 | 1116,272 |

Mediana dei p50: **336,232 → 244,757 ms**, variazione **-27,206%**. LUT selezionata individualmente. La variabilità tra ripetizioni resta visibile nella tabella; non sostituire i confronti con il solo risultato migliore.

## Due schede simultanee

| Scheda | Variante | Ciclo p50 ms | Ciclo p95 ms | Risultati/s | Età p95 ms | Max intervallo ms |
|---|---|---:|---:|---:|---:|---:|
| A | Originale | 377,208 | 564,371 | 2,426 | 547,249 | 3049,016 |
| A | LUT | 204,772 | 252,591 | 4,600 | 229,072 | 754,596 |
| B | Originale | 265,600 | 333,130 | 3,528 | 306,485 | 1350,576 |
| B | LUT | 198,180 | 241,929 | 4,668 | 221,850 | 509,912 |

Entrambe le schede superano i margini predefiniti di ciclo, p95, freschezza e
screening memoria nelle serie simultanee da 1.000 frame.

## Ora continua interrotta: dati parziali

La fase è fermata dopo 2.046,289 s (circa 34,1 minuti, inclusi controlli e
warmup). Non è una prova di un'ora completata. Statistiche dei soli risultati
ricevuti prima dello stop:

| Scheda | Frame camera | Ciclo p50 ms | Ciclo p95 ms | Risultati/s | Età p95 ms | Max intervallo ms |
|---|---:|---:|---:|---:|---:|---:|
| A | 5.349 | 340,023 | 537,399 | 2,645 | 513,497 | 5.523,145 |
| B | 7.225 | 255,252 | 354,632 | 3,562 | 327,775 | 3.711,529 |

A riceve HTTP 408: il server registra `body_timeout` dopo 3.000,848 ms,
prima dell'ammissione all'inferenza. Non è attesa nella coda del suffisso.
Un secondo 408 compare durante l'arresto, prima del reset del dispositivo.
B non registra errori nel tratto osservato.

Le due disconnessioni Wi-Fi registrate da A (reason 203 e 205) appartengono
all'avvio, circa 47 minuti prima dell'inizio della fase continua. Non coincidono
con il timeout e non ne dimostrano la causa. Non attribuire il guasto alla LUT,
al Pixel, al server o all'alimentazione senza una prova controllata.

Durante il tratto parziale il trasporto peggiora rispetto alla precedente
serie simultanea. Pubblicare anche questi valori, senza presentare il -27,2%
individuale come un vantaggio garantito per qualsiasi durata o rete.

### Richieste durante il ripristino e correzione del runner

Nel runner usato, i log seriali venivano chiusi prima dei ripristini sequenziali:
B continuava a inviare mentre A veniva ripristinata. Risultano 295 risposte
HTTP 200 successive al segnale di stop: una ancora registrata dal dispositivo,
294 senza campione seriale corrispondente. Sono escluse dalle statistiche di
fase; il replay verifica comunque tutti i loro punteggi.

Il primo audit chiamava impropriamente tutti i 534 record non correlati
"warmup". Audit corretto: **240 warmup effettivi e 294 altri record**.
Il file originale resta conservato nel run; il materiale pubblicabile usa
`archive-audit-corrected.json`.

Dopo la prova il runner è stato corretto: reset di entrambe le schede prima
di chiudere i log e ripristinare; eventuali errori di reset/chiusura non saltano
i tentativi di ripristino. La correzione è compilata staticamente, ma il nuovo
percorso di arresto non è stato collaudato con un'altra campagna hardware.

La proposta di diagnostica controllata del percorso HTTP e ripetizione dell'ora
è stata accantonata nella decisione finale sopra. Nessun timeout aumentato.

La cadenza riportata usa gli intervalli fra risultati dentro la serie, includendo il lavoro tra frame ma escludendo avvio, validazione e warmup. Il timestamp camera è quello del driver, non una misura precisa dell’esposizione.

## Correttezza, traffico e stato finale

- Richieste archiviate: **23829**; punteggi del suffisso identici al replay indipendente.
- Campioni dispositivo correlati: 23.295; 240 richieste warmup e 294 altri record senza campione corrispondente. Un campione correlato è successivo allo stop ed escluso dalle statistiche di fase.
- Stati terminali server: **23.829 HTTP 200 e 2 HTTP 408**. Il primo 408 interrompe la fase; il secondo è successivo allo stop.
- Controllo esaustivo su 65.536 colori e input/attivazioni di 100 frame reali su A; stesso firmware per entrambe. Attivazioni degli input incorporati identiche tramite SHA-256 fra varianti, schede e fasi.
- Traffico per inferenza invariato: 4.640 byte corpo richiesta (4.608 attivazioni) e 1.760 byte corpo risposta; esclusi header HTTP/TCP/IP e registrazioni.
- LUT: 64 KiB in PSRAM. Il progetto sperimentale riserva la stessa tabella anche nel riferimento per confrontare i percorsi per frame; il costo aggiuntivo rispetto al client operativo va comunque considerato.
- Equivalenza numerica non equivale a una nuova misura di accuratezza su scene annotate. Energia e picco RAM completo non misurati.
- Flash originali verificate e boot confermati di entrambe le schede. Server sperimentale terminato e inoltro ADB temporaneo rimosso.
- Sette test dell’analizzatore e build firmware superati. Nessun commit o push.

## Artefatti e riproduzione

[Audit completo](lut-hold-full-audit.json) · [selezione](lut-hold-full-selection.json) · [conferma A/B](lut-hold-full-confirmation.json) · [screening precedente](report.md) · [procedura](../README.md#confronto-lungo-originale--sola-lut).

Run locale ignorato: `experiments/esp32_input_camera_benchmark/results/2026-11-10-lut-hold-full-01/`. Contiene backup, firmware, snapshot/hash dei sorgenti, log seriali/server, archivio binario e audit. I file di credenziali e i binari non fanno parte del materiale pubblicabile.

Comando campagna, dopo la preparazione dei backup verificati:

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_input_camera_benchmark/campaign.py --run experiments/esp32_input_camera_benchmark/results/NUOVO_RUN --lut-hold-only
```
