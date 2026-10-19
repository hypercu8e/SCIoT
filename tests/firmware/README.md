# Verifiche autonome del firmware SCIoT

Questi test eseguono sul PC le funzioni C++ usate dai tre firmware, con la
libreria reale TensorFlowLite_ESP32 1.0.0. Non simulano l'hardware ESP32 e non
misurano le sue prestazioni. Risultati del 19 ottobre:
[archivio delle verifiche](../../experiments/firmware_fixes_2026-10-19/README.md).

## Esecuzione

Dalla radice del repository, nell'ambiente Python del progetto (TensorFlow
2.15, NumPy, Pillow e pandas), con CMake e un compilatore C++ GCC/Clang disponibili:

```bash
# PlatformIO può essere un comando pio già installato; su questa macchina:
experiments/esp32_int8_firmware/.venv/bin/pio run -d src/client/esp32-s3-eye-http
experiments/esp32_int8_firmware/.venv/bin/pio run -d src/client/esp32-s3-eye-mqtt
experiments/esp32_int8_firmware/.venv/bin/pio run -d src/client/esp32-s3-eye-websocket

.venv/bin/python tests/firmware/check_firmware.py
```

Il test usa per default la libreria installata dal client HTTP, e conserva
build, input, riferimenti e log nella cartella ignorata
`experiments/activation_compression/results/firmware-checks`. Opzioni
`--runtime /percorso/TensorFlowLite_ESP32/src` e `--output-dir /percorso` per altre
installazioni. Il test non si connette a broker/server/NTP e non aggiorna i
profili salvati del server; importa il parser effettivo senza avviare il servizio.

## Cosa viene verificato

- I 59 modelli del server coincidono byte per byte con quelli incorporati nei
  tre client. Tutti gli input/output sono float32 e rientrano nei buffer; i rami
  residui sono verificati rispetto al grafo Keras originale.
- Due ripetizioni, tre input sintetici deterministici (zero, casuale con seed
  fisso e gradiente), sei split: 0, 11, 25, 43, 52, 58. Ogni layer ricostruisce
  e distrugge l'interprete sulla stessa arena, copiando l'output prima del ritorno.
  Il riferimento esegue gli stessi binari con i kernel di riferimento TFLite,
  senza delegati; tolleranza dichiarata `rtol=1e-5`, `atol=1e-5`.
- Le uscite finali del riferimento TFLite vengono confrontate anche con Keras.
  Le differenze intermedie sono registrate separatamente: non attribuiamo al
  refactoring differenze tra conversione TFLite e calcolo Keras.
- Puntatore modello nullo, schema errato, arena insufficiente/non allineata,
  ingresso di dimensione o tipo errati, secondo ingresso FOMO mancante o di
  dimensione errata, uscita troppo grande o non float32 e `Invoke` fallita.
  I modelli con operazione custom che fallisce sono fixture sintetiche, non
  modelli destinati alla scheda. Il buffer di lavoro resta invariato al fallimento.
- Pacchetti con split iniziale/finale e dimensione massima; identificativi con
  lunghezza errata, buffer insufficiente, conteggio tempi errato e valori di
  dimensione che potrebbero causare overflow. Nessuna scrittura al fallimento.
  Il parser Python originale deve ricostruire identificativi, timestamp,
  attivazioni e tempi; la lunghezza inviata deve coincidere con i campi dichiarati.

AddressSanitizer e UndefinedBehaviorSanitizer sono attivi anche sulla libreria
nativa. Le stampe `SCIoTFail` e `Failed starting model allocation` nello stderr
sono attese nelle prove negative; l'esito del processo e `summary.json` stabiliscono
se la verifica è riuscita. Non vengono disattivati i controlli tramite `NDEBUG`.
