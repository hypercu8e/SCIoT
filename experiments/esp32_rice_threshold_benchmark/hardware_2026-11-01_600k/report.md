# Codec INT8 sulla ESP32

1752 richieste misurate, 0 diagnostiche; stato originale ripristinato e verificato. Percorsi lossless esatti.

Decoder Rice sul server: native. L'audit ricostruisce tutti i pacchetti con Python indipendente.

Proxy applicativo: target 600 kbit/s, rate effettivo mediano 598.26 kbit/s. Non simula contesa o perdita Wi-Fi.

|Ingresso|Giro|Metodo|Payload B|HTTP B|Ciclo p50/p95 ms|FPS|
|---|---:|---|---:|---:|---:|---:|
|video|0|raw|4608.0|6909.0|237.88/266.63|3.96|
|video|0|rice_temporal|2534.0|4835.0|219.64/364.60|4.07|
|video|1|raw|4608.0|6909.0|241.33/318.74|3.94|
|video|1|rice_temporal|2534.0|4835.0|216.29/260.30|4.53|
|video|2|raw|4608.0|6909.0|267.00/339.17|3.64|
|video|2|rice_temporal|2534.0|4835.0|246.21/354.23|3.77|
|video|3|raw|4608.0|6909.0|239.14/362.96|3.93|
|video|3|rice_temporal|2534.0|4835.0|218.65/387.36|3.09|
|video|4|raw|4608.0|6909.0|238.57/274.79|4.07|
|video|4|rice_temporal|2534.0|4835.0|219.58/282.87|4.42|
|video|5|raw|4608.0|6909.0|238.91/278.69|4.06|
|video|5|rice_temporal|2534.0|4835.0|214.93/254.25|4.55|

Criterio operativo: mediana almeno 5% inferiore al raw e p95 non oltre +5%, in tutte e tre le coppie video.

- rice_temporal: soddisfatto.

Una scheda, un video e questa rete. Byte HTTP applicativi: esclusi TCP/IP, ACK e ritrasmissioni. I tempi server sono già nel ciclo; minime heap cumulative e buffer comuni non misurano firmware separati. Sono confrontati soltanto raw INT8 e Rice temporale.
