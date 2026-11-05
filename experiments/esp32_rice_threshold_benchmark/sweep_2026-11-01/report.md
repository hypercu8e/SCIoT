# Soglia operativa Rice: prove hardware

Solo INT8 raw e Rice temporale; sei giri video per rate, 146 frame/giro/metodo. Ogni punto comprende 1752 richieste. Il criterio richiede mediana almeno -5% e p95 non oltre +5% in tutte le tre coppie.

|Proxy kbit/s|Raw p50 ms|Rice p50 ms|Variazione aggregata|Criterio 3 coppie|
|---:|---:|---:|---:|---|
|[600](../hardware_2026-11-01_600k/report.md)|240.12|219.59|-8.55%|superato|
|[800](../hardware_2026-11-01_800k/report.md)|221.67|207.77|-6.27%|superato|
|[900](../hardware_2026-11-01_900k/report.md)|216.99|204.64|-5.69%|non superato|
|[1000](../hardware_2026-11-01_1000k/report.md)|213.25|202.21|-5.18%|non superato|

**Massimo rate verificato che supera il criterio: 800 kbit/s. Fascia fra punti osservati: 800–900 kbit/s.**

Esito della ricerca: observed transition bracket 800–900 kbit/s (not a confidence interval).

Il criterio è un margine operativo, non il semplice pareggio. Un punto non superato può comunque avere una mediana aggregata migliore: devono superare i limiti tutte le tre coppie, compreso il p95.

## Coppie che non superano il criterio

- 900 kbit/s, coppia 1: guadagno mediano 4.43%, variazione p95 +13.02%.
- 1000 kbit/s, coppia 2: guadagno mediano 4.87%, variazione p95 +3.39%.

Validazione: 7008 richieste fisiche; attivazioni e uscite identiche al raw INT8, ripristino integrale e avvio originale verificati dopo ogni punto. Recuperi di prefissi seriali: 0; nessun tempo stimato.

[Grafico della fascia osservata](threshold.png) · [Versione SVG](threshold.svg).

La fascia individuata è un intervallo fra punti osservati, non un intervallo di confidenza o una soglia universale. Rete e luogo possono differire dalle prove di ottobre. Il proxy limita il corpo della richiesta: non misura il PHY Wi-Fi né simula contesa o ritrasmissioni. I limiti del modello/video e la fedeltà al raw INT8 restano distinti dall’accuratezza annotata.
