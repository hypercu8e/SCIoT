# Verifica della gestione XCLK sulla ESP32 B — 17 novembre 2026

**HTTP persistente e WebSocket superano entrambi la prova con camera reale.**
Ogni avvio completa 1.100 richieste con input di riferimento e 1.000 frame
camera. I log del server confermano 4.200 risposte con esito 200, senza timeout
o disconnessioni Wi-Fi durante la misura. Nel precedente controllo HTTP sulla
stessa porta e con il secondo cavo la richiesta 54 si era chiusa con 408.
[Diagnostica precedente](../2026-11-17-laptop/report.md).

Stessa B, porta USB `1-1`, secondo cavo, server sul laptop e stesso binario.
Due avvii indipendenti, in ordine HTTP persistente e WebSocket. RSSI iniziale
−56 dBm e canale 6 in entrambi. Profilo del laptop `balanced`, batteria in
scarica osservata durante WebSocket.

| Misura | HTTP persistente | WebSocket |
| --- | ---: | ---: |
| Richieste riuscite | 2.100/2.100 | 2.100/2.100 |
| Frame RGB565 96×96 verificati | 1.000 | 1.000 |
| Latenza richiesta/risposta, frame camera p50 / p95 | 41,853 / 138,820 ms | 32,886 / 112,236 ms |
| Latenza richiesta/risposta, input deterministici p50 / p95 | 19,770 / 37,193 ms | 18,933 / 56,536 ms |
| Ciclo completo camera p50 / p95 | 711,065 / 808,642 ms | 702,082 / 780,933 ms |
| RAM interna libera, minimo | 50.227 B | 35.487 B |

Il firmware tiene il singolo framebuffer in possesso mentre spegne XCLK per
inferenza e invio. A ogni ripresa attende 200 ms, restituisce il buffer e scarta
il primo frame completo. Per ogni avvio sono verificati 2.001 cambi di routing
su GPIO15 e 1.000 frame con timestamp successivi alla riaccensione e hash
distinti. I controlli di integrità del buffer prima e dopo l'invio, heap,
sentinelle e 10 confronti numerici intermedi sono passati. I 35 input del
controllo iniziale del prefisso sono risultati esatti in entrambi gli avvii.
Le 1.100 risposte deterministiche hanno superato il confronto integrale
con i valori attesi. Per i frame camera il client verifica identità,
formato e finitezza dei punteggi. I controlli sul framebuffer coprono
freschezza e integrità. La qualità ottica e l'esposizione vanno verificate a parte.

La ripresa della camera e l'attesa dopo le commutazioni occupano circa 601 ms
per frame. Le latenze osservate e il margine di RAM più stretto di WebSocket
motivano il confronto per round. Per scegliere il trasporto servono i nove
avvii con ordine alternato, tutti con `--gate-camera`, e i controlli di
riconnessione e traffico previsti dal benchmark.

Il runner ha ripristinato e verificato tutti gli 8 MiB della flash originale
dopo entrambi gli avvii. Boot originale verificato, server e seriale chiusi.
La correzione è nel firmware sperimentale. I log grezzi, i binari e i backup
restano nelle directory ignorate `results/LAPTOP_B_HTTP_GATED_01`,
`results/LAPTOP_B_WS_GATED_01` e `results/LAPTOP_SERVER_GATED_01`.
I conteggi e gli hash verificati sono in [summary.json](summary.json).
