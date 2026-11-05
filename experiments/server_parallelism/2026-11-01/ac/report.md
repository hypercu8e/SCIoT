# Parallelismo SCIoT INT8: campagna CPU



Stesso prefisso/suffisso congelato e split `block_2_add`; interpreti indipendenti, un processo HTTP. Client simulati su loopback nello stesso PC. I tempi non includono camera, prefisso ESP32 o Wi-Fi.

I conteggi e le uscite HTTP riuscite sono verificati byte per byte. I risultati sono separati per alimentazione e profilo CPU. Le righe `transition` non permettono confronti prestazionali stabili. I valori di latenza riportati sono mediane dei p95 per client e ripetizione, non percentili aggregati.

## Solo motore

|Energia|Worker|Thread/inferenza|Inferenze/s, mediana|CPU logiche equivalenti, mediana|Ripetizioni|
|---|---:|---:|---:|---:|---:|
|ac:[('powersave', 'balance_performance')]|1|1|5946.0|1.00|1|
|battery:[('powersave', 'balance_power')]|1|1|5793.4|1.00|2|
|ac:[('powersave', 'balance_performance')]|1|2|7171.6|2.99|1|
|battery:[('powersave', 'balance_power')]|1|2|6907.6|2.98|2|
|ac:[('powersave', 'balance_performance')]|1|4|7301.2|6.89|1|
|battery:[('powersave', 'balance_power')]|1|4|8517.1|6.98|2|
|ac:[('powersave', 'balance_performance')]|1|8|4708.7|13.62|2|
|battery:[('powersave', 'balance_power')]|1|8|4889.3|13.83|1|
|ac:[('powersave', 'balance_performance')]|2|1|10065.6|1.98|2|
|battery:[('powersave', 'balance_power')]|2|1|10737.8|1.99|1|
|ac:[('powersave', 'balance_performance')]|2|2|12064.9|5.89|2|
|battery:[('powersave', 'balance_power')]|2|2|13135.0|5.96|1|
|ac:[('powersave', 'balance_performance')]|2|4|9708.9|13.62|2|
|battery:[('powersave', 'balance_power')]|2|4|9589.0|13.75|1|
|ac:[('powersave', 'balance_performance')]|4|1|18465.4|3.77|2|
|battery:[('powersave', 'balance_power')]|4|1|18045.8|3.68|1|
|ac:[('powersave', 'balance_performance')]|4|2|13182.3|10.88|2|
|battery:[('powersave', 'balance_power')]|4|2|12949.7|10.82|1|
|ac:[('powersave', 'balance_performance')]|8|1|14758.2|3.63|2|
|battery:[('powersave', 'balance_power')]|8|1|15078.0|3.60|1|

## HTTP

|Energia|Worker|Thread|Client|Ripetizioni|Richieste/s, mediana [min–max]|p95 client, mediana ms|Rifiuti|Errori|
|---|---:|---:|---:|---:|---:|---:|---:|---:|
|ac:[('powersave', 'balance_performance')]|1|1|1|1|1331.9 [1331.9–1331.9]|0.89|0|0|
|battery:[('powersave', 'balance_power')]|1|1|1|2|611.2 [517.2–705.2]|2.50|0|0|
|ac:[('powersave', 'balance_performance')]|1|2|1|1|1283.1 [1283.1–1283.1]|1.04|0|0|
|battery:[('powersave', 'balance_power')]|1|2|1|2|1112.7 [1078.8–1146.6]|1.19|0|0|
|ac:[('powersave', 'balance_performance')]|1|4|1|1|1132.6 [1132.6–1132.6]|1.14|0|0|
|battery:[('powersave', 'balance_power')]|1|4|1|2|1134.4 [1105.8–1163.1]|1.15|0|0|
|ac:[('powersave', 'balance_performance')]|1|8|1|1|978.2 [978.2–978.2]|1.82|0|0|
|battery:[('powersave', 'balance_power')]|1|8|1|2|1055.1 [1033.5–1076.8]|1.08|0|0|
|ac:[('powersave', 'balance_performance')]|2|1|1|2|1211.8 [1201.1–1222.4]|1.12|0|0|
|battery:[('powersave', 'balance_power')]|2|1|1|1|479.5 [479.5–479.5]|2.58|0|0|
|ac:[('powersave', 'balance_performance')]|2|2|1|2|1159.5 [1117.3–1201.6]|1.19|0|0|
|battery:[('powersave', 'balance_power')]|2|2|1|1|992.7 [992.7–992.7]|1.40|0|0|
|ac:[('powersave', 'balance_performance')]|2|4|1|2|1081.5 [1004.1–1158.8]|1.15|0|0|
|battery:[('powersave', 'balance_power')]|2|4|1|1|1037.0 [1037.0–1037.0]|1.20|0|0|
|ac:[('powersave', 'balance_performance')]|4|1|1|2|1079.2 [998.3–1160.1]|1.30|0|0|
|battery:[('powersave', 'balance_power')]|4|1|1|1|486.7 [486.7–486.7]|2.84|0|0|
|ac:[('powersave', 'balance_performance')]|4|2|1|2|1049.5 [972.2–1126.8]|1.28|0|0|
|battery:[('powersave', 'balance_power')]|4|2|1|1|900.8 [900.8–900.8]|1.47|0|0|
|ac:[('powersave', 'balance_performance')]|8|1|1|2|932.7 [917.4–948.0]|1.47|0|0|
|battery:[('powersave', 'balance_power')]|8|1|1|1|492.4 [492.4–492.4]|2.76|0|0|
|ac:[('powersave', 'balance_performance')]|1|1|2|1|1866.6 [1866.6–1866.6]|1.35|0|0|
|battery:[('powersave', 'balance_power')]|1|1|2|2|1629.6 [1548.0–1711.2]|1.78|0|0|
|ac:[('powersave', 'balance_performance')]|1|2|2|1|1716.4 [1716.4–1716.4]|1.64|0|0|
|battery:[('powersave', 'balance_power')]|1|2|2|2|1684.5 [1638.1–1730.8]|1.69|0|0|
|ac:[('powersave', 'balance_performance')]|1|4|2|1|1506.9 [1506.9–1506.9]|1.71|0|0|
|battery:[('powersave', 'balance_power')]|1|4|2|2|1634.5 [1634.4–1634.6]|1.58|0|0|
|ac:[('powersave', 'balance_performance')]|1|8|2|1|766.5 [766.5–766.5]|5.90|0|0|
|battery:[('powersave', 'balance_power')]|1|8|2|2|1023.3 [970.4–1076.1]|4.06|0|0|
|ac:[('powersave', 'balance_performance')]|2|1|2|2|1725.3 [1710.4–1740.3]|1.48|0|0|
|battery:[('powersave', 'balance_power')]|2|1|2|1|1632.5 [1632.5–1632.5]|1.64|0|0|
|ac:[('powersave', 'balance_performance')]|2|2|2|2|1670.6 [1654.5–1686.6]|1.54|0|0|
|battery:[('powersave', 'balance_power')]|2|2|2|1|1574.6 [1574.6–1574.6]|1.68|0|0|
|ac:[('powersave', 'balance_performance')]|2|4|2|2|1397.8 [1371.0–1424.5]|1.79|0|0|
|battery:[('powersave', 'balance_power')]|2|4|2|1|1468.0 [1468.0–1468.0]|1.61|0|0|
|ac:[('powersave', 'balance_performance')]|4|1|2|2|1592.7 [1552.3–1633.0]|1.69|0|0|
|battery:[('powersave', 'balance_power')]|4|1|2|1|1495.5 [1495.5–1495.5]|1.82|0|0|
|ac:[('powersave', 'balance_performance')]|4|2|2|2|1534.3 [1496.8–1571.7]|1.68|0|0|
|battery:[('powersave', 'balance_power')]|4|2|2|1|1470.2 [1470.2–1470.2]|1.78|0|0|
|ac:[('powersave', 'balance_performance')]|8|1|2|2|1358.1 [1332.8–1383.4]|2.01|0|0|
|battery:[('powersave', 'balance_power')]|8|1|2|1|1428.5 [1428.5–1428.5]|1.89|0|0|
|ac:[('powersave', 'balance_performance')]|1|1|8|1|2091.7 [2091.7–2091.7]|4.63|0|0|
|battery:[('powersave', 'balance_power')]|1|1|8|2|1917.2 [1912.3–1922.0]|5.34|0|0|
|ac:[('powersave', 'balance_performance')]|1|2|8|1|1713.0 [1713.0–1713.0]|5.96|0|0|
|battery:[('powersave', 'balance_power')]|1|2|8|2|1816.0 [1796.3–1835.6]|5.79|0|0|
|ac:[('powersave', 'balance_performance')]|1|4|8|1|1648.2 [1648.2–1648.2]|6.15|0|0|
|battery:[('powersave', 'balance_power')]|1|4|8|2|1764.9 [1757.4–1772.3]|6.02|0|0|
|ac:[('powersave', 'balance_performance')]|1|8|8|2|844.8 [793.8–895.8]|19.70|0|0|
|battery:[('powersave', 'balance_power')]|1|8|8|1|1048.6 [1048.6–1048.6]|11.69|0|0|
|ac:[('powersave', 'balance_performance')]|2|1|8|2|2029.4 [2022.2–2036.6]|5.11|0|0|
|battery:[('powersave', 'balance_power')]|2|1|8|1|1907.7 [1907.7–1907.7]|5.44|0|0|
|ac:[('powersave', 'balance_performance')]|2|2|8|2|1924.3 [1916.1–1932.5]|5.11|0|0|
|battery:[('powersave', 'balance_power')]|2|2|8|1|1881.4 [1881.4–1881.4]|5.33|0|0|
|ac:[('powersave', 'balance_performance')]|2|4|8|2|1610.4 [1559.7–1661.0]|6.07|0|0|
|battery:[('powersave', 'balance_power')]|2|4|8|1|1627.2 [1627.2–1627.2]|5.59|0|0|
|ac:[('powersave', 'balance_performance')]|4|1|8|2|1944.0 [1934.8–1953.3]|5.18|0|0|
|battery:[('powersave', 'balance_power')]|4|1|8|1|1800.1 [1800.1–1800.1]|5.67|0|0|
|ac:[('powersave', 'balance_performance')]|4|2|8|2|1750.3 [1694.7–1805.8]|5.76|0|0|
|battery:[('powersave', 'balance_power')]|4|2|8|1|1775.2 [1775.2–1775.2]|5.62|0|0|
|ac:[('powersave', 'balance_performance')]|8|1|8|2|1611.8 [1604.5–1619.1]|5.95|0|0|
|battery:[('powersave', 'balance_power')]|8|1|8|1|1722.3 [1722.3–1722.3]|5.92|0|0|
|ac:[('powersave', 'balance_performance')]|1|1|32|1|1956.1 [1956.1–1956.1]|6.40|2480|0|
|battery:[('powersave', 'balance_power')]|1|1|32|2|1737.2 [1701.3–1773.1]|7.52|4943|0|
|ac:[('powersave', 'balance_performance')]|1|2|32|1|1543.7 [1543.7–1543.7]|8.43|2453|0|
|battery:[('powersave', 'balance_power')]|1|2|32|2|1662.8 [1575.5–1750.0]|7.73|4933|0|
|ac:[('powersave', 'balance_performance')]|1|4|32|1|1668.6 [1668.6–1668.6]|7.61|2469|0|
|battery:[('powersave', 'balance_power')]|1|4|32|2|1757.2 [1694.6–1819.7]|7.16|4930|0|
|ac:[('powersave', 'balance_performance')]|1|8|32|2|680.7 [625.9–735.6]|24.96|5164|0|
|battery:[('powersave', 'balance_power')]|1|8|32|1|993.2 [993.2–993.2]|13.31|2578|0|
|ac:[('powersave', 'balance_performance')]|2|1|32|2|1973.0 [1956.0–1990.0]|9.20|3843|0|
|battery:[('powersave', 'balance_power')]|2|1|32|1|1859.5 [1859.5–1859.5]|9.90|1907|0|
|ac:[('powersave', 'balance_performance')]|2|2|32|2|1818.3 [1780.0–1856.6]|10.30|3831|0|
|battery:[('powersave', 'balance_power')]|2|2|32|1|1862.5 [1862.5–1862.5]|9.79|1916|0|
|ac:[('powersave', 'balance_performance')]|2|4|32|2|1441.7 [1292.1–1591.3]|12.04|4025|0|
|battery:[('powersave', 'balance_power')]|2|4|32|1|1535.8 [1535.8–1535.8]|11.02|1959|0|
|ac:[('powersave', 'balance_performance')]|4|1|32|2|2006.0 [1998.7–2013.2]|14.10|1755|0|
|battery:[('powersave', 'balance_power')]|4|1|32|1|1841.5 [1841.5–1841.5]|15.77|814|0|
|ac:[('powersave', 'balance_performance')]|4|2|32|2|1709.1 [1576.0–1842.2]|17.05|1571|0|
|battery:[('powersave', 'balance_power')]|4|2|32|1|1752.5 [1752.5–1752.5]|17.62|805|0|
|ac:[('powersave', 'balance_performance')]|8|1|32|2|1626.8 [1435.8–1817.8]|22.86|385|0|
|battery:[('powersave', 'balance_power')]|8|1|32|1|1793.0 [1793.0–1793.0]|18.80|264|0|

## Carico programmato

|Energia|Regime|Worker|Thread|Richieste/s|p95 client ms|Rifiuti|Slot saltati|
|---|---|---:|---:|---:|---:|---:|---:|
|battery:[('powersave', 'balance_power')]|rate-0.5|1|1|350.5|17.71|2330|16335|
|battery:[('powersave', 'balance_power')]|rate-0.5|4|1|465.3|21.62|1894|13311|
|transition|rate-0.8|1|1|516.1|13.67|2407|28828|
|ac:[('powersave', 'balance_performance')]|rate-0.8|4|1|643.3|10.70|6394|75610|
|ac:[('powersave', 'balance_performance')]|rate-1.0|1|1|615.0|8.40|7453|112331|
|ac:[('powersave', 'balance_performance')]|rate-1.0|4|1|785.3|9.96|6425|97882|
|ac:[('powersave', 'balance_performance')]|rate-1.2|1|1|722.3|7.74|7504|137610|
|ac:[('powersave', 'balance_performance')]|rate-1.2|4|1|919.9|8.95|6502|120604|
|ac:[('powersave', 'balance_performance')]|rate-0.5|1|1|353.0|10.03|4749|32464|
|ac:[('powersave', 'balance_performance')]|rate-0.5|4|1|439.9|12.38|4059|27927|
|ac:[('powersave', 'balance_performance')]|rate-0.8|1|1|511.3|8.95|4922|57804|

## Interpretazione e limiti

Confrontare il motore isolato con HTTP: la capacità del servizio può essere limitata da ricezione, serializzazione, log sincroni e generatore, prima che dai kernel. Il numero di thread richiesto non dimostra l’utilizzo effettivo di altrettanti core. Il valore CPU è tempo CPU/tempo reale, comprende tutti i thread del processo: 1,0 equivale al tempo CPU di una CPU logica pienamente occupata, non misura i joule consumati. La prova solo motore include parsing, copie, invoke, postprocessing e controllo delle uscite. Le misure HTTP di CPU escludono il riscaldamento; quelle del solo motore e del generatore includono il riscaldamento.

Il generatore mantiene una richiesta pendente per client, registra gli slot programmati saltati e applica il backoff originale sui 429: non è un generatore open-loop illimitato. La scelta esplorativa del candidato usa soltanto il regime energetico iniziale e la mediana del throughput con il massimo numero di client della matrice, ed è esplorativa. Altre applicazioni sul PC possono influenzare i tempi. RSS include runtime TensorFlow e interpreti: non è la sola memoria dei tensori.

Gli invii programmati condividono la stessa origine temporale: generano raffiche sincronizzate. I rate sono target riferiti alla capacità della baseline nel regime iniziale su alimentatore; il carico consegnato può essere molto inferiore per effetto di 429, backoff e slot saltati. Il vantaggio di più worker in questa fase può comprendere la maggiore capacità di ammissione (coda più lavori attivi), oltre al calcolo. Questi risultati non misurano isolatamente la velocità dei kernel né rappresentano arrivi uniformi o traffico Wi-Fi reale.

Le tre ripetizioni complessive sono ripartite fra diversi regimi energetici: ogni riga indica quante ripetizioni effettivamente confrontabili contiene. Non si ricava una classifica universale aggregando alimentazioni o profili differenti.

Richieste HTTP completate e verificate: **5783532**; errori: **0**.

Registrazioni iniziali completate prima del riscaldamento; alimentazione e profilo energetico controllati durante la campagna.

Dati completi: `results/manifest.json`, `results/results.jsonl` e directory per prova. Il manifest conserva hardware, dipendenze, hash dei sorgenti e manifest del modello.
