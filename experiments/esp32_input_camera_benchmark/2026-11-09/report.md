# Input e acquisizione camera ESP32-S3-EYE — 9 novembre 2026

## Risultato pratico

**Conversione con LUT e rilascio anticipato del framebuffer migliorano la cadenza locale del prefisso, preservando la conversione RGB565 → INT8.** Su una scheda, senza HTTP, tre ripetizioni da 200 frame per variante: ciclo mediano circa 195 → 98 ms (−49.7%) e cadenza circa 5,00 → 9,62 attivazioni/s (+92.4%). L'età p95 del frame all'attivazione pronta resta vicina al riferimento: circa 197 contro 194 ms.

**Questo non dimostra il guadagno sulla predizione completa o sul servizio multi-client.** HTTP 408 è ricomparso anche nel firmware precedente già collaudato. Il confronto HTTP completo, la conferma con due schede e l'ora di stabilità della candidata non sono conclusi. Il vecchio esperimento riuscito non viene invalidato: queste nuove condizioni non ne riproducono le prestazioni di rete.

[Audit locale e statistiche di tutte le ripetizioni](local-audit.json) · [procedura e comandi](../README.md) · [catalogo dei filoni](../../../FILONI_OTTIMIZZAZIONE_SOFTWARE.md).

## Risultati locali validati

Una ESP32-S3-EYE, prefisso INT8 congelato, ESP-NN, split `block_2_add`, camera 96×96, XCLK 16 MHz, un framebuffer in PSRAM. Tre ripetizioni in ordini diversi, reset e 20 frame camera di warmup prima di ogni serie. Le righe riportano la mediana delle statistiche delle tre ripetizioni, non percentili aggregati di tutte le richieste. FPS misurati fra completamenti: comprendono logging e pause periodiche, escludono startup e warmup.

| Variante | Conversione p50 ms | Ciclo locale p50 ms | Ciclo locale p95 ms | Attivazioni/s | Età frame p95 ms |
|---|---:|---:|---:|---:|---:|
| Originale, buffer trattenuto | 47.174 | 195.009 | 195.880 | 5.002 | 194.004 |
| LUT, buffer trattenuto | 1.291 | 145.014 | 145.817 | 6.669 | 148.169 |
| Originale, rilascio anticipato | 47.644 | 144.130 | 145.023 | 6.671 | 283.154 |
| LUT, rilascio anticipato | 1.544 | 98.178 | 98.912 | 9.624 | 197.149 |

La conversione è calcolata come somma delle due fasi **per ogni frame**, poi aggregata. Non si ottiene sommando mediane indipendenti. Il ciclo parte prima di `fb_get` e termina dopo il prefisso e il packing. L'età parte dal timestamp di avvio acquisizione del driver; non è una misura precisa dell'esposizione. Il suffisso non viene eseguito: l'attivazione pronta non è ancora una predizione FOMO.

Il rilascio anticipato con conversione originale aumenta gli FPS ma produce frame più vecchi: circa 283 ms p95. La LUT con buffer trattenuto è l'opzione con minore età del frame, circa 148 ms p95. La combinazione LUT + rilascio anticipato è la candidata **locale** scelta dal criterio prestabilito: ciclo più veloce con età p95 non oltre il 5% sopra la baseline, memoria stabile nello screening e nessun errore.

### Grayscale nativo: esplorazione separata

Una sola serie da 200 frame: ciclo locale p50 **97.130 ms**, cadenza **9.737 attivazioni/s**, età p95 **196.006 ms**. Questa conversione cambia il contenuto d'ingresso; nessuna accuratezza su scene annotate è stata valutata. È esclusa dalla selezione e non va adottata sulla sola base dei tempi.

## Correttezza, memoria e limiti

- Tutti i 65.536 colori RGB565 confrontati sulla ESP32: **zero differenze INT8** contro la formula originale.
- **100 frame reali**: confronto integrale di input e attivazioni, anche ripristinando lo stesso input e inferendo durante il riempimento del frame successivo.
- **2.600 frame camera misurati**: 2.400 RGB565 e 200 grayscale, più 780 campioni incorporati; tutti i campioni attesi presenti.
- Zero avvisi watchdog, zero eventi seriali corrotti e zero inferenze sul server nella diagnostica locale. I byte di richiesta/risposta e i tempi HTTP sono esplicitamente zero.
- LUT RGB565: **64 KiB aggiuntivi in PSRAM**; inizializzazione mediana **327.261 ms**, esclusa dai cicli e applicata a tutte le varianti per confronto a memoria riservata costante. I primi/ultimi campioni di heap non mostrano perdite oltre la tolleranza di 4 KiB; è uno screening breve, non prova di assenza di leak o di picco RAM.
- Un tick di pausa ogni dieci frame permette al task idle di avanzare; è esterno al timer del ciclo e incluso nella cadenza effettiva. Il watchdog rimane attivo.
- Cinque test dell'analizzatore e build ESP-IDF 5.4.0 superati. Nessuna misura di energia o accuratezza annotata.

Firmware della prova locale: `362747b65bb93b908ff4421734b8d9144bfbca2b186fab08191cdb4fe0c2e5ee`. Binario, sorgenti, hash dei componenti, log e backup integrali sono conservati nel run locale ignorato `results/2026-11-09-local-yield/`. L'audit registra anche l'hash del proprio verificatore. La flash originale di A è stata ripristinata e verificata integralmente prima del boot, con avvio originale confermato. B è rimasta intatta nella prova locale ed è stata riavviata con il firmware originale confermato.

## Tentativi HTTP e controllo del guasto

1. **Primo tentativo:** equivalenza su tutti i colori e 100 frame riuscita; HTTP lento e 408 dopo 25 richieste completate, prima delle misure camera. [Audit](attempt1-audit.json).
2. **Wi-Fi del Pixel verso il router spento e reset dopo validazione:** riferimento da 1.000 frame completato, p50 ciclo 361,881 ms e HTTP 146,369 ms. LUT interrotta dopo 69 frame camera: conversione p50 1,322 + 0,002 ms, ma HTTP 390,975 ms e ciclo 554,293 ms. Sono campioni parziali con condizioni di rete diverse; non dimostrano un miglioramento del ciclo. [Statistiche](attempt2-partial.json), [audit di 1.229 risposte](attempt2-audit.json).
3. **Vecchio firmware di controllo:** stesso guasto HTTP 408 dopo 60 input incorporati e 12 frame camera su A. Tutte le 72 risposte riuscite hanno punteggi identici al replay. Il problema si riproduce senza LUT o nuova gestione camera; la causa precisa non è isolata. Entrambe le flash originali ripristinate e verificate, con boot confermato. [Audit](legacy-control-audit.json).

Il trasporto provato resta hotspot Pixel → USB/ADB reverse → server PC. Il 408 indica scadenza di ricezione del corpo lato server; non dimostra quale componente del percorso abbia causato il ritardo. I log integrali e i tentativi falliti sono conservati separatamente.

## Diagnostica locale iniziale invalidata

Un primo run senza HTTP aveva avvisi watchdog e una riga sample corrotta: 199 righe per 200 frame completati nella seconda serie LUT early. L'analizzatore l'ha rifiutata; il run è stato interrotto e A ripristinata con verifica e boot. Le indicazioni preliminari non sono confluite nei risultati sopra. Il run valido aggiunge pause periodiche e controllo esplicito del watchdog.

## Uso e lavoro restante

Le varianti sono implementate nel progetto isolato, selezionabili via seriale; la baseline del client multi-client è conservata. La conversione LUT ha ora verifica numerica e misure locali; il rilascio anticipato ha un compromesso di cadenza/età quantificato. Prima di promuovere la candidata al client operativo servono rete stabile, ripetizione del confronto HTTP, due schede e prova di un'ora. Il grayscale richiede inoltre una valutazione di qualità su scene annotate.
