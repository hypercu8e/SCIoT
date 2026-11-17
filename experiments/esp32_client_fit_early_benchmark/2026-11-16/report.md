# Capienza con camera e Wi-Fi — esito negativo

**Allocazione interna fallita dopo l’avvio dei servizi.** Wi-Fi con indirizzo IP e camera inizializzata.

- RAM interna totale libera: **219,755 byte**.
- Massimo blocco contiguo: **124,928 byte**.
- Blocco richiesto: **145,824 byte** (145.760 più due sentinelle da 32).

La memoria libera è distribuita in blocchi troppo piccoli. Il driver camera e il Wi-Fi risultano inizializzati; il prefisso candidato non è stato eseguito. Il test si è fermato al primo avvio: **zero frame della misura, nessuna dichiarazione di stabilità su tre avvii**.

Il riferimento temporaneo in PSRAM ha prodotto i tre canonici identici all’archivio ESP32 precedente. Questo non costituisce validazione del candidato con servizi attivi.

**Flash originale degli 8 MiB ripristinata, digest verificato prima del boot e avvio confermato.** Nessun cambiamento automatico a scratch o buffer di rete.

Prossimo esperimento proposto: riservare l’arena prima di avviare camera e Wi-Fi, come ordine di inizializzazione del client, e verificare se entrambi i servizi partono conservando i 32 KiB di riserva. Questa possibilità non è stata provata qui. HTTP, socket attivi e integrazione restano esclusi.
