# Prima prova INT8 sulla ESP32-S3-EYE

Preparazione del 19 ottobre 2026. **I tre firmware compilano; non sono ancora
stati eseguiti su una scheda.** Le prove PC e gli artefatti sono in
[esp32_prep_2026-10-19](../activation_compression/esp32_prep_2026-10-19/README.md).

## Cosa farà la prova

Si carica una delle tre versioni dello stesso programma:

| Versione | Lavoro eseguito dalla scheda | Confronto atteso |
|---|---|---|
| `prefix` | Prima parte della rete, dall'immagine allo split | 4.608 byte intermedi salvati dal PC |
| `full` | Rete intera | 432 byte di uscita salvati dal PC |
| `suffix` | Seconda parte, dai risultati intermedi all'uscita | 432 byte di uscita salvati dal PC |

Le tre prove sono separate: la scheda non invia ancora le attivazioni al server.
Il firmware contiene tre input già preparati (frame 48, 96 e 145 del video).
Non inizializza camera, LCD o Wi-Fi: prima controlliamo che il calcolo funzioni,
poi aggiungeremo acquisizione e comunicazione. Nessun pin di un attuatore viene usato.
Questo progetto è separato dai firmware originali SCIoT, che non sono modificati.

Il modello candidato è in grigio `96×96×1`, diverso dal modello RGB originale
SCIoT. Le prove verificano fedeltà numerica, non accuratezza su annotazioni.

## Preparazione sul PC

Comandi dalla radice del repository. L'ambiente Python principale `.venv` è
quello già usato per gli esperimenti. Il secondo ambiente contiene solo gli
strumenti di compilazione e **su questa macchina è già installato**.

```bash
# Solo se manca l'ambiente degli strumenti:
.venv/bin/python -m venv experiments/esp32_int8_firmware/.venv
experiments/esp32_int8_firmware/.venv/bin/python -m pip install 'platformio==6.1.18'

# Rigenera gli array C dagli artefatti conservati, controllandone gli hash:
.venv/bin/python experiments/esp32_int8_firmware/generate_assets.py

# Compila senza bisogno della scheda:
experiments/esp32_int8_firmware/.venv/bin/pio run \
  -d experiments/esp32_int8_firmware -e prefix -e full -e suffix
```

Dipendenze fissate: piattaforma `espressif32@6.10.0`, Arduino ESP32 2.0.17,
`tanakamasayuki/TensorFlowLite_ESP32@1.0.0`, la stessa libreria indicata nei
firmware SCIoT esaminati. Non sono abilitate ottimizzazioni ESP-NN. Registriamo
solo i cinque operatori necessari: ADD, CONV_2D, DEPTHWISE_CONV_2D, PAD, SOFTMAX.

La configurazione usa il profilo generico ESP32-S3-DevKitC-1 con flash da 8 MB,
PSRAM OPI e USB CDC, per l'hardware N8R8 della S3-EYE. Non costituisce un profilo
camera/LCD completo per altre schede. [Guida ufficiale S3-EYE](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-eye/user_guide.html).

## Quando avremo la scheda

1. Collegarla con un cavo USB dati. Individuare la porta:

   ```bash
   experiments/esp32_int8_firmware/.venv/bin/pio device list
   ```

2. Caricare la prima parte. Sostituire `/dev/ttyACM0` con la porta effettiva:

   ```bash
   experiments/esp32_int8_firmware/.venv/bin/pio run \
     -d experiments/esp32_int8_firmware -e prefix \
     -t upload --upload-port /dev/ttyACM0
   ```

   Questo passaggio sostituisce il programma presente sulla scheda. Su una scheda
   in prestito concordare prima quali programmi conservare o ripristinare.

3. Aprire il monitor e salvare il log:

   ```bash
   mkdir -p experiments/activation_compression/results/esp32
   experiments/esp32_int8_firmware/.venv/bin/pio device monitor \
     -p /dev/ttyACM0 -b 115200 \
     | tee experiments/activation_compression/results/esp32/prefix.log
   ```

   Se manca l'inizio, premere `r` per riavviare la prova completa. Attendere la
   riga `"event":"done"`, poi uscire con Ctrl+C. Non aggiungere un filtro che
   antepone timestamp alle righe JSON. Se l'USB cambia porta al reset, riaprire
   il monitor sulla porta corretta e ripetere.

4. Verificare il log sul PC:

   ```bash
   .venv/bin/python experiments/esp32_int8_firmware/verify_serial.py \
     --stage prefix \
     --log experiments/activation_compression/results/esp32/prefix.log \
     --output experiments/activation_compression/results/esp32/prefix-verification.json
   ```

   Il controllo richiede tutti e tre gli input, gli hash corretti, allocazione,
   dati di memoria e completamento. Confronta anche i byte effettivamente
   ricevuti, senza fidarsi solo del messaggio di successo del firmware. Qualsiasi
   differenza numerica fallisce la parità esatta; non implica automaticamente
   che la qualità applicativa sia insufficiente e va investigata.

Ripetere i passi 2–4 sostituendo `prefix` con `full`, poi con `suffix` (anche
nei nomi dei file). Prima di camera/rete devono riuscire allocazione e inferenza;
conservare i log completi anche quando qualcosa fallisce.

## Cosa misuriamo e come leggerlo

- **Correttezza:** confronto di tutti i valori in ogni esecuzione con il PC;
  massimo errore espresso in passi INT8 e byte dell'ultima uscita.
- **Tempo:** due esecuzioni di riscaldamento e dieci misurate per input; minimo,
  mediana e massimo della sola `Invoke`. Copia input, confronto, stampa e attesa
  USB sono fuori dal timer. È una prima misura, non una valutazione statistica
  estesa dell'applicazione.
- **Memoria della rete:** `arena_used_bytes`, cioè la memoria gestita
  dall'interprete dopo aver allocato anche i tensori di ingresso/uscita.
- **Memoria del dispositivo:** spazio libero, minimo libero dall'avvio e più
  grande blocco libero, separatamente per memoria interna e PSRAM.

L'**arena** è lo spazio di lavoro riservato alla rete. Il valore iniziale
`ARENA_BYTES=524288` riserva 512 KiB in PSRAM: non è una misura del fabbisogno
minimo. I 19.340 byte di RAM statica indicati dal compilatore **non includono
quest'area dinamica** e non sono il picco RAM totale. Per un confronto tra prove
conservare la stessa capacità e posizione dell'arena; l'effetto di memoria
interna/PSRAM va misurato con configurazioni distinte e riportate.

In caso di `arena_allocation_failed`, controllare riconoscimento/configurazione
PSRAM. In caso di `allocate_tensors_failed`, leggere anche gli errori della
libreria, senza attribuire automaticamente il problema alla sola memoria.

Queste prove non misurano camera, preparazione immagini sulla scheda, Wi-Fi,
codec, traffico totale, energia o latenza dell'applicazione SCIoT. Il confronto
con ESP-NN e con il server originale sarà una fase successiva.

## Perché partiamo da INT8

L'ispezione del sorgente della libreria scaricata conferma i percorsi INT8 per
i cinque operatori richiesti. Per la depthwise convolution, invece, questo
runtime gestisce ingressi float32 e INT8, ma non INT16. Il nostro modello 16×8
contiene sei nodi depthwise con ingresso INT16: richiede un runtime aggiornato
o l'aggiunta di quell'implementazione prima dell'esecuzione.

È un limite della libreria selezionata, non una conclusione che l'ESP32-S3 non
possa eseguire INT16. Hash dei sorgenti controllati e conclusione circoscritta
in [runtime-audit.json](../activation_compression/esp32_prep_2026-10-19/runtime-audit.json).

