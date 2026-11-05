# Codec INT8 sulla ESP32

1752 richieste misurate, 0 diagnostiche; stato originale ripristinato e verificato. Percorsi lossless esatti.

Decoder Rice sul server: native. L'audit ricostruisce tutti i pacchetti con Python indipendente.

Proxy applicativo: target 1000 kbit/s, rate effettivo mediano 996.69 kbit/s. Non simula contesa o perdita Wi-Fi.

|Ingresso|Giro|Metodo|Payload B|HTTP B|Ciclo p50/p95 ms|FPS|
|---|---:|---|---:|---:|---:|---:|
|video|0|raw|4608.0|6909.0|212.26/270.23|4.29|
|video|0|rice_temporal|2534.0|4835.0|202.07/245.95|4.81|
|video|1|raw|4608.0|6909.0|213.13/249.43|4.40|
|video|1|rice_temporal|2534.0|4835.0|200.94/263.84|4.51|
|video|2|raw|4608.0|6909.0|212.81/263.77|4.32|
|video|2|rice_temporal|2534.0|4835.0|202.68/357.81|4.48|
|video|3|raw|4608.0|6909.0|212.31/266.04|4.58|
|video|3|rice_temporal|2534.0|4835.0|200.58/239.40|4.87|
|video|4|raw|4608.0|6909.0|215.01/261.67|4.51|
|video|4|rice_temporal|2534.0|4835.0|203.17/243.54|4.79|
|video|5|raw|4608.0|6909.0|213.31/260.38|4.32|
|video|5|rice_temporal|2534.0|4835.0|203.20/267.50|4.44|

Criterio operativo: mediana almeno 5% inferiore al raw e p95 non oltre +5%, in tutte e tre le coppie video.

- rice_temporal: non soddisfatto.

Una scheda, un video e questa rete. Byte HTTP applicativi: esclusi TCP/IP, ACK e ritrasmissioni. I tempi server sono già nel ciclo; minime heap cumulative e buffer comuni non misurano firmware separati. Sono confrontati soltanto raw INT8 e Rice temporale.
