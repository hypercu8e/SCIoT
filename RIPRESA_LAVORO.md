# Punto di ripresa SCIoT — aggiornamento dell'11 novembre 2026

## Da dove ricominciare (12 novembre)

**Obiettivo in corso:** far entrare le attivazioni del prefisso nella RAM
interna del client operativo. Il guadagno misurato è grande: `Invoke()` da
84,7 a 62,3 ms (−26%). Però serve spazio: oggi il picco senza PAD è
178.688 byte e il limite fissato è 161.323 (minimo libero del client
194.091 − riserva 32 KB).

**Esperimento senza PAD committato e pushato il 12 novembre**
(`results/`, `artifacts/`, `include/generated/` e `idf/components/` restano
ignorati da Git).

**Prima cosa da fare: scegliere una delle due strade** (nessuna ancora approvata):

1. **Consigliata: buffer a strisce più piccolo in ESP-NN.** La depthwise con
   padding riserva circa 40 KB (`esp_nn_get_depthwise_conv_scratch_size_esp32s3`
   e ramo strip-tiled in `esp_nn_depthwise_conv_s8_esp32s3.c`, budget fisso
   di 40 KB, 17 righe da 2.352 byte). Con 3–4 righe il picco scenderebbe verso
   145 KB. Prova locale sulla scheda B, senza rete: copia del componente
   nell'esperimento (mai modificare quello del client), stessi controlli byte
   per byte, misura del tempo della depthwise in PSRAM e in RAM interna.
   Scratch size e kernel devono restare coerenti: il kernel ricava l'altezza
   della striscia dalla dimensione dello scratch.
2. **Buffer Wi-Fi/lwIP in PSRAM nel client** (`CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP`).
   Libera RAM interna ma tocca la rete, già fragile (HTTP 408 col percorso Pixel/ADB).

**Dopo, in ogni caso:** prova di capienza nel client con Wi-Fi e camera attivi
(blocco interno contiguo più grande, minimo libero, stabilità). Solo dopo:
porting di LUT + modello senza PAD (o PAD veloce) + arena interna nel client,
e misura del ciclo completo. Prima del porting: il modello senza PAD cambia
SHA-256, che il client usa per registrarsi al server (manifest da aggiornare).

**Stato hardware e ambiente:** scheda B con firmware originale ripristinato e
verificato, boot confermato; nessun server, Pixel o inoltro ADB attivo.
Ultimo backup verificato di B:
`experiments/esp32_nopad_benchmark/results/2026-11-11-B-01/board/original-flash.bin`
(usabile come `--seed`). Build: `experiments/esp32_deadzone_benchmark/results/build-tools/bin/pio`
con `PLATFORMIO_CORE_DIR` assoluto e `IDF_COMPONENT_MANAGER=0`, analisi con `.venv/bin/python`.

**Risultati di oggi, in ordine:**
[PAD veloce](experiments/esp32_pad_benchmark/2026-11-11/report.md) (−9,4 ms) →
[attivazioni in RAM interna](experiments/esp32_memory_benchmark/2026-11-11/report.md) (−22,4 ms, limite superiore) →
[prefisso senza PAD](experiments/esp32_nopad_benchmark/2026-11-11/report.md) (−47 KB di picco, stessi byte).

## Ultimo lavoro: prefisso senza nodo PAD

Esperimento `experiments/esp32_nopad_benchmark/`, scheda B, senza rete né
camera. `make_nopad.py` riscrive il prefisso congelato togliendo il PAD e
mettendo padding SAME nella depthwise (SHA-256 `43419ffa…3b97`, file
ignorato da Git e rigenerabile). Stessi byte su PC (503 input) e scheda
(4 varianti, 2.160 inferenze misurate).

Picco attivazioni 225.840 → 178.688 byte: sopra il limite di 161.323
(minimo libero del client 194.091 − riserva 32 KB). Il buffer a strisce
ESP-NN della depthwise con padding pesa circa 40 KB. Tempo: −1,7 ms con
attivazioni in PSRAM, invariato in RAM interna (62,24 ms).

Decisione aperta per la prossima sessione, entrambe da approvare:
(a) liberare RAM interna nel client spostando i buffer Wi-Fi/lwIP in PSRAM
(`CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP`), con il rischio sulla rete già
fragile; (b) ridurre il buffer a strisce della depthwise nel componente
ESP-NN (picco verso 145 KB), modificando un componente congelato.
Flash B ripristinata e verificata, boot confermato. Committato e pushato il 12 novembre.
[Report](experiments/esp32_nopad_benchmark/2026-11-11/report.md).

## Attivazioni in RAM interna, il filone merita — 11 novembre

Esperimento `experiments/esp32_memory_benchmark/`, scheda B, senza
Wi-Fi/camera/HTTP. Stessa API TFLM a due arene, PAD veloce in entrambe;
cambia solo la memoria delle attivazioni. `Invoke()` 84,723 → 62,289 ms
(−26,5%); 17,5 ms dagli operatori diversi dal PAD, oltre la soglia di 5 ms
fissata prima. Zero differenze, attivazioni canoniche identiche al
precedente firmware. Blocco interno contiguo all'avvio 278.528 byte.

Vincolo: picco attivazioni 225.840 byte, il client con Wi-Fi/camera ha
minimo 194 KB liberi. Senza nodo PAD il picco sarebbe circa 138 KB.
Prossimi passi da approvare: (1) rimuovere il PAD dal grafo con padding
SAME nella depthwise, verifica byte per byte; (2) prova di capienza nel
client con Wi-Fi e camera; (3) poi portare tutto nel client e misurare il
ciclo completo. Flash B ripristinata e verificata, boot confermato.
Esperimenti PAD e memoria committati e pushati l'11 novembre.
[Report](experiments/esp32_memory_benchmark/2026-11-11/report.md).

## PAD veloce, criteri superati — 11 novembre

Esperimento separato `experiments/esp32_pad_benchmark/`, solo scheda B,
senza camera/Wi-Fi/HTTP. Il PAD del nodo 4 usa copie per righe e riempimento
del bordo al posto del kernel TFLM; preparazione e parametri restano TFLM.
Modello, split, componenti e arena invariati.

Correttezza: 3.687.936 byte del tensore PAD confrontati su 32 input, zero
diversi; zero differenze sulle 1.260 esecuzioni della misura; attivazioni
canoniche identiche al precedente firmware ESP32. Test su PC contro il kernel
TFLM su 2.001 casi; 11 test superati.

Tempi (mediana dei p50 di tre round): PAD 14,647 → 5,209 ms (−64,4%),
`Invoke()` 93,913 → 84,482 ms (−9,431 ms, −10,0%); altri operatori invariati.
Calibrazione: il PAD veloce costa quasi quanto una copia in PSRAM
(5,0 contro 4,9 ms); in RAM interna la copia richiede 0,3 ms.

Prossimi passi possibili, da decidere: promuovere PAD (e LUT) nel client
operativo e misurare il ciclo completo; oppure filone memoria, buffer critici
in RAM interna. Flash originale B ripristinata e verificata, boot confermato.
Il lavoro fino al 10 novembre è stato committato e pushato l'11 novembre.
[Report](experiments/esp32_pad_benchmark/2026-11-11/report.md).

## Profilazione locale del prefisso completata — 10 novembre

Esperimento separato `experiments/esp32_layer_profile/`, solo scheda B,
senza camera/Wi-Fi/HTTP. Tre input fissi, tre round normale/profilato:
540 inferenze misurate, 90 warmup, 2.970 misure di operatori. Arena in PSRAM
sempre allo stesso indirizzo, 229.820 byte effettivi su 1 MiB allocato.

Tempo normale 93,762 ms, profilato 93,874 ms (mediane dei p50 dei round,
scostamento +0,119%). Principali costi: prima CONV_2D 23,439 ms (25,0%),
espansione 1×1 del nodo 3 18,017 ms (19,2%), PAD 14,628 ms (15,6%).
Prossimo candidato concreto: PAD mediante copie per righe/riempimento del
bordo, confrontando esattamente i byte. Anche memoria interna/PSRAM resta
un esperimento distinto; nessuna ottimizzazione nuova implementata qui.

Profilata e normale identiche su tutti gli output; identiche anche alle tre
attivazioni canoniche del precedente firmware ESP32. Il confronto aggiuntivo
con TFLite PC mostra differenze già presenti, massimo 4 livelli INT8:
non chiamarlo equivalenza PC/ESP32. Dettagli e log del primo audit stretto
fallito sono conservati, senza invalidare l'attribuzione dei tempi sul backend
ESP32 precedente.

Flash originale B ripristinata e verificata, boot originale confermato.
Cinque test analizzatore superati, build e misure fisiche riuscite. Nessun
server avviato; Pixel non necessario. Nessun commit/push.
[Report e dati](experiments/esp32_layer_profile/2026-11-10/report.md).

## Chiusura concordata del filone LUT

L'utente considera conclusa questa valutazione: la LUT è utile e numericamente
equivalente. Il beneficio della conversione locale non dipende dalla rete;
il -27,2% del ciclo completo è invece il risultato della configurazione misurata,
non una percentuale garantita su qualsiasi collegamento.

Il timeout HTTP è considerato probabilmente legato al particolare percorso
hotspot Pixel + USB/ADB. È un'interpretazione plausibile, non una causa isolata
sperimentalmente; l'ora resta interrotta nei risultati. **Non riaprire
automaticamente la diagnostica di rete né ripetere l'ora.** Alla prossima
sessione si può proseguire con altro lavoro, conservando la LUT come risultato
acquisito. Codice nel progetto sperimentale; integrazione nel client operativo
non eseguita in questa sessione.

## Ultimo esito: confronto lungo concluso, ora interrotta

Originale e sola LUT con framebuffer trattenuto: completate tre serie da
1.000 frame per versione su A e il confronto da 1.000 frame per versione su
entrambe le schede. Criteri superati: ciclo individuale mediano 336,232 →
244,757 ms (circa -27,2%); confermati anche p95 e freschezza su A e B.

L'ora continua fallisce dopo circa 34 minuti per HTTP 408 su A, timeout di
ricezione del corpo a 3 s. Le disconnessioni Wi-Fi registrate sono all'avvio,
non al momento del guasto. Causa non isolata. Nessuna promozione della LUT.
La precedente proposta di diagnostica HTTP e ripetizione dell'ora è stata
accantonata alla chiusura concordata sopra. Timeout invariati.

Tutte le 23.829 risposte HTTP 200 archiviate hanno punteggi identici al replay;
anche 2 terminali HTTP 408, il secondo dopo lo stop. Dati della fase parziale
separati da 295 risposte emesse durante l'arresto. Corretto il conteggio:
240 warmup e 294 record senza campione seriale, non 534 warmup.

Correzione successiva del runner: reset di entrambe le schede prima di chiudere
i log e procedere ai ripristini sequenziali; il nuovo arresto non è ancora
collaudato con una campagna hardware. Sette test analizzatore superati.

Entrambe le flash originali ripristinate e verificate, boot confermati; server
spento, seriali libere, inoltro ADB rimosso. Il telefono può essere scollegato.
Nessun commit/push. [Report lungo e audit](experiments/esp32_input_camera_benchmark/2026-11-10/lut-hold-full-report.md).

## Screening HTTP precedente del 10 novembre

Due nuovi controlli individuali del vecchio client, in ordine A/B e B/A,
completano 320 richieste. Lo screening HTTP delle quattro varianti su A
completa tre ripetizioni da 20 frame camera ciascuna, più input incorporati
e warmup: altre 1.200 richieste. Tutte le 1.520 risposte hanno punteggi identici
al replay; zero errori dispositivo o HTTP 408 nelle prove odierne.

Il trasporto rimane variabile: nel riferimento uno scambio dura 5,2 s, contro
circa 0,15 s misurati nel servizio server. La causa dei precedenti 408 non è
isolata. Non dichiarare stabilità prolungata o risoluzione del problema.

La sola LUT con buffer trattenuto è promettente: ciclo p50 descrittivo da
438,614 a 322,488 ms (circa -26,5%), cadenza da 2,177 a 2,745 risultati/s e
età al risultato p95 da 572,467 a 487,465 ms. LUT + rilascio anticipato ha
p50 più basso, ma età p95 circa 1.011 ms e un intervallo fra risultati da 5 s.
Sono mediane delle statistiche di tre serie brevi: nessuna candidata selezionata
o promossa, nessuna nuova prova simultanea o di un'ora.

Prossimo passo: confronto HTTP completo da 1.000 frame per variante e
ripetizione, conservando le misure di freschezza, cadenza ed errori. La modalità
nuova `--http-smoke-only` serve solo allo screening e non applica la selezione.
Non serve ripetere automaticamente diagnostica locale ed equivalenza numerica
se codice, modello e configurazione non cambiano.

Flash originali e boot confermati: A ripristinata dopo lo screening, B intatta
durante lo screening e riavviata sul firmware originale. Server spento, seriali
libere, inoltro ADB rimosso. Alla ripresa ricreare l'inoltro e verificare IP,
identità delle schede e nuovi backup prima di installare firmware. Modifiche
ancora locali, nessun commit/push odierno.

[Report e audit del 10 novembre](experiments/esp32_input_camera_benchmark/2026-11-10/report.md).

## Handoff precedente — 9 novembre

Riprendere da qui nella prossima sessione. Per oggi il lavoro è terminato: nessuna campagna o server sperimentale lasciato in esecuzione.

## Cosa abbiamo concluso

1. **La campagna precedente con due ESP32 è riuscita:** prove simultanee, riavvio isolato e un'ora di camera continua; 34.296 richieste con punteggi del suffisso identici al replay. La validazione vale per quella configurazione Pixel + ADB, modello e split. [Report multi-client](experiments/multiclient_hardware/2026-11-09-pixel-adb-full/report.md).
2. **Abbiamo implementato e verificato due ottimizzazioni locali:** conversione RGB565 → INT8 con tabella e restituzione anticipata del framebuffer. Le implementazioni sono nel progetto sperimentale separato, non promosse al client operativo.
3. **Non conosciamo ancora il guadagno dell'ottimizzazione sul sistema completo.** I nuovi confronti HTTP sono stati interrotti da HTTP 408, riprodotto anche con il vecchio firmware di controllo. La precedente campagna riuscita resta valida. La causa dei nuovi errori non è isolata.

## Risultati locali da conservare come riferimento

Una ESP32-S3-EYE, INT8, ESP-NN, split `block_2_add`, camera 96×96, XCLK 16 MHz, un framebuffer. Tre ripetizioni da 200 frame per variante RGB565, senza HTTP e senza suffisso. Valori sotto: mediane delle statistiche delle tre ripetizioni.

| Variante | Conversione p50 ms | Ciclo locale p50 ms | Attivazioni/s | Età frame p95 ms |
|---|---:|---:|---:|---:|
| Originale, buffer trattenuto | 47,174 | 195,009 | 5,002 | 194,004 |
| LUT, buffer trattenuto | 1,291 | 145,014 | 6,669 | 148,169 |
| Originale, rilascio anticipato | 47,644 | 144,130 | 6,671 | 283,154 |
| LUT, rilascio anticipato | 1,544 | 98,178 | 9,624 | 197,149 |

- La LUT con buffer trattenuto dà l'attivazione di frame meno vecchi; LUT + rilascio anticipato è la candidata locale con maggiore cadenza e p95 dell'età entro +5% dal riferimento.
- I 9,624/s sono **attivazioni del prefisso**, non predizioni FOMO complete ricevute dal server. Il ciclo locale termina dopo inferenza del prefisso e packing. Il timestamp del frame è quello del driver, non una misura precisa dell'esposizione.
- Equivalenza: zero differenze sui 65.536 colori RGB565 e confronto integrale di input/attivazioni su 100 frame reali, anche durante il riempimento del frame successivo.
- Totale del run valido: 2.600 frame camera misurati (2.400 RGB565 + 200 grayscale), 780 campioni incorporati, zero watchdog o eventi seriali corrotti.
- Costo LUT: 64 KiB in PSRAM più overhead dell'allocatore e circa 327 ms di inizializzazione, esclusi dal ciclo. Non dichiarare guadagni energetici o picco RAM misurato.
- Grayscale nativo: una sola serie esplorativa, circa 97,130 ms e 9,737 attivazioni/s. Cambia l'ingresso del modello: qualità su scene annotate non verificata; escluso dalla selezione.

[Report e audit completi](experiments/esp32_input_camera_benchmark/2026-11-09/report.md) · [implementazione e comandi](experiments/esp32_input_camera_benchmark/README.md) · [tutti i filoni software](FILONI_OTTIMIZZAZIONE_SOFTWARE.md).

## Da dove continuare: prima la stabilità HTTP

1. Leggere il report e controllare lo stato Git; ci sono modifiche precedenti e nuovi file non committati. Preservarli. Non eseguire reset/restore generali e non assumere che il lavoro sia già sul remoto.
2. Identificare le due schede effettivamente collegate, verificare che le seriali siano libere e fare nuovi backup delle flash attuali prima di installare firmware. I ruoli usati sono A `24:ec:4a:0e:b7:6c`, B `24:ec:4a:0e:c3:14`.
3. Ricontrollare hotspot, IP del telefono e percorso verso il server. Per ripetere Pixel + ADB: telefono USB, hotspot a 2,4 GHz e debug autorizzato; ricreare `adb reverse tcp:8000 tcp:8000`. **L'inoltro è stato rimosso a fine sessione.** Gli IP possono cambiare. Credenziali e URL stanno nel file ignorato `src/client/esp32-s3-eye-multiclient/include/network.local.h`; non stamparne il contenuto completo o versionarlo.
4. Ripartire con prove brevi del **vecchio client HTTP v2**, separatamente su A e B: input incorporati e poi camera. Il controller storico supporta `--single-only`. Confrontare una sola condizione per volta: cavo/porta/alimentazione, posizione/rete, camera spenta/accesa e percorso diretto/ADB se disponibile. Nei precedenti test sul laptop il guasto aveva seguito cavo/porta; questo è un indizio, non una misura di alimentazione né una causa dimostrata per il nuovo problema.
5. Raccogliere tempi dispositivo, ricezione corpo sul server e disconnessioni. **HTTP 408 qui è il timeout di ricezione del corpo (3 s), non la coda d'inferenza.** Non allungare i timeout per nascondere il guasto; non attribuirlo automaticamente a LUT, protocollo, server o telefono.
6. Quando il riferimento HTTP torna ripetibilmente stabile, riprendere il confronto HTTP fra le quattro varianti, con input e modello invariati. Il progetto sperimentale supporta i comandi seriali `0`–`4`; `g` misura 1.000 frame e `h` un'ora. `campaign.py` senza `--local-only` esegue il confronto individuale e, se trova una candidata, le prove su due schede e l'ora di stabilità.
7. Promuovere una variante al client operativo solo dopo confronto completo riuscito, verifica di correttezza e stabilità. Misurare insieme ciclo, FPS utili per dispositivo, età dei frame, errori e memoria. Un miglioramento locale non garantisce lo stesso miglioramento della risposta finale.

La diagnostica locale è già conclusa: non serve ripeterla automaticamente per ripartire. Si ripete se cambiano codice, modello, configurazione o emerge un dubbio specifico.

## File, ambienti e risultati da ritrovare

- Esperimento nuovo: `experiments/esp32_input_camera_benchmark/`; firmware in `idf/`, varianti e criteri nel README.
- Ambiente build/USB: `experiments/esp32_deadzone_benchmark/results/build-tools/bin/python` e relativo `pio`. Ambiente server/replay: `.venv/bin/python`.
- Cache build da usare con percorso assoluto: `PLATFORMIO_CORE_DIR="$PWD/experiments/esp32_deadzone_benchmark/results/platformio-core"`.
- Componenti congelati: copia locale nel progetto sperimentale, come documentato nel README. Evitare dipendenze esterne al progetto via CMake: hanno causato collisioni degli oggetti PlatformIO. Non rigenerare pesi o quantizzazione.
- Modelli/header congelati: `experiments/esp32_representation_benchmark/artifacts/` e `include/generated/`; se mancanti usare il ripristino hash-verificato documentato in `experiments/multiclient_hardware/restore_runtime.py`.
- Run HTTP interrotti: `experiments/esp32_input_camera_benchmark/results/2026-11-09-input-camera/` e `2026-11-09-input-camera-wifi-off/`.
- Controllo vecchio firmware: stesso percorso `results/2026-11-09-legacy-control/`; 72 richieste riuscite poi 408, ripristino di entrambe verificato.
- Primo run locale **invalidato**: `results/2026-11-09-local-diagnostic/`; watchdog e una riga persa. Non aggregarlo con i risultati validi.
- Run locale **valido**: `results/2026-11-09-local-yield/`; audit in `local-audit.json`, copie pubblicabili nel report datato. Pause di un tick ogni dieci frame, watchdog attivo. Snapshot dei sorgenti, hash dei componenti e firmware conservati nel run.
- Cinque test dell'analizzatore e build firmware superati. L'audit locale ha verificato tutte le serie e gli eventi; gli audit HTTP dei tentativi riusciti parzialmente hanno ricalcolato i punteggi del suffisso.

I risultati grezzi, le flash, i binari e le credenziali sono ignorati da Git: non trasferirli tramite commit per errore. A fine sessione **A ripristinata e verificata integralmente con boot originale; B intatta nella prova locale e boot originale confermato**. Nessun firmware sperimentale lasciato attivo.

## Ultime quattro giornate: testo per la scheda tirocinio

Ricostruzione dalle date dei log e del diario, non dalle sole date dei commit. Ore e presenze amministrative non vengono dedotte. Oggi è la quarta giornata di questo riepilogo.

| Giornata | Data documentata | Descrizione sintetica per la scheda |
|---|---|---|
| 1 | 30/10/2026 | Implementazione e valutazione su ESP32 di codec lossless per tensori INT8, con decoder nativo e prove a banda limitata. |
| 2 | 01/11/2026 | Misura della soglia di convenienza della compressione Rice e analisi del parallelismo del server con più client, worker e thread. |
| 3 | 05/11/2026 | Preparazione delle prove hardware multi-client e diagnostica dei collegamenti Wi-Fi/USB, con automazione dei test, backup e ripristino delle schede. |
| 4 | 09/11/2026 | Validazione del sistema con due ESP32 e ottimizzazione della preparazione dell'input e dell'acquisizione immagini, con verifiche numeriche e misure delle latenze. |

Fonti: [diario](DIARIO_TIROCINIO.md), [codec del 30 ottobre](experiments/esp32_lossless_codec_benchmark/report.md), [soglia Rice](experiments/esp32_rice_threshold_benchmark/sweep_2026-11-01/report.md), [parallelismo server](experiments/server_parallelism/2026-11-01/ac/README.md), [prove del 5 novembre](experiments/multiclient_hardware/2026-11-05/report.md), [diagnosi laptop/USB](RIPRESA_MULTICLIENT_LAPTOP.md), [multi-client del 9 novembre](experiments/multiclient_hardware/2026-11-09-pixel-adb-full/report.md), [ottimizzazioni del 9 novembre](experiments/esp32_input_camera_benchmark/2026-11-09/report.md).
