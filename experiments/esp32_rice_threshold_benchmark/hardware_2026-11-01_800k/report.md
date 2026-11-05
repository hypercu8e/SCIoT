# Codec INT8 sulla ESP32

1752 richieste misurate, 0 diagnostiche; stato originale ripristinato e verificato. Percorsi lossless esatti.

Decoder Rice sul server: native. L'audit ricostruisce tutti i pacchetti con Python indipendente.

Proxy applicativo: target 800 kbit/s, rate effettivo mediano 797.90 kbit/s. Non simula contesa o perdita Wi-Fi.

|Ingresso|Giro|Metodo|Payload B|HTTP B|Ciclo p50/p95 ms|FPS|
|---|---:|---|---:|---:|---:|---:|
|video|0|raw|4608.0|6909.0|222.93/301.25|4.19|
|video|0|rice_temporal|2534.0|4835.0|205.52/237.20|4.78|
|video|1|raw|4608.0|6909.0|221.95/261.55|4.36|
|video|1|rice_temporal|2534.0|4835.0|207.66/262.84|4.50|
|video|2|raw|4608.0|6909.0|222.47/243.41|4.30|
|video|2|rice_temporal|2534.0|4835.0|206.38/238.57|4.74|
|video|3|raw|4608.0|6909.0|220.95/263.26|4.41|
|video|3|rice_temporal|2534.0|4835.0|208.28/303.16|3.91|
|video|4|raw|4608.0|6909.0|220.78/245.57|4.45|
|video|4|rice_temporal|2534.0|4835.0|211.36/262.85|4.46|
|video|5|raw|4608.0|6909.0|221.82/257.30|4.41|
|video|5|rice_temporal|2534.0|4835.0|207.25/250.90|4.71|

Criterio operativo: mediana almeno 5% inferiore al raw e p95 non oltre +5%, in tutte e tre le coppie video.

- rice_temporal: soddisfatto.

Una scheda, un video e questa rete. Byte HTTP applicativi: esclusi TCP/IP, ACK e ritrasmissioni. I tempi server sono già nel ciclo; minime heap cumulative e buffer comuni non misurano firmware separati. Sono confrontati soltanto raw INT8 e Rice temporale.
