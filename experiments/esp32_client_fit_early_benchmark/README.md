# Capienza della RAM interna con camera e Wi-Fi

**16 novembre 2026: allocazione anticipata verificata sulla B.**
Arena interna riservata prima di camera/Wi-Fi, tre avvii da 1.000 frame,
zero differenze, minimo interno libero **70.155 byte** contro 32.768 richiesti.
Flash originale ripristinata e boot confermato. **15 test analizzatore superati.**
[Report anticipato](2026-11-16-early/report.md).
La [prova tardiva](2026-11-16/report.md) rimane conservata: l'allocazione dopo
camera/Wi-Fi falliva perché il massimo blocco contiguo era di 124.928 byte.
Client operativo invariato; HTTP e socket attivi ancora fuori dalla prova.

## Variante con allocazione anticipata

Il runner supporta `--allocation early` e `--allocation late` (default, per
riprodurre il primo esperimento). Nella variante anticipata il blocco interno
viene riservato prima dei buffer PSRAM e dell'avvio di Wi-Fi/camera. Rimane
occupato durante il calcolo del riferimento temporaneo in PSRAM e viene poi
usato dal candidato. Il minimo locale della memoria è monitorato dalla
prenotazione fino al termine, includendo l'avvio dei servizi; le sentinelle
del blocco riservato sono verificate anche durante il riferimento.

Il firmware registra `allocation_order` al boot e `arena_reserved` con la
collocazione effettiva. Il runner salva ordine e flag di build in
`configuration.json`; l'analizzatore verifica che corrispondano alla sequenza
osservata. Restano invariati scratch, modello, LUT, riserva, configurazione
Wi-Fi e numero di frame. I risultati delle due varianti vanno conservati in
directory distinte. Per la variante anticipata:

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_client_fit_early_benchmark/run.py --allocation early --run experiments/esp32_client_fit_early_benchmark/results/NUOVO_RUN_EARLY --seed experiments/esp32_client_fit_early_benchmark/results/2026-11-16-B-01/board/original-flash.bin
```

## Obiettivo e criteri

Scheda B (`24:ec:4a:0e:c3:14`), prefisso INT8 senza PAD e scratch depthwise
da 3 righe. Allocare **145.760 byte effettivi in RAM interna**, più due
sentinelle da 32 byte. La variante tardiva alloca **dopo** camera/Wi-Fi;
quella anticipata riserva il blocco **prima** e lo mantiene durante il loro avvio.
Tre avvii indipendenti, ciascuno con 1.000 frame camera.

Accettazione obbligatoria in tutti gli avvii:

- arena, input e output in RAM interna, memoria persistente da 64 KiB in PSRAM;
- almeno **32 KiB interni liberi**, anche come minimo locale dell'allocatore,
  dall'allocazione al termine della misura;
- 35 input confrontati integralmente contro il modello originale sullo stesso
  ESP32; i tre canonici confrontati anche con l'archivio ESP32 precedente;
- 10 controlli dei tre canonici, uno ogni 100 frame, sentinelle sempre integre,
  6 convoluzioni e 3 depthwise ESP-NN per inferenza;
- 1.000 frame RGB565 96×96 validi, nessuna disconnessione Wi-Fi durante la
  misura, errore di allocazione, watchdog, panic, brownout o corruzione heap.

Il buffer interno viene realmente allocato della dimensione richiesta, non
ricavato da un blocco preventivo da 240 KiB. Le allocazioni degli altri buffer
sono esplicite in PSRAM. Il contatore di minimo locale heap parte subito dopo
l'allocazione e include `AllocateTensors()`, validazione e inferenze camera;
nella variante anticipata include anche l'avvio di camera e Wi-Fi.

## Configurazione e isolamento

Il fisso può rimanere in Ethernet. **La ESP32 si collega direttamente al router
Wi-Fi a 2,4 GHz**; Internet, telefono, ADB e server HTTP non sono necessari.
Configurare esclusivamente `include/network.local.h`, usando come esempio
`include/network.local.example.h`. Il file locale è ignorato da Git, non viene
copiato negli snapshot e i suoi valori non vengono stampati. Il firmware e i
backup possono contenere credenziali: rimangono nei percorsi ignorati.

Il client operativo resta invariato. `prepare.py` verifica i componenti TFLM,
ESP-NN, camera e JPEG contro manifest congelati locali, crea copie private e
applica la patch scratch già verificata. Non scarica dipendenze né modifica
componenti degli esperimenti precedenti. I file di cache Python sono esclusi
dall'inventario. Il modello senza PAD è rigenerato localmente con lo stesso hash.

CPU 240 MHz, PSRAM 80 MHz, Wi-Fi STA senza power-save, buffer Wi-Fi/lwIP nella
collocazione del client operativo. Camera RGB565 96×96, XCLK 16 MHz, un
framebuffer in PSRAM trattenuto fino al termine dell'elaborazione.

Sono presenti LUT RGB565 → INT8 da 64 KiB, buffer canonico float, messaggio e
risposta delle dimensioni del client. L'interprete originale temporaneo in
PSRAM produce gli output attesi e viene distrutto prima dell'allocazione
interna. I dati di verifica restano in PSRAM durante la prova, rendendone
esplicito l'overhead. I tempi escludono i controlli dei canonici dal ciclo
camera e non costituiscono una misura del servizio completo.

## Preparazione e verifiche

Dalla radice del repository:

```sh
.venv/bin/python experiments/esp32_client_fit_early_benchmark/prepare.py
.venv/bin/python -m unittest discover -s experiments/esp32_client_fit_early_benchmark -p 'test_*.py' -v
IDF_COMPONENT_MANAGER=0 PLATFORMIO_CORE_DIR="$PWD/experiments/esp32_deadzone_benchmark/results/platformio-core" experiments/esp32_deadzone_benchmark/results/build-tools/bin/pio run -d experiments/esp32_client_fit_early_benchmark/idf
```

La build usa solo il file di rete locale di questo esperimento; il runner
ricompila sempre prima di accedere alla scheda per evitare credenziali obsolete
nel binario. Non archiviare il file locale insieme ai sorgenti.

## Campagna hardware

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_client_fit_early_benchmark/run.py --run experiments/esp32_client_fit_early_benchmark/results/NUOVO_RUN --seed experiments/esp32_scratch_benchmark/results/2026-11-16-B-01/board/original-flash.bin
.venv/bin/python experiments/esp32_client_fit_early_benchmark/analyze.py --run experiments/esp32_client_fit_early_benchmark/results/NUOVO_RUN --output experiments/esp32_client_fit_early_benchmark/results/NUOVO_RUN/report --legacy-archive experiments/esp32_input_camera_benchmark/results/2026-11-10-lut-hold-full-01/server/inference.bin
```

`--seed` è facoltativo: anche se presente, il backup viene confrontato con
l'intera flash attuale prima dell'installazione. Il runner seleziona solo B,
rifiuta seriali occupate, installa una volta ed esegue tre reset indipendenti.
Ogni avvio ha log seriale ed eventi separati. L'attesa Wi-Fi è di 30 secondi;
il limite per ciascun avvio è di 10 minuti. Un errore interrompe la campagna:
nessun cambio automatico di scratch, riserva o configurazione di rete.

Il runner ripristina in `finally`, verifica il digest degli 8 MiB prima del
boot e conferma l'applicazione originale. SIGINT/SIGTERM avviano il recupero;
un secondo segnale viene ignorato durante il ripristino. Non scollegare B
prima della conferma. Non viene cancellata automaticamente la partizione NVS
se l'inizializzazione fallisce.

L'analizzatore rifiuta campagne incomplete senza evidenza conclusiva o recuperi
non verificati. Distingue il successo completo dal fallimento osservato
dell'allocazione, riportando esplicitamente zero frame e nessun superamento
dei criteri nel secondo caso. Produce
report Markdown, JSON e CSV. I sorgenti acquisiti e il firmware installato
sono verificati tramite hash; le successive modifiche alla documentazione
non invalidano gli snapshot. Dopo una campagna completa conservare report,
riepilogo e provenienza in una directory datata; backup e log restano ignorati.

**Limite:** nessuna richiesta HTTP o socket dati attivo. Un esito positivo
verifica questa capienza locale con camera/Wi-Fi e riserva, non ancora i picchi
RAM durante trasmissione, l'accuratezza del modello, l'energia o la latenza
end-to-end. L'integrazione nel percorso HTTP è un passo successivo.

## Nome dopo la consegna sul laptop

Questa variante del 16 novembre è conservata in `esp32_client_fit_early_benchmark` per distinguerla da `esp32_client_fit_benchmark`, già presente nei commit remoti del 12 novembre. Le evidenze JSON e i log storici conservano i percorsi originali; i comandi e gli include attivi usano il nuovo nome. I due esperimenti hanno configurazioni e risultati distinti.
