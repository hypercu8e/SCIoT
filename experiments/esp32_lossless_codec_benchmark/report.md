# Ultima verifica della compressione INT8

16128 richieste fisiche misurate e 360 diagnostiche; tutte le campagne complete, auditate e con firmware originale ripristinato e verificato. Tutti i percorsi lossless conservano attivazioni e uscite byte per byte.

|Condizione|Raw p50 ms|Rice temporale p50 ms|Variazione p50 aggregata|Criterio sulle 3 coppie|
|---|---:|---:|---:|---|
|[Wi-Fi ordinaria, Python](hardware_python_2026-10-30/report.md)|191.09|198.77|+4.02%|non superato|
|[Wi-Fi ordinaria, C++](hardware_native_network_2026-10-30/report.md)|177.36|178.84|+0.84%|non superato|
|[Proxy 128 kbit/s, C++](hardware_native_128k_2026-10-30/report.md)|478.13|349.45|-26.91%|superato|
|[Proxy 512 kbit/s, C++](hardware_native_512k_2026-10-30/report.md)|241.85|221.26|-8.51%|superato|

Le mediane aggregate descrivono tutti i sei giri video. La decisione usa invece tre confronti separati, ciascuno su due giri in ordine invertito: mediana almeno -5% e p95 non oltre +5%. Non è una garanzia statistica per altre scene o reti.

Rice temporale: 2533.96 byte/frame contro 4608 raw, risparmio 45.01%. Nella campagna completa D+DZ4 con miniz e con packing producono la stessa ricostruzione con perdita; non sono candidati all'obiettivo lossless.

Nella rete ordinaria provata nessun candidato Rice supera il criterio operativo. Il vantaggio è condizionato ai regimi limitati che superano il criterio: Proxy 128 kbit/s, C++ (rice_independent, rice_temporal); Proxy 512 kbit/s, C++ (rice_temporal). Raw resta il riferimento per la latenza ordinaria; Rice è un candidato opzionale per banda ridotta.

Nota di audit (Proxy 128 kbit/s, C++): 1 prefisso identificativo USB troncato ricostruito da pacchetto e righe adiacenti. Tempi presenti integralmente nel log originale, nessuna stima; manifest e hash conservati.

## Interpretazione e limiti

- Il decoder C++ elimina il costo del ciclo Rice interpretato; il decoder Python indipendente verifica offline tutti i pacchetti. Confrontare ciascun codec con il raw della stessa campagna, senza attribuire al backend differenze assolute fra sessioni radio diverse.
- Il proxy limita il corpo applicativo della richiesta, con rate effettivo registrato. Non riproduce contesa Wi-Fi, perdita, ritrasmissioni o consumo energetico. I byte HTTP non sono occupazione radio.
- Una ESP32-S3-EYE, un modello, uno split e un video. Camera verificata nella campagna completa; confronti nativi e limitati usano ingressi video identici. La fedeltà al raw INT8 non misura accuratezza rispetto ad annotazioni né equivalenza al modello float32.
- I buffer comuni del benchmark non rappresentano picchi RAM di firmware separati. Integrazione SCIoT, addestramento di bottleneck e altri split rimangono fuori dalla prova.

La ricognizione bibliografica è mirata, non esaustiva. I risultati delimitano questa esplorazione post-hoc su INT8; non dimostrano impossibilità di ulteriori codec o metodi addestrati.
