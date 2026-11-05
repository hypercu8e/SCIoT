# Codec INT8 sulla ESP32

3504 richieste misurate, 0 diagnostiche; stato originale ripristinato e verificato. Percorsi lossless esatti.

Decoder Rice sul server: native. L'audit ricostruisce tutti i pacchetti con Python indipendente.

|Ingresso|Giro|Metodo|Payload B|HTTP B|Ciclo p50/p95 ms|FPS|
|---|---:|---|---:|---:|---:|---:|
|video|0|raw|4608.0|6886.0|174.61/199.80|5.54|
|video|0|zlib1|3934.1|6212.1|179.33/211.68|5.47|
|video|0|rice_independent|3895.6|6173.6|175.92/209.75|5.04|
|video|0|rice_temporal|2534.0|4812.0|179.96/259.01|4.86|
|video|1|raw|4608.0|6886.0|185.45/282.17|4.83|
|video|1|zlib1|3934.1|6212.1|181.31/278.93|4.91|
|video|1|rice_independent|3895.6|6173.6|181.23/273.67|4.86|
|video|1|rice_temporal|2534.0|4812.0|178.71/262.58|5.00|
|video|2|raw|4608.0|6886.0|175.76/263.40|5.03|
|video|2|zlib1|3934.1|6212.1|186.25/270.65|4.78|
|video|2|rice_independent|3895.6|6173.6|178.10/257.31|5.05|
|video|2|rice_temporal|2534.0|4812.0|176.68/262.08|5.11|
|video|3|raw|4608.0|6886.0|177.12/262.37|5.07|
|video|3|zlib1|3934.1|6212.1|185.51/260.77|4.71|
|video|3|rice_independent|3895.6|6173.6|179.82/265.43|5.05|
|video|3|rice_temporal|2534.0|4812.0|182.21/282.58|4.69|
|video|4|raw|4608.0|6886.0|187.12/257.39|4.83|
|video|4|zlib1|3934.1|6212.1|182.47/258.22|4.99|
|video|4|rice_independent|3895.6|6173.6|181.93/278.13|4.83|
|video|4|rice_temporal|2534.0|4812.0|176.64/256.86|5.05|
|video|5|raw|4608.0|6886.0|177.18/260.65|5.02|
|video|5|zlib1|3934.1|6212.1|184.09/256.36|4.87|
|video|5|rice_independent|3895.6|6173.6|182.11/255.74|4.95|
|video|5|rice_temporal|2534.0|4812.0|179.04/273.40|4.89|

Criterio operativo: mediana almeno 5% inferiore al raw e p95 non oltre +5%, in tutte e tre le coppie video.

- rice_independent: non soddisfatto.
- rice_temporal: non soddisfatto.

Una scheda, un video e questa rete. Byte HTTP applicativi: esclusi TCP/IP, ACK e ritrasmissioni. I tempi server sono già nel ciclo; minime heap cumulative e buffer comuni non misurano firmware separati. Le configurazioni D+DZ restano con perdita e non sono approvate per l’applicazione.
