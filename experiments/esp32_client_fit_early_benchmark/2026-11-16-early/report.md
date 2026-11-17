# Capienza con camera e Wi-Fi — risultati

Ordine di allocazione: **early**.

**Criteri superati in tre avvii indipendenti.** Arena interna effettiva: 145.760 byte più 64 byte di sentinelle; 3.000 frame camera.

| Avvio | Blocco contiguo prima (B) | Minimo libero (B) | Invoke p50/p95 (ms) |
|---|---:|---:|---:|
| 1 | 208896 | 70347 | 63.202 / 64.123 |
| 2 | 208896 | 70155 | 63.209 / 64.159 |
| 3 | 208896 | 70263 | 63.200 / 64.083 |

Confronti numerici e sentinelle superati, Wi-Fi connesso, nessuna disconnessione nella misura. Flash originale ripristinata e boot confermato.

Questa verifica usa LUT, buffer applicativi, camera e Wi-Fi, ma non richieste HTTP o socket attivi: la capienza durante trasmissione e il ciclo del servizio completo restano da misurare. Nessuna modifica al client operativo.

## Confronto con l'allocazione tardiva

La [prova precedente](../2026-11-16/report.md) aveva 219.755 byte interni
liberi, ma il massimo blocco contiguo era di 124.928 byte: l'allocazione di
145.824 byte falliva. In questa variante il blocco viene riservato all'inizio,
quando il massimo contiguo è di 208.896 byte; camera e Wi-Fi riescono poi ad
avviarsi mantenendo l'arena occupata.

La riserva richiesta era di 32.768 byte: il minimo peggiore osservato,
**70.155 byte**, la supera di 37.387 byte. Il monitor del minimo locale copre
anche l'avvio dei servizi e la generazione dei riferimenti in PSRAM.
Durante la fase del candidato non si sono verificate disconnessioni Wi-Fi;
le eventuali disconnessioni di associazione iniziale sono conservate nei log
ed escluse da quel conteggio. Il maggiore blocco residuo a fine avvio era
31.744 byte: il margine totale non equivale a un singolo blocco della stessa
capacità.

## Correttezza e limiti

Per ciascun avvio: 35 confronti integrali con il modello originale su ESP32,
poi 1.000 frame camera e 10 controlli dei tre canonici. Zero differenze,
chiamate ESP-NN attese, sentinelle e heap integri. I canonici del riferimento
coincidono anche con l'archivio del firmware ESP32 precedente.

Il prefisso ha p50 circa 63,2 ms con servizi attivi. I tempi di acquisizione
sono separati e questi risultati non sono FPS del servizio completo.
Non viene dimostrato un guadagno HTTP o energetico né una nuova accuratezza.

**Conclusione operativa:** il problema del blocco contiguo è superato con
questo ordine di inizializzazione nella configurazione provata. Il passo
successivo proposto è una variante sperimentale del percorso HTTP che usi
lo stesso ordine, verificando anche i picchi di memoria durante le richieste.
Nessuna integrazione automatica nel client operativo.

## Provenienza e ripristino

Backup di 8 MiB verificato prima dell'installazione; flash originale
ripristinata e verificata prima del boot, applicazione originale confermata.
Nessun watchdog, panic o brownout. Nessun server HTTP o inoltro ADB avviato.

[Verifica e hash](verification.json), [configurazione di build](configuration.json),
[riepilogo](summary.json), [misure](measurements.csv), [15 test analizzatore](tests.log).
Dati grezzi, firmware e snapshot in `../results/2026-11-16-B-02-early/`
(ignorati da Git). Credenziali conservate esclusivamente nel file locale
ignorato e nei binari privati, senza pubblicarle nel report o negli snapshot
sorgenti. La prova tardiva e i suoi dati sono conservati separatamente.
