# Screening HTTP delle ottimizzazioni — 10 novembre 2026

Le prove brevi non riproducono gli HTTP 408 del giorno precedente. La sola
conversione tramite LUT, con framebuffer trattenuto, è promettente nel percorso
completo. Il rilascio anticipato richiede cautela: un ciclo mediano inferiore
non implica risultati più frequenti o frame più recenti. Nessuna variante è
stata selezionata o promossa al client operativo.

## Configurazione e protocollo

Due ESP32-S3-EYE, stesso modello INT8 congelato, ESP-NN e split `block_2_add`.
Pixel 9a, hotspot 2,4 GHz e `adb reverse tcp:8000 tcp:8000`; suffisso sul PC,
un worker e un thread. SSID e credenziali restano nel file locale ignorato.
Nessuna modifica ai timeout HTTP o al protocollo.

1. Client precedente: due prove individuali per scheda, prima A/B e poi B/A.
   Ogni prova comprende 60 input incorporati e 20 frame camera: 320 richieste.
2. Progetto sperimentale: controllo dei 65.536 colori RGB565 e confronto
   integrale di input/attivazioni su 100 frame reali.
3. Screening solo su A: quattro varianti RGB565, tre ripetizioni con ordini
   0-1-2-3, 3-2-1-0 e 1-0-3-2. Ogni serie comprende 60 input incorporati,
   20 frame camera di warmup e 20 frame camera misurati. In totale 1.200
   richieste, di cui 240 warmup e 240 frame camera misurati.

La nuova opzione `campaign.py --http-smoke-only` conserva il risultato con
scope `short_http_smoke_20_frames`, senza selezione, grayscale o campagna
simultanea. [Procedura](../README.md#screening-http-breve).

## Risultati esplorativi HTTP

Mediane delle statistiche delle tre ripetizioni, 20 frame misurati ciascuna.
La cadenza usa gli intervalli fra risultati all'interno della serie; non include
avvio, validazione, input incorporati o warmup. Il timestamp del driver camera
non è una misura precisa dell'esposizione.

| Variante | Ciclo p50 ms | Ciclo p95 ms | Risultati/s | Età al risultato p95 ms | Massimo intervallo fra risultati ms |
|---|---:|---:|---:|---:|---:|
| Originale, buffer trattenuto | 438,614 | 593,603 | 2,177 | 572,467 | 1.029,179 |
| LUT, buffer trattenuto | 322,488 | 509,481 | 2,745 | 487,465 | 875,420 |
| Originale, rilascio anticipato | 308,644 | 510,076 | 3,195 | 817,714 | 1.694,124 |
| LUT, rilascio anticipato | 291,562 | 576,034 | 2,427 | 1.010,664 | 5.004,318 |

La sola LUT riduce il ciclo mediano descrittivo di circa il 26,5% rispetto
al riferimento e mostra frame più recenti. La combinazione con rilascio
anticipato ha il ciclo p50 più basso, ma età p95 maggiore e cadenza inferiore
alla sola LUT. Non applicare il criterio di selezione del confronto completo
a queste serie da 20 frame, insufficienti anche per conclusioni sulle code
di latenza, sulla memoria o sulla stabilità prolungata.

Traffico invariato fra varianti: 4.640 byte di corpo richiesta, inclusi 4.608
byte di attivazione, e 1.760 byte di corpo risposta. Sono esclusi header
HTTP/TCP/IP e registrazioni. L'equivalenza numerica non è una nuova misura
di accuratezza su scene annotate; non sono state misurate energia o picco RAM.

## Diagnostica del riferimento e limiti

Entrambi i giri del vecchio client completano tutti i campioni senza errori.
Nel primo giro B registra però uno scambio HTTP da 5.189,053 ms: la richiesta
correlata impiega 149,902 ms nel servizio server, di cui 149,193 ms per la
ricezione e circa 0,65 ms nel worker. Il ritardo maggiore è quindi esterno
al tempo misurato dal servizio. Questo confronto non separa connessione,
trasmissione, inoltro ADB e ritorno della risposta.

Nei quattro controlli individuali le mediane del ciclo camera sono
323,599/389,357 ms (A/B nel primo giro) e 441,846/438,726 ms (A/B nel secondo).
Non usare questi valori, né quelli dello screening, per attribuire una
differenza rispetto al 9 novembre a una sola causa: il trasporto è variabile.
La causa dei precedenti 408 rimane non isolata; non dichiarare il problema
risolto perché non si è riprodotto in prove brevi.

## Verifiche, dati e ripresa

[Statistiche e riepilogo](summary.json) · [audit riferimento A/B](baseline-01-audit.json)
· [audit riferimento B/A](baseline-02-audit.json) · [replay screening](smoke-audit.json).

Run grezzi locali, ignorati da Git:

- `experiments/multiclient_hardware/results/2026-11-10-http-baseline-01/`
- `experiments/multiclient_hardware/results/2026-11-10-http-baseline-02/`
- `experiments/esp32_input_camera_benchmark/results/2026-11-10-http-smoke-01/`

I run conservano backup, log seriali/server, richieste/risposte, snapshot e hash
dei sorgenti. Il progetto sperimentale conserva anche il firmware usato.
Credenziali e binari restano esclusi dal materiale pubblicabile.

Audit conclusi: tutte le 1.520 risposte hanno punteggi del suffisso identici
al replay indipendente; zero errori dispositivo e tutti gli stati terminali
server HTTP 200. I controlli numerici riportano zero differenze sui 65.536
colori e sui 100 frame di confronto.

Entrambi i run del riferimento terminano con ripristino integrale verificato
e boot originale confermato di A e B. Dopo lo screening, A è ripristinata e
verificata; B non è stata modificata e il suo boot originale è confermato da
`B/unchanged-boot.log`. Per questo l'audit dello screening riporta `restored`
falso per B: non è un ripristino fallito. Lo stato finale è registrato anche
in `summary.json`. Server spento, seriali libere e inoltro ADB rimosso.

Cinque test dell'analizzatore, compilazione Python e build dei due firmware
superati. Nessun commit o push eseguito.

Passo successivo: confronto HTTP completo da 1.000 frame per variante e
ripetizione, con controlli di freschezza e jitter; solo dopo eventuale selezione,
conferma su due schede e un'ora. Conservare questi risultati come screening,
senza aggregarli alle prove locali senza HTTP del 9 novembre.
