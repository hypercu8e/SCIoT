# Codec INT8 sulla ESP32

3504 richieste misurate, 0 diagnostiche; stato originale ripristinato e verificato. Percorsi lossless esatti.

Decoder Rice sul server: native. L'audit ricostruisce tutti i pacchetti con Python indipendente.

Proxy applicativo: target 512 kbit/s, rate effettivo mediano 509.58 kbit/s. Non simula contesa o perdita Wi-Fi.

|Ingresso|Giro|Metodo|Payload B|HTTP B|Ciclo p50/p95 ms|FPS|
|---|---:|---|---:|---:|---:|---:|
|video|0|raw|4608.0|6909.0|243.77/327.47|3.88|
|video|0|zlib1|3934.1|6235.1|237.53/286.89|4.07|
|video|0|rice_independent|3895.6|6196.6|237.85/325.65|3.96|
|video|0|rice_temporal|2534.0|4835.0|218.73/285.01|4.24|
|video|1|raw|4608.0|6909.0|241.24/270.78|3.96|
|video|1|zlib1|3934.1|6235.1|239.48/286.10|4.07|
|video|1|rice_independent|3895.6|6196.6|237.72/274.20|4.08|
|video|1|rice_temporal|2534.0|4835.0|222.21/275.93|4.35|
|video|2|raw|4608.0|6909.0|242.72/324.61|3.80|
|video|2|zlib1|3934.1|6235.1|237.89/275.30|4.10|
|video|2|rice_independent|3895.6|6196.6|236.70/264.54|4.02|
|video|2|rice_temporal|2534.0|4835.0|221.88/279.61|4.36|
|video|3|raw|4608.0|6909.0|241.40/269.92|4.01|
|video|3|zlib1|3934.1|6235.1|238.49/298.55|4.04|
|video|3|rice_independent|3895.6|6196.6|235.87/280.59|4.07|
|video|3|rice_temporal|2534.0|4835.0|218.02/284.64|4.38|
|video|4|raw|4608.0|6909.0|240.02/276.21|4.07|
|video|4|zlib1|3934.1|6235.1|238.77/295.75|4.01|
|video|4|rice_independent|3895.6|6196.6|238.39/285.70|3.99|
|video|4|rice_temporal|2534.0|4835.0|219.36/262.34|4.41|
|video|5|raw|4608.0|6909.0|243.12/308.08|3.90|
|video|5|zlib1|3934.1|6235.1|239.02/297.10|4.00|
|video|5|rice_independent|3895.6|6196.6|237.92/283.52|4.09|
|video|5|rice_temporal|2534.0|4835.0|225.47/267.65|4.33|

Criterio operativo: mediana almeno 5% inferiore al raw e p95 non oltre +5%, in tutte e tre le coppie video.

- rice_independent: non soddisfatto.
- rice_temporal: soddisfatto.

Una scheda, un video e questa rete. Byte HTTP applicativi: esclusi TCP/IP, ACK e ritrasmissioni. I tempi server sono già nel ciclo; minime heap cumulative e buffer comuni non misurano firmware separati. Le configurazioni D+DZ restano con perdita e non sono approvate per l’applicazione.
