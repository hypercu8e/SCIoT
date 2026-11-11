# Preparazione input e acquisizione camera ESP32-S3-EYE

Esperimento isolato: modello INT8, split `block_2_add`, ESP-NN, HTTP v2 con connessione ricreata per richiesta. [Catalogo dei filoni](../../FILONI_OTTIMIZZAZIONE_SOFTWARE.md). [Risultati e limiti delle prove del 9 novembre](2026-11-09/report.md).

[Confronto lungo del 10 novembre](2026-11-10/lut-hold-full-report.md): criteri
individuali e simultanei superati, ora interrotta da HTTP 408 dopo circa
34 minuti. Nessuna promozione al client operativo.

## Varianti

| Comando | Variante | Conversione | Restituzione framebuffer |
|---|---|---|---|
| `0` | reference_hold | RGB565 → float → INT8 originale | Dopo HTTP |
| `1` | lut_hold | RGB565 → INT8, tabella 64 KiB | Dopo HTTP |
| `2` | reference_early | Conversione originale | Dopo preprocessing |
| `3` | lut_early | Tabella RGB565 → INT8 | Dopo conversione |
| `4` | gray_early | Grayscale nativo → INT8, tabella 256 byte | Dopo conversione |

Tutte le varianti riservano la tabella RGB565 in PSRAM per isolare i costi del percorso per frame. La tabella viene costruita una sola volta all'avvio, con la formula originale; costo e memoria sono registrati. Un solo framebuffer, 96×96, XCLK 16 MHz e grab-when-empty. Nessun nuovo task d'inferenza o HTTP concorrente. Il grayscale non equivale al grigio calcolato da RGB565: resta esplorativo e non autorizza conclusioni sulla qualità.

`v` verifica tutti i 65.536 colori contro la conversione originale e confronta input e attivazioni su 100 frame camera identici. `g` esegue 1.000 frame misurati, `h` un'ora. Ogni prova rinnova la sessione, include i 60 input incorporati di controllo e 20 frame camera di riscaldamento esclusi dai campioni. Le verifiche numeriche non fanno parte delle misure prestazionali.

## Riproduzione

Usare Python build-tools già disponibile per seriale/esptool e `.venv` per server/replay. Il progetto richiede una copia locale dei componenti congelati del firmware multi-client (non modificarli). I percorsi generati, risultati, credenziali e flash restano ignorati.

```sh
mkdir -p experiments/esp32_input_camera_benchmark/idf/components
cp -a src/client/esp32-s3-eye-multiclient/components/. experiments/esp32_input_camera_benchmark/idf/components/
PLATFORMIO_CORE_DIR="$PWD/experiments/esp32_deadzone_benchmark/results/platformio-core" experiments/esp32_deadzone_benchmark/results/build-tools/bin/pio run -d experiments/esp32_input_camera_benchmark/idf
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_input_camera_benchmark/prepare.py --run experiments/esp32_input_camera_benchmark/results/NUOVO_RUN
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_input_camera_benchmark/campaign.py --run experiments/esp32_input_camera_benchmark/results/NUOVO_RUN
python3 experiments/esp32_input_camera_benchmark/analyze.py --run experiments/esp32_input_camera_benchmark/results/NUOVO_RUN --output experiments/esp32_input_camera_benchmark/results/NUOVO_RUN/summary.json
.venv/bin/python experiments/esp32_input_camera_benchmark/verify_archive.py --run experiments/esp32_input_camera_benchmark/results/NUOVO_RUN --output experiments/esp32_input_camera_benchmark/results/NUOVO_RUN/audit.json
```

Prima della campagna devono esistere backup integrali verificati e snapshot con hash dei nuovi sorgenti e dei componenti. `prepare.py` salva anche i sorgenti sperimentali, gli hash dei componenti e una copia del binario. Il telefono deve avere hotspot acceso, USB e debug ADB autorizzato; la campagna imposta `adb reverse tcp:8000 tcp:8000`. Non stampare `network.local.h`.

## Misure e scelta

Tre ripetizioni per variante RGB565 sulla scheda A, con ordini 0-1-2-3, 3-2-1-0 e 1-0-3-2. Si registrano p50/p95/p99 delle fasi, età del frame alla consegna e al risultato, intervalli tra risultati, FPS e memoria. Il timestamp camera rappresenta l'avvio acquisizione del driver, non l'esposizione precisa. Il timer del risultato termina quando la risposta è stata letta; i log e gli intervalli esterni al ciclo contribuiscono invece agli FPS effettivi.

La candidata deve ridurre di almeno il 5% la mediana dei p50 delle tre ripetizioni rispetto alla baseline e non peggiorare oltre il 5% la mediana dei p95 del ciclo e dell'età al risultato. Nessun errore, nessuna sequenza di frame ripetuti e nessuna perdita di memoria rilevata. Il controllo memoria confronta mediane dei primi/ultimi tre campioni (tolleranza 4 KiB): è uno screening, non una prova di assenza di leak. A parità di condizioni scegliere il p50 più basso, poi l'identificativo più basso.

Una prova grayscale da 1.000 frame è esclusa dalla selezione. Se esiste una candidata, confrontare baseline e candidata con due schede da 1.000 frame ciascuna, poi un'ora simultanea della candidata. Il risultato finale resta soggetto alla conferma multi-client: pubblicare eventuali regressioni anche se la selezione individuale era positiva. Se non esiste una candidata, conservare la baseline.

`campaign.py` ripristina e verifica le flash originali in `finally`, anche dopo errori o segnali SIGINT/SIGTERM. Non scollegare le schede durante scritture/ripristini. Un'interruzione di alimentazione o SIGKILL richiede il ripristino manuale con `flash_board.py restore` e i backup del run.

## Confronto lungo originale / sola LUT

`campaign.py --run PERCORSO_RUN --lut-hold-only` confronta solo
`reference_hold` e `lut_hold`, tre serie da 1.000 frame misurati ciascuna,
in ordine 0-1, 1-0, 0-1. Stessi controlli numerici, warmup, modello e criteri
del confronto generale: mediana dei p50 almeno -5%, mediane dei p95 di ciclo
ed età al risultato non oltre +5%, screening memoria senza perdita rilevata.
Esclude rilascio anticipato e grayscale. Non cambiare questi criteri dopo
aver osservato i risultati.

Se la LUT passa individualmente, esegue 1.000 frame per variante su entrambe
le schede. Prima dell'ora continua richiede su **ciascuna** scheda gli stessi
margini su p50, p95, freschezza e memoria; conserva `confirmation.json` e
salta l'ora se una scheda non passa. Un run completato senza candidata o senza
conferma è un esito negativo del confronto, non una validazione della LUT.
L'ora, quando eseguita, deve poi superare gli audit e il replay indipendente.

## Screening HTTP breve

`campaign.py --run PERCORSO_RUN --http-smoke-only` verifica prima l'equivalenza
numerica, poi esegue le quattro varianti RGB565 su A in tre ordini alternati.
Ogni serie usa il comando `s`: 60 input incorporati, 20 frame di warmup e 20
frame camera misurati. Conserva `smoke-summary.json`, senza selezionare candidate
o avviare grayscale, prove simultanee o l'ora di stabilità. Le statistiche di
20 frame sono esplorative e non sostituiscono il confronto completo.

Usare la stessa preparazione con backup verificati. Al termine A viene
ripristinata; B rimane intatta dopo il backup e va riavviata con
`boot_unchanged.py --run PERCORSO_RUN`. Verificare le risposte con
`verify_archive.py`; per ricalcolare le statistiche brevi usare `summarize(run)`
da `analyze.py`, senza applicare la selezione delle candidate.

## Diagnostica locale quando HTTP non è stabile

Il comando `d` esegue 200 frame misurati, con gli stessi 20 frame camera di warmup e controlli incorporati, senza registrazione o scambio HTTP per frame. I log dichiarano `transport: local_no_http`, byte di richiesta/risposta zero e tempo rete zero. Il timestamp finale indica quando è pronta l'attivazione del prefisso sulla scheda: non viene calcolata la predizione FOMO del suffisso e questa età non è l'età di una risposta dal server.

`campaign.py --local-only` confronta le quattro varianti in tre ripetizioni da 200 frame, riavviando prima di ogni serie; aggiunge il grayscale esplorativo e ripristina la scheda. La candidata selezionata è soltanto locale: non avvia la conferma multi-client o l'ora HTTP. Il server viene mantenuto per compatibilità della strumentazione, ma non riceve inferenze locali. Non applicare `verify_archive.py` ai campioni locali, che non hanno richieste/risposte; verificare invece gli eventi numerici di `v` e la completezza dei campioni con `analyze.py`.

La diagnostica locale cede un tick al task idle ogni dieci frame (anche nei controlli incorporati e nel warmup). Questa pausa è esterna al timer del ciclo e inclusa negli FPS effettivi. Il watchdog resta attivo: la campagna rifiuta serie con suoi avvisi. Il primo tentativo locale senza queste pause è stato invalidato per un avviso watchdog che ha corrotto una riga seriale.

A ripristino concluso, verificare il run locale con `python3 experiments/esp32_input_camera_benchmark/verify_local.py --run PERCORSO_RUN --output PERCORSO_RUN/local-audit.json`. L'audit richiede tutte le 13 serie complete, zero avvisi watchdog o eventi corrotti, zero inferenze sul server e il ripristino verificato di A.

Prima dell'audit locale, riavviare B (rimasta intatta dopo il backup) e confermarne il boot originale:

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_input_camera_benchmark/boot_unchanged.py --run PERCORSO_RUN
python3 experiments/esp32_input_camera_benchmark/verify_local.py --run PERCORSO_RUN --output PERCORSO_RUN/local-audit.json
```

Questa verifica aggiuntiva riguarda il run `--local-only`: per la campagna HTTP completa entrambe le schede installate vengono già ripristinate e avviate dal controller.
