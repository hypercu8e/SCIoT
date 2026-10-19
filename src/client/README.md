# Client SCIoT

I client ESP32-S3-EYE sono disponibili per HTTP, MQTT e WebSocket. Condividono
in `common/` l'esecuzione controllata di un layer float32 e la composizione del
messaggio binario compatibile col server. Mantenere questa directory accanto ai
tre progetti quando si copia o compila il codice.

## Configurazione e compilazione

Ogni progetto usa espressif32 6.10.0 / Arduino ESP32 2.0.17 e il profilo generico
ESP32-S3-DevKitC-1 con flash 8 MB e PSRAM OPI per la S3-EYE N8R8. Non serve
installare manualmente una definizione di scheda personalizzata. Il driver
camera è quello incluso nel framework, non una seconda libreria separata.

Per usare la scheda, copiare `src/conf.template.h` in `src/conf.h` nel client
scelto e inserire rete e indirizzo del server. Senza `conf.h` la compilazione usa
il template con credenziali vuote: consente verifiche di build, non una connessione
Wi-Fi già configurata. `conf.h` resta ignorato da Git.

Con PlatformIO installato, dalla radice del repository:

```bash
pio run -d src/client/esp32-s3-eye-http
pio run -d src/client/esp32-s3-eye-mqtt
pio run -d src/client/esp32-s3-eye-websocket
```

Chi ha già un `conf.h` può mantenerlo. Per ottenere la riserva ridotta del
messaggio, aggiornare anche lì `OUTPUT_MSG_SIZE` alla definizione nel nuovo
template; una capacità inferiore al necessario viene rifiutata in compilazione.

## Comportamento e verifiche

L'interprete di ogni layer resta valido fino alla copia dell'uscita; il resolver
ha durata per tutto il programma. Errori di allocazione, tipo/dimensione dei
tensori o inferenza interrompono il percorso senza inviare un risultato valido.
Il secondo ingresso FOMO viene verificato con la dimensione dei dati conservati,
non con quella del primo ingresso. Frame camera e buffer principali sono
controllati, e il ciclo operativo non parte se PSRAM/camera/allocazioni falliscono.

Gli identificativi sono trasmessi come testo, e vengono inviati esattamente i
tempi fino allo split. Con i template attuali il buffer passa da 922.253 a
461.261 byte: 460.992 byte in meno riservati in PSRAM. Non è una misura del picco
RAM o di accelerazione della rete.

[Test nativi sul PC](../../tests/firmware/README.md) e
[risultati archiviati](../../experiments/firmware_fixes_2026-10-19/README.md).
Le prove hardware restano da eseguire: camera, connessione e riconnessioni,
gestione degli invii asincroni, tempi e memoria reali. Il protocollo e i modelli
float32 originali sono conservati; il candidato INT8 ha un firmware sperimentale
separato in `experiments/esp32_int8_firmware`.
