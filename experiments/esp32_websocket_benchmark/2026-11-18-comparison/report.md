# Confronto sulla ESP32 B con gestione XCLK | 18 novembre 2026

**Nove avvii completati, 18.900 richieste riuscite su 18.900 e 9.000 frame
reali.** HTTP persistente, WebSocket e HTTP con chiusura hanno completato
6.300 richieste ciascuno. I log del server confermano ogni risposta.
Zero timeout e zero disconnessioni Wi-Fi durante la misura.

La stessa ESP32 B, sulla porta USB 1-1, ha eseguito i nove avvii con un
unico binario. Il clock della camera veniva acceso per acquisire il frame
e spento durante inferenza e invio. I tre giri hanno ruotato l'ordine
**WS → persistente → chiusura**, **persistente → chiusura → WS**,
**chiusura → WS → persistente**. Il server è rimasto sullo stesso laptop,
profilo energetico balanced, con alimentazione esterna osservata
durante la campagna. RSSI iniziale da -75 a -52 dBm, canale 6.

## Risultati per trasporto

Le latenze sono in millisecondi. Per ogni colonna si calcola il percentile
in ciascun avvio e si riporta la mediana dei tre valori. Le misure di memoria
sono il minimo osservato fra tutti e tre gli avvii.

| Trasporto | Ciclo camera p50 / p95 | Richiesta/risposta camera p50 / p95 | Richiesta/risposta input fissi p50 / p95 | RAM interna libera minima | Margine minimo stack applicativo |
| --- | ---: | ---: | ---: | ---: | ---: |
| HTTP persistente | 709,8 / 792,6 | 40,1 / 122,5 | 19,0 / 67,3 | 48723 B | 12952 B |
| WebSocket | 711,3 / 798,2 | 41,5 / 128,1 | 19,1 / 90,6 | 36535 B | 12952 B |
| HTTP con chiusura | 754,3 / 820,5 | 89,9 / 150,5 | 31,1 / 156,9 | 50035 B | 12952 B |

## Misure per avvio

| Avvio | Trasporto | RSSI (dBm) | Ciclo camera p50 / p95 (ms) | RAM interna libera minima |
| ---: | --- | ---: | ---: | ---: |
| 1 | WebSocket | -55 | 710,4 / 795,1 | 36535 B |
| 2 | HTTP persistente | -60 | 710,9 / 796,2 | 48723 B |
| 3 | HTTP con chiusura | -59 | 754,3 / 821,5 | 50035 B |
| 4 | HTTP persistente | -52 | 709,8 / 792,6 | 50183 B |
| 5 | HTTP con chiusura | -54 | 744,5 / 819,7 | 50231 B |
| 6 | WebSocket | -75 | 712,3 / 804,2 | 36759 B |
| 7 | HTTP con chiusura | -59 | 803,5 / 820,5 | 50779 B |
| 8 | WebSocket | -60 | 711,3 / 798,2 | 37155 B |
| 9 | HTTP persistente | -63 | 698,6 / 785,2 | 50195 B |

## Esito

La differenza WebSocket rispetto a HTTP persistente nel ciclo camera,
p50 / p95, è giro 1 -0,07% / -0,14%, giro 2 0,35% / 1,46%, giro 3 1,81% / 1,65%. Il divario in valore assoluto arriva al 1,81%.
Il criterio di latenza del benchmark (WebSocket entro +5% a p50 e p95
in ogni giro) è soddisfatto.

Per questa configurazione la scelta è **HTTP persistente**. I due
trasporti hanno un ciclo pressoché uguale e HTTP persistente conserva
12188 byte in più di RAM interna al minimo. HTTP con chiusura ha il ciclo
mediano più lento in tutti e tre i giri. La fase che comprende riavvio del
sensore, acquisizione e commutazioni di XCLK occupa circa 601
ms per frame ed è la parte dominante del ciclo.

Ogni avvio ha superato 35 verifiche iniziali del prefisso, 10 controlli
numerici intermedi, verifica dei timestamp e integrità del framebuffer,
heap e sentinelle. Le risposte ai 1.100 input deterministici per avvio
corrispondono byte per byte al riferimento del firmware, con CRC
coerenti anche fra gli avvii. Lo stack misurato è quello del task
applicativo. Restano fuori da questa campagna la validazione visiva,
le prove di recupero da guasti e la misura del traffico sul filo.

**Flash originale ripristinata e verificata su tutti gli 8 MiB.** Boot
originale confermato. B scollegabile. Il benchmark usa il firmware
sperimentale e il server di prova è stato chiuso.

[Misure e verifiche in JSON](summary.json). Dati grezzi, snapshot e
backup nelle directory ignorate `results/LAPTOP_B_COMPARE_GATED_01` e
`results/LAPTOP_SERVER_COMPARE_GATED_01`.
