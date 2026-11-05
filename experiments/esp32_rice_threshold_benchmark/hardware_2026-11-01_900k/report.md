# Codec INT8 sulla ESP32

1752 richieste misurate, 0 diagnostiche; stato originale ripristinato e verificato. Percorsi lossless esatti.

Decoder Rice sul server: native. L'audit ricostruisce tutti i pacchetti con Python indipendente.

Proxy applicativo: target 900 kbit/s, rate effettivo mediano 897.30 kbit/s. Non simula contesa o perdita Wi-Fi.

|Ingresso|Giro|Metodo|Payload B|HTTP B|Ciclo p50/p95 ms|FPS|
|---|---:|---|---:|---:|---:|---:|
|video|0|raw|4608.0|6909.0|216.50/266.61|4.46|
|video|0|rice_temporal|2534.0|4835.0|206.13/279.02|4.57|
|video|1|raw|4608.0|6909.0|216.36/246.28|4.32|
|video|1|rice_temporal|2534.0|4835.0|206.89/341.36|4.47|
|video|2|raw|4608.0|6909.0|216.36/250.15|4.51|
|video|2|rice_temporal|2534.0|4835.0|203.60/253.76|4.71|
|video|3|raw|4608.0|6909.0|216.18/239.43|4.48|
|video|3|rice_temporal|2534.0|4835.0|202.06/235.58|4.83|
|video|4|raw|4608.0|6909.0|219.68/263.51|4.40|
|video|4|rice_temporal|2534.0|4835.0|204.83/235.03|4.81|
|video|5|raw|4608.0|6909.0|216.96/360.60|4.25|
|video|5|rice_temporal|2534.0|4835.0|204.49/281.87|4.62|

Criterio operativo: mediana almeno 5% inferiore al raw e p95 non oltre +5%, in tutte e tre le coppie video.

- rice_temporal: non soddisfatto.

Una scheda, un video e questa rete. Byte HTTP applicativi: esclusi TCP/IP, ACK e ritrasmissioni. I tempi server sono già nel ciclo; minime heap cumulative e buffer comuni non misurano firmware separati. Sono confrontati soltanto raw INT8 e Rice temporale.
