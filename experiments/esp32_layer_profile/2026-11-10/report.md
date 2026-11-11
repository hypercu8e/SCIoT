# Profilazione del prefisso ESP32-S3-EYE — 10 novembre 2026

**Profilazione fisica completata.** La prima convoluzione, l'espansione 1×1
del nodo 3 e il padding del nodo 4 assorbono insieme circa il **59,7%** del
tempo di inferenza. Il padding è un bersaglio concreto per una prossima prova:
circa **14,6 ms** per copiare il tensore e aggiungere il bordo.

## Misura

Scheda B `24:ec:4a:0e:c3:14`, modello INT8 congelato `block_2_add`, ESP-NN e
TFLite Micro locali del benchmark precedente. CPU configurata a 240 MHz,
PSRAM a 80 MHz, data cache 32 KiB. Una sola arena da 1 MiB in PSRAM, stesso
indirizzo e stessa allocazione effettiva di **229.820 byte** (circa 224,4 KiB)
per tutti i blocchi.

Tre input fissi, frame 48/96/145. Tre round normale/profilato in ordine
0-1, 1-0, 0-1; cinque warmup e trenta misure per input e blocco.
**540 inferenze misurate**, 90 warmup, **2.970 record operatore**. Input
copiati prima del timer; confronto output, stampa e pause al task idle dopo
il timer. Watchdog attivo, nessun suo avviso nel log.

Camera, Wi-Fi, HTTP e LUT non sono inizializzati. Si misura `Invoke()`;
questi risultati non sono FPS camera o latenza dell'applicazione completa.

## Costo della strumentazione

| Modalità | Mediana dei p50 dei tre round |
|---|---:|
| Normale, profiler nullo e wrapper con soli contatori | 93,762 ms |
| Profilata, callback per nodo e timer ESP-NN | 93,874 ms |

Scostamento osservato **+0,119%**, circa 112 µs. È una stima dell'effetto
complessivo della strumentazione nelle condizioni provate, non una misura
isolata del costo di ogni timer né un intervallo di confidenza.

Le percentuali seguenti usano le **somme dei tempi** delle 270 inferenze
profilate, divise per la somma dei rispettivi tempi `Invoke()`. Non sono
rapporti fra mediane indipendenti. Gli scope dei nodi coprono il **99,906%**
di `Invoke()`; le entrypoint ESP-NN misurate ne coprono l'**82,776%**.
Il tempo delle entrypoint comprende anche eventuali copie e preparazioni
interne: non dimostra che ogni istruzione eseguita sia SIMD.

## Tutti gli operatori, ordine del modello

Gli indici sono zero-based. Il tempo del nodo include il kernel TFLM e il
reset delle allocazioni temporanee compreso nello scope del profiler.

| Nodo | Operatore | Uscita H×W×C | Tempo p50 ms | Quota di Invoke |
|---:|---|---|---:|---:|
| 0 | CONV_2D 3×3, stride 2 | 48×48×16 | 23,439 | 24,97% |
| 1 | DEPTHWISE_CONV_2D | 48×48×16 | 8,589 | 9,15% |
| 2 | CONV_2D 1×1 | 48×48×8 | 3,802 | 4,05% |
| 3 | CONV_2D 1×1, espansione | 48×48×48 | 18,017 | 19,19% |
| 4 | PAD | 49×49×48 | 14,628 | 15,58% |
| 5 | DEPTHWISE_CONV_2D, stride 2 | 24×24×48 | 9,462 | 10,08% |
| 6 | CONV_2D 1×1 | 24×24×8 | 1,470 | 1,57% |
| 7 | CONV_2D 1×1, espansione | 24×24×48 | 4,331 | 4,61% |
| 8 | DEPTHWISE_CONV_2D | 24×24×48 | 7,713 | 8,22% |
| 9 | CONV_2D 1×1 | 24×24×8 | 1,402 | 1,49% |
| 10 | ADD residuo | 24×24×8 | 0,929 | 0,99% |

Il PAD trasforma 48×48×48 in 49×49×48: copia 110.592 byte di input in
un'uscita da 115.248 byte e aggiunge 4.656 valori di bordo. Il percorso INT8
di `PadImageStyle` nel componente locale richiama `PadImpl`, che visita ogni
elemento e controlla i limiti delle dimensioni con cicli annidati. Non passa
da ESP-NN. Il valore di padding deve rispettare lo zero point quantizzato;
non va sostituito automaticamente con il byte zero.

La profilazione non separa ancora i tempi di calcolo dagli stalli della PSRAM.
Una prova mirata potrebbe confrontare il PAD attuale con copia per righe e
riempimento dei bordi, verificando tutti i byte e l'uscita del prefisso.
Un'altra prova distinta riguarda la collocazione dei buffer in RAM interna.
Nessuna di queste ottimizzazioni è implementata o misurata qui.

## Correttezza e confronto tra backend

Tutte le esecuzioni normali e profilate, warmup inclusi, confrontano
integralmente i 4.608 byte dell'output con il riferimento sul dispositivo:
**nessuna differenza**. Le tre attivazioni canoniche sono inoltre identiche
byte per byte a quelle archiviate dal precedente firmware ESP32 HTTP v2.
Input sul PC e sulla scheda identici; modello verificato tramite SHA-256.

Il controllo aggiuntivo del prefisso TFLite sul PC **non è bit-exact** con
il backend ESP-NN già usato prima della profilazione:

| Input | Elementi diversi su 4.608 | Massimo scarto INT8 | Scarto assoluto medio |
|---:|---:|---:|---:|
| 48 | 674 | 4 | 0,15885 |
| 96 | 680 | 4 | 0,16189 |
| 145 | 587 | 4 | 0,13976 |

Queste differenze non sono introdotte dal profiler: il confronto con le
attivazioni del precedente run ESP32 è esatto. La loro causa numerica non è
isolata; non sono una nuova misura di accuratezza né prova che siano innocue
per qualsiasi predizione. Il precedente replay del suffisso verifica il
suffisso su attivazioni ricevute e non implica equivalenza fra prefissi PC
ed ESP32.

Il primo audit richiedeva anche l'uguaglianza integrale al PC ed è fallito;
il suo log è conservato come `strict-pc-audit.log`. L'audit successivo pubblica
esplicitamente le differenze e verifica la continuità con il backend ESP32
precedente. Non presenta il confronto PC come superato.

## Ripristino e artefatti

Backup integrale di 8 MiB verificato prima del flash; firmware sperimentale
installato e verificato. A fine prova **flash originale ripristinata e
verificata integralmente prima del boot**, avvio originale confermato. Nessun
firmware sperimentale lasciato sulla scheda. Nessun server o inoltro di rete
avviato per questa prova.

Cinque test dell'analizzatore verificano completezza, campioni duplicati,
attribuzione dei tempi e differenze nelle attivazioni. Build firmware e
acquisizione hardware riuscite. Nessun commit o push.

[Audit e statistiche](summary.json) · [operatori CSV](operators.csv) ·
[mappa del modello e tensori](model-map.json) · [procedura](../README.md) ·
[firmware del profiler](../idf/src/main.cpp).

Run locale ignorato:
`experiments/esp32_layer_profile/results/2026-11-10-B-01/`.
Contiene backup, binari usati, snapshot/hash dei sorgenti e dei componenti,
configurazione SDK, log seriale, eventi e audit. La revisione dell'analizzatore
successiva al controllo PC è conservata separatamente in
`post-run-audit-sources/`; lo snapshot iniziale resta invariato.
