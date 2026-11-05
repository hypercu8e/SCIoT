# ESP32-S3-EYE HTTP v2 INT8

Client per il [server multi-client](../../server/multiclient/README.md).
Usa il prefisso INT8 congelato, ESP-IDF 5.4 e le revisioni ufficiali dei componenti
registrate nel benchmark. Una sola arena INT8; il modello FLOAT32 non viene caricato.

Dalla radice SCIoT:

```sh
python3 src/client/esp32-s3-eye-multiclient/prepare_components.py
cp src/client/esp32-s3-eye-multiclient/include/network.local.example.h src/client/esp32-s3-eye-multiclient/include/network.local.h
pio run -d src/client/esp32-s3-eye-multiclient
```

Impostare SSID, password e `SERVER_BASE_URL` nel file locale ignorato da Git.
L'URL è la base del server, ad esempio `http://192.168.1.10:8000`, senza `/infer`
e senza slash finale. Anche i binari contengono le credenziali e sono ignorati.
Il build di verifica iniziale usa solo i valori fittizi del template.

`prepare_components.py` verifica le revisioni del benchmark e copia i sorgenti
nella directory locale ignorata `components/`, senza modificarli. Le copie locali
servono a evitare collisioni dei nomi degli oggetti di PlatformIO con componenti
esterni al progetto. Richiede gli artefatti generati del benchmark originale.

Prima di caricare verificare che nessun'altra prova stia usando la stessa scheda,
conservare e verificare una copia integrale della flash corrente (8 MB), registrare
il MAC e il relativo hash. Ripristinare quella copia e verificarla dopo la prova.
Non usare automaticamente il backup di un'altra scheda o di un'altra sessione.

```sh
pio run -d src/client/esp32-s3-eye-multiclient -t upload --upload-port /dev/ttyACM0
python experiments/esp32_representation_benchmark/capture.py --port /dev/ttyACM0 --reset --timeout 900 --log /tmp/sciot-board-run1.log
```

`capture.py` richiede pyserial; usare un percorso nuovo. Il firmware attende `g`
dopo `ready`, come il benchmark. Esegue 3 input fissi × 20 ripetizioni e poi 1.000
frame camera. `MULTICLIENT_CAMERA_FRAMES` permette di cambiare il numero al build.

Il MAC completo identifica la scheda. Registrazione e ogni POST verificano la
sessione e gli identificativi della risposta. Il contatore cresce anche su errori.
I rifiuti 429 sono contati e seguiti da una pausa 250–500 ms; gli altri errori
invalidano la sessione. Non vengono reinviate inferenze automaticamente.

Dopo la prima prova singola: affiancare un client PC e poi una seconda scheda con
lo stesso firmware; il MAC le distingue. Riavviare A mentre B continua e controllare
log server/seriali. Sono richieste almeno 1.000 operazioni per scheda e una prova di
un'ora prima di dichiarare completata la validazione hardware.

La build riuscita dimostra compilazione e link, non Wi-Fi, camera, stabilità,
correttezza hardware o prestazioni con due ESP32.

## Campagna hardware del 5 novembre

Il client aggiunge i comandi seriali `s` (60 input incorporati e 20 frame camera),
`g` (60 input e il numero configurato di frame, normalmente 1.000), `i` (60 input
e tre minuti camera), `h` (60 input e un'ora camera). Dopo ogni esecuzione torna
in attesa; registra RAM interna e PSRAM libere, correnti e minime dalla partenza.
Il framebuffer resta acquisito durante inferenza e invio; le disconnessioni
Wi-Fi sono registrate e causano un nuovo tentativo di connessione.

Le due prove iniziali si sono fermate nella verifica individuale di A per
problemi di trasmissione con camera attiva. Entrambe le flash sono state
ripristinate e verificate; le prove simultanee e di un'ora restano aperte.
[Report](../../../experiments/multiclient_hardware/2026-11-05/report.md) ·
[Ripresa sul laptop](../../../RIPRESA_MULTICLIENT_LAPTOP.md).
