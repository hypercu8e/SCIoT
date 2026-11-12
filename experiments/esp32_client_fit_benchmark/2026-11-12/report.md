# Prova di capienza nel client — 12 novembre 2026

**Esito.** Il blocco di **152 KiB in RAM interna non entra** nel client così
com'è. Con il blocco tenuto, Wi-Fi e lwIP restano senza RAM interna: il
minimo libero scende a **22.751 e 11.831 byte** (soglia 32.768), il server
chiude molte richieste per corpo non arrivato in tempo (HTTP 408) e le due
fasi R non finiscono in 20 minuti (360 e 4 frame camera su 1.000). Le fasi N,
nello stesso ambiente, finiscono con 1.000 e 997 frame.

Per la regola fissata prima, l'esito formale è **problema dell'ambiente**: la
fase di controllo 3 ha avuto 3 risposte 408 su 1.060. Il criterio di margine
fallisce comunque in entrambe le fasi R, indipendentemente dalla rete, e la
distanza fra N e R è troppo grande per attribuirla all'ambiente. Prossimo
passo: liberare RAM interna spostando i buffer Wi-Fi/lwIP in PSRAM.

## Configurazione

Scheda B `24:ec:4a:0e:c3:14`, rete `FASTWEB` del laboratorio, server HTTP v2
sul PC (`audit_server.py`). Firmware: copia del client con la sola scelta
N/R all'avvio ([README](../README.md)). Quattro fasi N, R, N, R, ciascuna dopo
un riavvio: 60 input incorporati + 1.000 frame camera. Limite per fase 20
minuti. Run `results/2026-11-12-board-B-02` (non versionato, contiene il
firmware con le credenziali), audit in [summary.json](summary.json).

Il primo tentativo (`2026-11-12-board-B-aborted-runner-bug`) si è fermato per
un errore del runner nella stampa di avanzamento, prima di misurare; scheda
ripristinata e avvio originale confermato anche lì.

## Risultati per fase

| Fase | Incorporati | Camera | Risposte server | Min. libero interno | Blocco max (min.) | Ciclo camera p50 / p95 | Rete p50 |
|---|---:|---:|---|---:|---:|---:|---:|
| 1 N | 60 | 1.000 | 1.060 × 200 | 196.807 | 110.592 | 0,28 / 0,44 s | 65 ms |
| 2 R | 60 | 360 | 420 × 200, 48 × 408 | **22.751** | 31.744 | 1,56 / 4,56 s | 1,29 s |
| 3 N | 60 | 997 | 1.057 × 200, 3 × 408 | 193.363 | 112.640 | 0,28 / 0,43 s | 58 ms |
| 4 R | 60 | 4 | 64 × 200, 29 × 408, 2 × 410 | **11.831** | 31.744 | 8,7 / 17,0 s | 3,47 s |

- Inferenza p50 invariata (≈ 95 ms in tutte le fasi): la riserva non tocca
  l'inferenza, che resta in PSRAM.
- Nessuna disconnessione Wi-Fi, nessun panic, watchdog o riavvio.
- I 408 sono tutti `body_timeout`: la connessione si apre ma il corpo della
  richiesta non arriva entro il limite del server. I 2 × 410
  (`session_replaced`) sono la nuova registrazione dopo un errore.
- All'avvio con R: blocco contiguo più grande 208.896 prima della riserva,
  libero 146.571 e blocco più grande **53.248** dopo.

## Lettura

Il limite di 161.323 sottraeva 32 KB al minimo libero del 9 novembre, come se
il resto del client usasse sempre la stessa RAM interna. Non è così. Quando
la memoria scarseggia, lo stack di rete trattiene buffer per le ritrasmissioni
e ne chiede altri. Gli invii TCP rallentano, il ciclo si allunga e i buffer
restano occupati più a lungo. Il minimo reale (12–23 KB) è sotto la stima
(~38 KB).

La causa è la configurazione: con `SPIRAM_MALLOC_ALWAYSINTERNAL=16384` ogni
allocazione sotto i 16 KB, e quindi ogni buffer Wi-Fi e lwIP, va in RAM
interna. Inoltre `SPIRAM_TRY_ALLOCATE_WIFI_LWIP` è spento.

## Limiti

Una sola scheda e un solo ambiente di rete. 1.000 frame per fase. La riserva è
un blocco inerte, non un'arena TFLM usata: non misura la contesa sulla RAM
interna durante l'inferenza.

## Recupero

Backup di 8 MiB verificato, firmware originale riscritto e verificato prima
dell'avvio, avvio del client originale confermato (`sciot_esp32_client`).
