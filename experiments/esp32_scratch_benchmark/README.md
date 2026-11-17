# Buffer depthwise a strisce — ESP32-S3-EYE

**16 novembre 2026: campagna hardware completata sulla scheda B.**
Selezionate **3 righe**: picco 178.688 → **145.760 byte** (−18,4%),
`Invoke()` in RAM interna 62,244 → **62,432 ms** (+0,30%).
5.400 inferenze misurate, zero differenze e ripristino integrale verificato.
**12 test analizzatore superati.** [Report e limiti](2026-11-16/report.md).
La capienza del client con camera/Wi-Fi resta da misurare.

Obiettivo: far rientrare le attivazioni del prefisso senza PAD nel limite
preliminare di **161.323 byte**, scegliendo la variante più veloce.
Il riferimento congelato richiede 178.688 byte. Limite derivato dal minimo
libero del client (194.091 byte) meno 32 KiB di riserva: non dimostra disponibilità
di un blocco contiguo nel client con camera e Wi-Fi.

## Implementazione e isolamento

`prepare.py` verifica tutti i 714 file dei componenti del benchmark senza PAD
contro il manifest del run fisico dell'11 novembre, crea copie private e applica
`esp-nn-strip.patch` senza fuzz. I componenti già preparati vengono riutilizzati
solo se corrispondono ai relativi hash. Lo script rigenera localmente il modello
senza PAD: nessuna scrittura nel benchmark precedente o nel client operativo.
I componenti locali, il modello generato e i binari restano ignorati da Git.

La patch espone solo nella copia sperimentale un limite di righe, impostato prima
di costruire l'interprete. Lo applica al dimensionamento del ramo 3×3 mult1 già
elaborato a strisce; il kernel ricava dal medesimo scratch lo spazio utilizzabile.
Valore 0: comportamento originale, **17 righe** nel nodo interessato; alternative
**3, 5, 7 e 9 righe**. Restano invariati il ramo piccolo, i pesi, la quantizzazione
e gli altri kernel. Scratch preferenziale e worker dual-core devono essere inattivi.

Un solo firmware, modello senza PAD, CPU 240 MHz, PSRAM 80 MHz, memoria
persistente in PSRAM e attivazioni alternativamente in PSRAM/RAM interna.
Camera, Wi-Fi e HTTP non inizializzati. Nessuna modifica alle API di SCIoT.

## Protocollo e criteri fissati prima della misura

- Riferimento numerico: modello originale con PAD veloce, sullo stesso ESP32,
  su 3 canonici + 32 input INT8 xorshift32 (seme 20261116). Confronto integrale
  dei 4.608 byte; i canonici vengono anche confrontati col precedente archivio
  ESP32. Non si assume equivalenza byte per byte col backend TFLite PC.
- Per ogni variante: ricerca dell'arena minima a passi di 16 byte. Inferenze
  successive eseguite proprio con quella dimensione, con sentinelle da 32 byte
  prima/dopo l'arena, controllate dopo ogni inferenza. Il blocco fisico allocato
  rimane 240 KiB più guardie, per conservare indirizzi stabili: il picco è la
  dimensione minima pianificata e verificata, non la memoria totale allocata.
- Validazione di tutti i 35 input in entrambe le memorie per tutte le varianti.
  Tre round, ordine ruotato delle 10 combinazioni variante/memoria; ordine
  inverso per il profiler. Ogni blocco: 3 input × (5 warmup + 30 misure).
  **5.400 inferenze misurate, 900 warmup, 27.000 record operatore**.
- Timer di `Invoke()` esclude copia input, controlli, stampa e pausa watchdog.
  Registrati tempi operatori, scratch richiesto, righe effettive, arena usata,
  indirizzi e heap. Le sentinelle rilevano sconfinamenti ai confini dell'arena;
  non sono una protezione individuale di ciascun tensore interno.
- Ammissibilità: zero differenze/errori, picco ≤161.323 byte, p50 e p95 di
  `Invoke()` in RAM interna entro +5% dal riferimento da 17 righe in ogni round.
  Fra le ammesse si sceglie il minore p50 (mediana dei p50 dei tre round).
  Entro l'1% dal più rapido si preferisce il picco minore; ulteriore parità:
  p50 e poi numero di righe minori. Nessuna ammissibile → nessuna promozione.

## Preparazione e build

Dalla radice del repository, con gli artefatti dei precedenti benchmark presenti:

```sh
.venv/bin/python experiments/esp32_scratch_benchmark/prepare.py
.venv/bin/python -m unittest discover -s experiments/esp32_scratch_benchmark -p 'test_*.py' -v
IDF_COMPONENT_MANAGER=0 PLATFORMIO_CORE_DIR="$PWD/experiments/esp32_deadzone_benchmark/results/platformio-core" experiments/esp32_deadzone_benchmark/results/build-tools/bin/pio run -d experiments/esp32_scratch_benchmark/idf
```

La preparazione richiede componenti e input congelati locali: il manifest non
scarica dipendenze e rifiuta versioni diverse. Le verifiche statiche sono in
[validation/2026-11-16](validation/2026-11-16/verification.json).

## Acquisizione sulla sola B

Collegare B (MAC `24:ec:4a:0e:c3:14`) e usare una directory di run nuova.
Ricompilare dopo ogni modifica ai sorgenti. Il runner controlla identità,
seriale libera e flash da 8 MiB, verifica il backup prima dell'installazione,
poi ripristina in `finally` anche dopo SIGINT/SIGTERM, verificando flash e boot
originale. Non scollegare durante flash o ripristino. `--seed` è facoltativo:
il vecchio backup viene riutilizzato solo dopo verifica della flash attuale.

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_scratch_benchmark/run.py --run experiments/esp32_scratch_benchmark/results/NUOVO_RUN --board B
.venv/bin/python experiments/esp32_scratch_benchmark/analyze.py --run experiments/esp32_scratch_benchmark/results/NUOVO_RUN --output experiments/esp32_scratch_benchmark/results/NUOVO_RUN/report --legacy-archive experiments/esp32_input_camera_benchmark/results/2026-11-10-lut-hold-full-01/server/inference.bin
```

Il runner archivia sorgenti, patch, configurazione effettiva, manifest dei
componenti e firmware installato con hash. L'analizzatore rifiuta misure
incomplete, duplicate, incoerenti o con recupero non verificato e produce
`summary.json`, `measurements.csv` e `report.md`. Dopo la campagna conservare
report e riepilogo in una directory datata versionata, mantenendo backup e
log grezzi nei risultati ignorati. Aggiornare il punto di ripresa con l'esito.

Il prossimo passo dopo un esito positivo è la prova di capienza nel client
con camera/Wi-Fi. Integrazione, rete, energia e qualità su scene annotate
restano fuori da questo esperimento.
