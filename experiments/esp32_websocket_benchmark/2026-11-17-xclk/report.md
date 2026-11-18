# XCLK della camera: effetto sulla rete riprodotto sulla B

Campagna del 17 novembre 2026 completata: **tre avvii indipendenti e 1.500 ping**.
Il risultato identifica come fattore determinante, nelle condizioni provate,
il clock XCLK instradato verso il sensore. Spegnerlo ripristina le risposte di rete;
riaccenderlo riproduce il degrado. Non è una diagnosi del meccanismo fisico:
interferenza e variazione del carico elettrico non sono distinte da questa prova.

| Condizione | Risposte entro 1.000 ms | Senza risposta entro il timeout |
|---|---:|---:|
| Wi-Fi prima della camera | 300/300 | 0 |
| Camera inizializzata, acquisizione ferma, XCLK ON | 82/600 | 518 |
| Stessi buffer trattenuti, XCLK OFF | 600/600 | 0 |

Ogni avvio usa il medesimo binario e la sequenza baseline → ON → OFF → ON → OFF,
con 50 ping al gateway e 50 al laptop per fase. Tutte le coppie soddisfano i
criteri preregistrati per entrambe le destinazioni. Le 12 commutazioni hanno
routing GPIO e latch verificati; RAM libera immediatamente prima/dopo identica
in tutte e 12, nessun buffer liberato. Minimi interni per avvio:
57.519 / 55.895 / 57.439 B, sopra la riserva di 32.768 B. Sentinelle e heap integri,
35 confronti esatti del prefisso per avvio, nessuna disconnessione Wi-Fi misurata.

## Cosa spiega e cosa resta da validare

Il precedente `cam_stop()` ferma acquisizione e interrupt VSYNC ma lascia XCLK
attivo; per questo il controllo con acquisizione sospesa non risolveva il guasto.
Qui GPIO15 viene scollegato da `CAM_CLK_IDX` e portato basso per OFF, quindi
ricollegato per ON, senza cambiare divisore 16 MHz, memoria, Wi-Fi, porta o cavo.
Il routing è letto dai registri: non è stata misurata la forma d'onda con un
oscilloscopio. L'ipotesi nasce dalla lettura del driver congelato e dalla
[segnalazione esp32-camera #869](https://github.com/espressif/esp32-camera/issues/869),
ma la conclusione sulla B deriva dalle misure locali sopra riportate.

Questo risultato localizza un fattore del collasso di rete, coerente con i 408
precedenti durante la ricezione del corpo HTTP. La campagna attuale usa ICMP:
**non dimostra ancora HTTP/WS stabili con clock gestito nel ciclo camera**.
Non acquisisce frame camera nelle fasi ON/OFF e non misura prestazioni comparative.

Passo successivo: validare separatamente acquisizione con XCLK acceso e invio con
XCLK spento, conservando il framebuffer e verificando riavvio del sensore,
freschezza/integrità dei frame, risultati numerici e ciclo completo. Non fissare
un numero di frame da scartare sulla base di altre risoluzioni/schede. Client
operativo e server invariati; nessuna promozione WebSocket e nessun commit/push.

## Implementazione, test e ripristino

Aggiunti comando seriale `x`, `--xclk-diagnostic` e analizzatore dedicato. Il runner
ricompila e acquisisce tre boot, con backup completo verificato prima di scrivere
e ripristino in `finally`. Le opzioni diagnostiche sono escluse dalla campagna
ordinaria. Due sessioni ICMP e memoria per i risultati sono allocate prima della
baseline e riutilizzate; timeout ed errori locali di invio sono conservati.

Build riuscita, 12 test analisi/ripristino superati, selezione `x` e rifiuto delle
combinazioni CLI incompatibili verificati con seriale simulata. Prima pubblicazione
eseguita solo dopo audit dei digest di snapshot, firmware e backup completo.
Flash originale degli 8 MiB ripristinata e verificata; boot originale confermato.
B scollegabile, nessun server o monitor seriale del banco aperto.

[Dati per fase e avvio](summary.json), [verifica e provenienza](verification.json).
Log, firmware e backup privati restano in `../results/LAPTOP_B_XCLK_01/`, ignorati
da Git; nessuna credenziale nei file pubblici.

# Diagnostica XCLK della camera

Esito: **xclk_effect_reproduced**. Flash originale ripristinata e boot verificato.

| Avvio | Fase | Destinazione | Risposte | p50 ms | p95 ms |
|---|---|---|---:|---:|---:|
| 1 | baseline | gateway | 50/50 | 1.0 | 7.549999999999997 |
| 1 | baseline | laptop | 50/50 | 8.0 | 112.04999999999997 |
| 1 | on_1 | gateway | 0/50 | — | — |
| 1 | on_1 | laptop | 0/50 | — | — |
| 1 | off_1 | gateway | 50/50 | 1.0 | 4.549999999999997 |
| 1 | off_1 | laptop | 50/50 | 8.5 | 105.59999999999997 |
| 1 | on_2 | gateway | 3/50 | 906.0 | 933.9 |
| 1 | on_2 | laptop | 5/50 | 253.0 | 442.0 |
| 1 | off_2 | gateway | 50/50 | 1.0 | 10.649999999999991 |
| 1 | off_2 | laptop | 50/50 | 8.0 | 102.1 |
| 2 | baseline | gateway | 50/50 | 1.0 | 7.0 |
| 2 | baseline | laptop | 50/50 | 8.0 | 109.29999999999998 |
| 2 | on_1 | gateway | 18/50 | 564.5 | 906.8499999999999 |
| 2 | on_1 | laptop | 27/50 | 354.0 | 766.9 |
| 2 | off_1 | gateway | 50/50 | 1.0 | 7.199999999999989 |
| 2 | off_1 | laptop | 50/50 | 6.5 | 87.24999999999996 |
| 2 | on_2 | gateway | 7/50 | 365.0 | 892.4 |
| 2 | on_2 | laptop | 0/50 | — | — |
| 2 | off_2 | gateway | 50/50 | 1.0 | 9.649999999999991 |
| 2 | off_2 | laptop | 50/50 | 5.0 | 82.39999999999998 |
| 3 | baseline | gateway | 50/50 | 1.0 | 10.649999999999991 |
| 3 | baseline | laptop | 50/50 | 7.5 | 98.29999999999998 |
| 3 | on_1 | gateway | 17/50 | 50.0 | 867.5999999999999 |
| 3 | on_1 | laptop | 2/50 | 467.0 | 877.4 |
| 3 | off_1 | gateway | 50/50 | 1.0 | 5.0 |
| 3 | off_1 | laptop | 50/50 | 7.0 | 93.14999999999996 |
| 3 | on_2 | gateway | 0/50 | — | — |
| 3 | on_2 | laptop | 3/50 | 559.0 | 886.5999999999999 |
| 3 | off_2 | gateway | 50/50 | 7.0 | 54.099999999999994 |
| 3 | off_2 | laptop | 50/50 | 33.0 | 141.29999999999998 |

Criterio prefissato: tre avvii completi, due recuperi per destinazione/avvio. Baseline e fasi OFF almeno 49/50 risposte; p95 OFF entro max(100 ms, due volte il p95 baseline). Ogni fase ON deve perdere almeno 10 punti percentuali in più della fase OFF abbinata, oppure avere p50 almeno max(20 ms, tre volte max(1 ms, p50 OFF)).

Il routing GPIO è verificato via registri, senza misura con oscilloscopio. Anche un effetto riprodotto non distingue interferenza elettromagnetica e alimentazione, né dimostra stabilità del ciclo camera o vantaggi WebSocket. Nessuna promozione operativa.
