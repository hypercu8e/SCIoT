# Verifica PC dei codec INT8

Attivazioni rigenerate sul desktop; tempi host non predicono ESP32. Tutti i percorsi lossless conservano byte e uscite del suffisso; il packing conserva esattamente il D+DZ4.

|Metodo|Payload medio B|Fallback raw|Frame con uscita diversa dal raw|
|---|---:|---:|---:|
|raw|4608.00|0|0|
|zlib1|3934.25|0|0|
|rice_independent|3895.45|0|0|
|rice_temporal|2534.06|0|0|
|deadzone4_zlib|1935.72|0|136|
|deadzone4_packed|2304.00|0|136|

Nessuna misura fisica effettuata da questo script.
