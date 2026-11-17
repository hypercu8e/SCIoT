# Buffer a strisce ESP-NN — risultati

Variante selezionata: **3 righe**. 5.400 inferenze misurate, output esatti e ripristino verificato.

| Righe | Memoria | Picco byte | p50 ms | p95 ms |
|---|---|---:|---:|---:|
| 17 | psram | 178688 | 82.764 | 82.775 |
| 17 | internal | 178688 | 62.244 | 62.257 |
| 3 | psram | 145760 | 77.776 | 77.790 |
| 3 | internal | 145760 | 62.432 | 62.445 |
| 5 | psram | 150464 | 78.386 | 78.397 |
| 5 | internal | 150464 | 62.326 | 62.339 |
| 7 | psram | 155168 | 79.279 | 79.288 |
| 7 | internal | 155168 | 62.290 | 62.303 |
| 9 | psram | 159872 | 80.347 | 80.358 |
| 9 | internal | 159872 | 62.272 | 62.285 |

Mediane dei percentili di tre round. Limite preliminare: 161.323 byte; guardie, correttezza e tempi controllati. Una scheda, input fissi, senza camera/Wi-Fi/HTTP. La capienza del client completo e il suo ciclo restano da misurare.

## Interpretazione e prossimo passo

Con **3 righe** il picco scende da 178.688 a **145.760 byte**: **32.928 byte
liberati (−18,4%)** e 15.563 byte sotto il budget preliminare di 161.323.
Il p50 in RAM interna passa da 62,244 a **62,432 ms**: +0,188 ms (+0,30%).
Il p95 passa da 62,257 a 62,445 ms. Tutte le varianti rispettano il vincolo
+5% in ogni round; i tempi sono entro l'1% dal più rapido, quindi la regola
fissata prima della misura sceglie quella con meno memoria.

La depthwise interessata passa da 4,686 a 4,874 ms in RAM interna; gli altri
operatori rimangono pressoché invariati. In PSRAM il buffer più piccolo
riduce invece `Invoke()` da 82,764 a 77,776 ms (−6,0%): risultato osservato,
senza attribuirne qui la causa a uno specifico effetto della cache.
[Tempi per operatore](operators.csv).

Con la configurazione selezionata, PSRAM → RAM interna passa da 77,776 a
62,432 ms (−19,7%). È un confronto del solo prefisso, senza acquisizione,
conversione LUT, rete e suffisso; non rappresenta il guadagno del ciclo completo.

Correttezza: 35 input confrontati per ciascuna variante/memoria, più tutti
i warmup e i campioni; zero differenze e sentinelle integre. I tre canonici
coincidono anche con il firmware ESP32 precedente. Nessuna nuova misura di
accuratezza contro annotazioni o consumo energetico.

**Esito: requisito preliminare di memoria e tempi superato.** Il prossimo
passo è verificare il blocco interno contiguo disponibile nel client con
camera/Wi-Fi attivi e la riserva residua. Questa campagna mantiene un blocco
fisico da 240 KiB per la comparabilità degli indirizzi: la capacità di allocare
145.760 byte nel client operativo non è ancora dimostrata.

## Ripristino e riproducibilità

Backup integrale degli 8 MiB verificato contro la flash attuale prima di
installare il firmware sperimentale. Flash originale ripristinata, digest
verificato prima del boot e avvio originale confermato. Nessun watchdog,
panic o brownout. Nessun server o inoltro ADB avviato.

Dati grezzi, backup e snapshot: `../results/2026-11-16-B-01/` (ignorati).
[Verifica e hash](verification.json), [riepilogo](summary.json),
[tabella misure](measurements.csv). Il runner ignora le cache Python nel
controllo dei componenti, mantenendo la verifica di tutti i sorgenti congelati.
L'audit verifica gli snapshot dei sorgenti e i binari archiviati, consentendo
aggiornamenti successivi alla documentazione. **12 test analizzatore superati.**
Nessuna integrazione nel client o modifica ai suoi componenti.
