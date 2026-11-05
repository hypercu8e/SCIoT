# Parallelismo SCIoT INT8: risultati preliminari

**Campagna incompleta e confronto prestazionale non conclusivo.** Interrotta dopo aver rilevato alimentazione a batteria (17%), preferenza energetica `power` e forti variazioni dei tempi. Le misure vanno ripetute con alimentazione e profilo stabili. I conteggi restano verifiche funzionali valide.

Stesso prefisso/suffisso congelato e split `block_2_add`; interpreti indipendenti, un processo HTTP. Client simulati su loopback nello stesso PC. I tempi non includono camera, prefisso ESP32 o Wi-Fi.

I conteggi e le uscite HTTP riuscite sono verificati byte per byte. Le percentuali di latenza riportate sono mediane dei p95 per client e ripetizione, non percentili aggregati.

## Solo motore

|Worker|Thread/inferenza|Inferenze/s, mediana|Core CPU medi, mediana|Ripetizioni|
|---:|---:|---:|---:|---:|
|1|1|5666.5|1.00|1|
|1|2|6748.8|2.99|1|
|1|4|8391.2|6.97|1|
|1|8|5637.9|14.70|1|
|2|1|10499.8|2.00|1|
|2|2|12265.2|5.89|1|
|2|4|9851.0|13.95|1|
|4|1|16894.8|3.85|2|
|4|2|11786.1|10.96|2|
|8|1|15268.3|3.64|2|

## HTTP

|Worker|Thread|Client|Ripetizioni|Richieste/s, mediana [min–max]|p95 client, mediana ms|Rifiuti|Errori|
|---:|---:|---:|---:|---:|---:|---:|---:|
|1|1|1|1|485.1 [485.1–485.1]|2.72|0|0|
|1|2|1|1|1041.3 [1041.3–1041.3]|1.37|0|0|
|1|4|1|1|1171.3 [1171.3–1171.3]|1.05|0|0|
|1|8|1|1|979.9 [979.9–979.9]|1.63|0|0|
|2|1|1|1|538.5 [538.5–538.5]|2.64|0|0|
|2|2|1|1|921.5 [921.5–921.5]|1.63|0|0|
|2|4|1|1|1114.1 [1114.1–1114.1]|1.02|0|0|
|4|1|1|1|465.1 [465.1–465.1]|2.67|0|0|
|4|2|1|2|855.4 [809.1–901.7]|1.55|0|0|
|8|1|1|2|410.3 [292.1–528.5]|3.35|0|0|
|1|1|2|1|1703.6 [1703.6–1703.6]|1.68|0|0|
|1|2|2|1|1676.1 [1676.1–1676.1]|1.69|0|0|
|1|4|2|1|1711.2 [1711.2–1711.2]|1.41|0|0|
|1|8|2|1|953.5 [953.5–953.5]|4.44|0|0|
|2|1|2|1|1551.3 [1551.3–1551.3]|1.76|0|0|
|2|2|2|1|1590.5 [1590.5–1590.5]|1.68|0|0|
|2|4|2|1|1491.6 [1491.6–1491.6]|1.59|0|0|
|4|1|2|2|953.8 [452.8–1454.7]|3.70|0|0|
|4|2|2|2|1343.4 [1213.6–1473.3]|1.99|0|0|
|8|1|2|2|1098.0 [782.7–1413.3]|3.54|0|0|
|1|1|8|1|1875.5 [1875.5–1875.5]|5.76|0|0|
|1|2|8|1|1875.8 [1875.8–1875.8]|5.77|0|0|
|1|4|8|1|1803.9 [1803.9–1803.9]|5.78|0|0|
|1|8|8|1|1010.7 [1010.7–1010.7]|12.78|0|0|
|2|1|8|1|1891.1 [1891.1–1891.1]|5.62|0|0|
|2|2|8|1|1868.1 [1868.1–1868.1]|5.58|0|0|
|2|4|8|1|1614.1 [1614.1–1614.1]|6.33|0|0|
|4|1|8|2|1165.3 [573.2–1757.5]|11.77|0|0|
|4|2|8|2|1588.5 [1408.9–1768.1]|6.27|0|0|
|8|1|8|2|1700.1 [1699.3–1700.9]|6.15|0|0|
|1|1|32|1|1751.5 [1751.5–1751.5]|7.38|2471|0|
|1|2|32|1|1764.0 [1764.0–1764.0]|7.35|2465|0|
|1|4|32|1|1739.1 [1739.1–1739.1]|7.24|2459|0|
|1|8|32|1|924.0 [924.0–924.0]|17.88|2577|0|
|2|1|32|1|1709.3 [1709.3–1709.3]|11.56|1888|0|
|2|2|32|1|1850.6 [1850.6–1850.6]|9.93|1913|0|
|2|4|32|1|1474.5 [1474.5–1474.5]|12.19|1966|0|
|4|1|32|2|1202.7 [592.7–1812.6]|35.31|1433|0|
|4|2|32|2|1613.8 [1382.5–1845.0]|18.38|1579|0|
|8|1|32|2|1779.6 [1770.5–1788.8]|18.88|612|0|

## Carico programmato

|Regime|Worker|Thread|Richieste/s|p95 client ms|Rifiuti|Slot saltati|
|---|---:|---:|---:|---:|---:|---:|

## Interpretazione e limiti

Confrontare il motore isolato con HTTP: la capacità del servizio può essere limitata da ricezione, serializzazione, log sincroni e generatore, prima che dai kernel. Il numero di thread richiesto non dimostra l’utilizzo effettivo di altrettanti core. Il valore CPU è tempo CPU/tempo reale, comprende tutti i thread del processo. Le misure HTTP di CPU escludono il riscaldamento; quelle del solo motore e del generatore includono il riscaldamento.

Il generatore mantiene una richiesta pendente per client, registra gli slot programmati saltati e applica il backoff originale sui 429: non è un generatore open-loop illimitato. La scelta della configurazione migliore usa la mediana del throughput con il massimo numero di client della matrice, ed è esplorativa. Altre applicazioni sul PC possono influenzare i tempi. RSS include runtime TensorFlow e interpreti: non è la sola memoria dei tensori.

Richieste HTTP completate e verificate: **2049981**; errori: **0**.

Audit: il generatore è stato corretto dopo 35 prove HTTP complete per registrare i client prima del riscaldamento; una prova interrotta su 429 è conservata e ripetuta. Server e percorso di inferenza invariati. Vedere README e `results/registration-audit.json`.

Dati completi: `results/manifest.json`, `results/results.jsonl` e directory per prova. Il manifest conserva hardware, dipendenze, hash dei sorgenti e manifest del modello.
