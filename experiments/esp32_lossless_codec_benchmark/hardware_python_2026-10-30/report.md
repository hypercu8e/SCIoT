# Codec INT8 sulla ESP32

5616 richieste misurate, 360 diagnostiche; stato originale ripristinato e verificato. Percorsi lossless esatti.

Decoder Rice sul server: python. L'audit ricostruisce tutti i pacchetti con Python indipendente.

|Ingresso|Giro|Metodo|Payload B|HTTP B|Ciclo p50/p95 ms|FPS|
|---|---:|---|---:|---:|---:|---:|
|video|0|raw|4608.0|6886.0|174.57/249.36|5.31|
|video|0|zlib1|3934.1|6212.1|178.03/207.70|5.46|
|video|0|rice_independent|3895.6|6173.6|183.31/203.23|5.38|
|video|0|rice_temporal|2534.0|4812.0|184.37/207.68|5.28|
|video|0|deadzone4_zlib|1934.3|4212.3|214.11/237.93|4.59|
|video|0|deadzone4_packed|2304.0|4582.0|204.79/239.06|4.66|
|video|1|raw|4608.0|6886.0|173.23/193.26|5.70|
|video|1|zlib1|3934.1|6212.1|179.03/205.02|5.39|
|video|1|rice_independent|3895.6|6173.6|187.22/245.93|5.09|
|video|1|rice_temporal|2534.0|4812.0|185.31/225.18|5.19|
|video|1|deadzone4_zlib|1934.3|4212.3|216.36/259.42|4.46|
|video|1|deadzone4_packed|2304.0|4582.0|205.76/248.04|4.49|
|video|2|raw|4608.0|6886.0|192.72/241.78|4.97|
|video|2|zlib1|3934.1|6212.1|205.37/282.30|4.55|
|video|2|rice_independent|3895.6|6173.6|208.15/288.69|4.42|
|video|2|rice_temporal|2534.0|4812.0|210.08/287.22|4.46|
|video|2|deadzone4_zlib|1934.3|4212.3|232.34/285.03|3.70|
|video|2|deadzone4_packed|2304.0|4582.0|222.05/264.38|4.39|
|video|3|raw|4608.0|6886.0|203.37/293.82|4.58|
|video|3|zlib1|3934.1|6212.1|207.91/268.14|4.55|
|video|3|rice_independent|3895.6|6173.6|209.23/283.86|4.50|
|video|3|rice_temporal|2534.0|4812.0|203.73/295.74|4.54|
|video|3|deadzone4_zlib|1934.3|4212.3|235.94/301.80|4.07|
|video|3|deadzone4_packed|2304.0|4582.0|226.26/275.04|4.21|
|video|4|raw|4608.0|6886.0|204.50/276.57|4.61|
|video|4|zlib1|3934.1|6212.1|198.63/270.66|4.63|
|video|4|rice_independent|3895.6|6173.6|211.14/285.59|4.47|
|video|4|rice_temporal|2534.0|4812.0|207.82/295.58|4.48|
|video|4|deadzone4_zlib|1934.3|4212.3|234.07/287.16|4.14|
|video|4|deadzone4_packed|2304.0|4582.0|224.41/283.11|4.26|
|video|5|raw|4608.0|6886.0|194.65/246.25|4.93|
|video|5|zlib1|3934.1|6212.1|190.88/244.13|5.01|
|video|5|rice_independent|3895.6|6173.6|201.84/276.99|4.72|
|video|5|rice_temporal|2534.0|4812.0|205.03/282.45|4.59|
|video|5|deadzone4_zlib|1934.3|4212.3|234.12/274.26|4.18|
|video|5|deadzone4_packed|2304.0|4582.0|224.82/280.69|4.25|
|camera|0|raw|4608.0|6886.0|184.45/226.27|5.28|
|camera|0|zlib1|3622.0|5900.0|185.09/218.63|5.27|
|camera|0|rice_independent|3648.6|5926.6|192.27/230.10|5.03|
|camera|0|rice_temporal|2816.0|5094.0|193.32/206.16|5.10|
|camera|0|deadzone4_zlib|2335.1|4613.1|218.16/261.11|4.40|
|camera|0|deadzone4_packed|2304.0|4582.0|211.60/250.40|4.59|
|camera|1|raw|4608.0|6886.0|199.53/225.79|4.89|
|camera|1|zlib1|3616.6|5894.6|232.28/265.68|4.34|
|camera|1|rice_independent|3647.4|5925.4|204.17/219.85|4.81|
|camera|1|rice_temporal|2816.3|5094.3|207.94/229.03|4.74|
|camera|1|deadzone4_zlib|2338.9|4616.9|231.73/251.30|4.07|
|camera|1|deadzone4_packed|2304.0|4582.0|228.66/301.59|4.11|

Criterio operativo: mediana almeno 5% inferiore al raw e p95 non oltre +5%, in tutte e tre le coppie video.

- rice_independent: non soddisfatto.
- rice_temporal: non soddisfatto.

Una scheda, un video e questa rete. Byte HTTP applicativi: esclusi TCP/IP, ACK e ritrasmissioni. I tempi server sono già nel ciclo; minime heap cumulative e buffer comuni non misurano firmware separati. Le configurazioni D+DZ restano con perdita e non sono approvate per l’applicazione.
