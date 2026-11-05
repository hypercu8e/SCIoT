# Codec INT8 sulla ESP32

3504 richieste misurate, 0 diagnostiche; stato originale ripristinato e verificato. Percorsi lossless esatti.

Recupero seriale dichiarato: 1 prefisso identificativo ricostruito dai pacchetti originali; tutti i tempi conservati dalla riga USB, nessun campione temporale stimato. Log originale invariato e manifest di recupero esportato.

Decoder Rice sul server: native. L'audit ricostruisce tutti i pacchetti con Python indipendente.

Proxy applicativo: target 128 kbit/s, rate effettivo mediano 127.83 kbit/s. Non simula contesa o perdita Wi-Fi.

|Ingresso|Giro|Metodo|Payload B|HTTP B|Ciclo p50/p95 ms|FPS|
|---|---:|---|---:|---:|---:|---:|
|video|0|raw|4608.0|6909.0|478.26/500.39|2.08|
|video|0|zlib1|3934.1|6235.1|440.31/497.12|2.25|
|video|0|rice_independent|3895.6|6196.6|430.31/459.37|2.29|
|video|0|rice_temporal|2534.0|4835.0|330.55/483.98|2.85|
|video|1|raw|4608.0|6909.0|481.50/529.93|2.04|
|video|1|zlib1|3934.1|6235.1|448.41/512.83|2.16|
|video|1|rice_independent|3895.6|6196.6|441.86/515.77|2.20|
|video|1|rice_temporal|2534.0|4835.0|334.00/504.13|2.74|
|video|2|raw|4608.0|6909.0|481.52/540.21|2.02|
|video|2|zlib1|3934.1|6235.1|449.32/521.22|2.16|
|video|2|rice_independent|3895.6|6196.6|441.31/514.92|2.16|
|video|2|rice_temporal|2534.0|4835.0|346.71/497.48|2.77|
|video|3|raw|4608.0|6909.0|475.55/546.61|2.05|
|video|3|zlib1|3934.1|6235.1|439.03/516.54|2.15|
|video|3|rice_independent|3895.6|6196.6|432.75/512.03|2.18|
|video|3|rice_temporal|2534.0|4835.0|362.05/505.88|2.57|
|video|4|raw|4608.0|6909.0|475.78/515.62|2.07|
|video|4|zlib1|3934.1|6235.1|440.53/515.90|2.18|
|video|4|rice_independent|3895.6|6196.6|426.84/521.44|2.19|
|video|4|rice_temporal|2534.0|4835.0|359.92/505.52|2.64|
|video|5|raw|4608.0|6909.0|469.80/526.49|2.06|
|video|5|zlib1|3934.1|6235.1|432.20/503.77|2.25|
|video|5|rice_independent|3895.6|6196.6|428.28/492.66|2.25|
|video|5|rice_temporal|2534.0|4835.0|367.94/504.82|2.56|

Criterio operativo: mediana almeno 5% inferiore al raw e p95 non oltre +5%, in tutte e tre le coppie video.

- rice_independent: soddisfatto.
- rice_temporal: soddisfatto.

Una scheda, un video e questa rete. Byte HTTP applicativi: esclusi TCP/IP, ACK e ritrasmissioni. I tempi server sono già nel ciclo; minime heap cumulative e buffer comuni non misurano firmware separati. Le configurazioni D+DZ restano con perdita e non sono approvate per l’applicazione.
