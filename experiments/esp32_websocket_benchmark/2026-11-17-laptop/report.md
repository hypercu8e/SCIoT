# Diagnostica laptop: HTTP / WebSocket, USB e camera — 17 novembre 2026

**Aggiornamento successivo:** [prova XCLK completata su tre avvii](../2026-11-17-xclk/report.md),
con degrado reversibile ON/OFF. Le sezioni seguenti conservano i controlli
precedenti su porte, cavi e memoria, prima di questa identificazione.

Cambiare porta USB e poi cavo, mantenendo lo stesso firmware, non ha risolto il guasto. Anche il client HTTP di riferimento,
ricompilato senza modifiche ai suoi sorgenti, completa 60 richieste senza camera
ma fallisce con HTTP 408 al quarto frame camera, dopo tre riusciti. Il problema
non è specifico del nuovo trasporto WebSocket; **la causa rimane non dimostrata**.
Nessuna porta è certificata affidabile con camera attiva da queste prove.

## Prove conservate

| Run | USB | Configurazione | Esito |
|---|---|---|---|
| `LAPTOP_B_HTTP_01` | `1-2` | HTTP persistente, camera attiva | Registrazione HTTP 408; zero inferenze |
| `LAPTOP_B_HTTP_OFF_01` | `1-2` | Stesso benchmark, camera non inizializzata | 1.100/1.100 richieste corrette |
| `LAPTOP_B_HTTP_ON_02` | `1-2` | Camera attiva | Registrazione 200; prima inferenza 408 |
| `LAPTOP_B_WS_01` | `1-2` | WS, camera attiva | Socket accettato; registrazione applicativa fallita |
| `LAPTOP_B_HTTP_USB1_01` | `1-1` | HTTP persistente, camera attiva | Registrazione HTTP 408 |
| `LAPTOP_B_HTTP_PSRAM_01` | `1-1` | Camera attiva, attivazioni in PSRAM | Connessione HTTP fallita; minimo interno rilevato 213.419 B |
| `LAPTOP_B_HTTP_PAUSED_01` | `1-1` | Camera inizializzata, acquisizione sospesa, buffer trattenuti | 111 risposte corrette, poi richiesta 111 (contatore da zero) in timeout |
| `LAPTOP_B_REFERENCE_01` | `1-1` | Client HTTP di riferimento, INT8 originale, connessioni close | 60/60 input incorporati e 3 frame camera riusciti; quarto frame HTTP 408 |
| `LAPTOP_B_HTTP_CABLE2_02` | `1-1` | Altro cavo confermato dall’utente, identico binario di USB1 | 53 richieste corrette; richiesta 53 (da zero) HTTP 408 `body_timeout` |

B: MAC `24:ec:4a:0e:c3:14`, seriale `/dev/ttyACM0`. Il cambio porta osservato è da
`pci-0000:63:00.3-usb-0:2:1.0` a `pci-0000:63:00.3-usb-0:1:1.0`.
Laptop su alimentazione esterna, profilo `balanced`; IP LAN invariato, server con
un worker e un thread di inferenza. Nessuna modifica ai timeout di protocollo.

## Confronti controllati e limiti

OFF, ON_02, WS e USB1 usano lo stesso binario SHA-256
`91fe0a8ed58084fdba22a5fbf5a96654bc782658764bb8925c29f2ad69e3103b`.
Il confronto tra le due porte e quello OFF/ON non cambiano contemporaneamente
firmware. Il primo run usa la revisione precedente alla diagnostica aggiunta;
i controlli PSRAM e acquisizione sospesa sono revisioni successive, con sorgenti,
binari e hash distinti conservati nei rispettivi snapshot. Non costituiscono
coppie di misure prestazionali sullo stesso binario.

OFF completa 100 richieste iniziali e 1.000 deterministiche misurate, tutte con
confronto integrale dei punteggi canonici; heap e sentinelle integri. Latenze
richiesta/risposta: p50 **18.651 ms**, p95 **150.669 ms**,
p99 **189.592 ms**. Sono dati senza camera, con coda di latenza visibile:
non misurano il ciclo camera né il vantaggio di WS.

Spostare le attivazioni in PSRAM, liberando oltre 145 KB interni, non ripristina
la connessione. Questo indebolisce l'ipotesi della sola quantità di RAM libera;
non esclude errori di buffer, DMA o altri difetti software.

Il comando diagnostico `p` chiama `cam_stop()` del driver congelato dopo la
validazione: disabilita interrupt VSYNC e acquisizione senza deinizializzare
camera o liberarne i buffer. Il clock del sensore non viene disabilitato.
RAM interna prima/dopo: **71,411/71,411 B**.
Controllo heap prima della rete superato; la prova fallisce comunque dopo 111
risposte corrette. Mediana delle risposte riuscite, warmup inclusi:
**620.372 ms**. Il segmento misurato
successivo ai 100 warmup resta incompleto: 11 risposte riuscite.

Il client di riferimento mantiene il frame camera acquisito durante inferenza
e HTTP, usa il prefisso INT8 originale, arena in PSRAM e connessioni close.
La sua memoria interna minima rilevata prima dei frame è **217.495 B**.
Le tre risposte camera riuscite richiedono **1061.880, 910.225, 3705.325 ms**,
poi arriva HTTP 408 sul quarto tentativo. Il test è fermato al primo errore,
prima dei 20 frame previsti. Sette disconnessioni Wi-Fi sono registrate durante
l'avvio, prima di `ready`; nessuna dopo `ready`. Il firmware di riferimento
compila con i sorgenti operativi invariati e la configurazione locale già valida
per il laptop; il suo binario è distinto dalla flash originale salvata dalla B.

HTTP 408 `body_timeout` localizza i fallimenti osservati nella ricezione del
corpo sul server, prima dell'inferenza del suffisso. Questo non distingue
alimentazione, cavo, interferenze/attività del sensore o software condiviso.
La sola forza del segnale e l'assenza di reset USB non escludono problemi radio
o elettrici. Non è stata acquisita una cattura TCP completa.

## Ripristino e ripresa

I **nove test diagnostici** e il tentativo interrotto escluso hanno backup verificato degli 8 MiB, ripristino
integrale con digest corrispondente e boot originale confermato. I digest dei
file di backup e dei firmware archiviati sono stati ricontrollati prima di
pubblicare questo riepilogo. Il primo backup è una lettura completa sul laptop;
i successivi usano un backup verificato della prova precedente come seme e
verificano nuovamente l'intera flash sulla B. Server e monitor del banco chiusi.
B scollegabile.

**Cambio cavo completato:** in `LAPTOP_B_HTTP_CABLE2_02` l'utente ha confermato
la sostituzione, il percorso USB è rimasto `1-1` e il binario coincide con USB1.
La registrazione riesce, ma la richiesta 53 fallisce dopo 53 risposte corrette:
ESP32 3.081.742 µs, server 408 `body_timeout` dopo 3.000.788 µs. Tutte le richieste
sono ancora nel warmup; zero frame camera misurati. Nessuna disconnessione Wi-Fi
registrata, RSSI −57 dBm, minimo interno rilevato 50.843 B. Non è uno smoke superato
né una misura prestazionale completa. Non basta attribuire il guasto alla porta
o al cavo sulla base delle prove finora disponibili.

**Indagine successiva:** tracciare ricezione del corpo HTTP e traffico TCP per
localizzare la consegna incompleta, e controllare clock sensore e percorso
camera/rete comune ai due firmware. Un eventuale hub con alimentatore proprio e
collegamento dati al laptop costituisce un distinto controllo dell'alimentazione;
non è stato provato. La causa resta aperta, senza attribuzioni automatiche a
firmware, Wi-Fi o USB.

Nessuno smoke con camera attiva è completo; i nove avvii WS/HTTP persistente/
HTTP close non sono stati eseguiti. Nessun vantaggio WS dimostrato e nessuna
promozione operativa.

## Provenienza e modifiche

[Dati derivati verificati](summary.json). Log, backup, firmware e snapshot
rimangono locali in `../results/`, ignorati da Git. Nessuna credenziale nei file
pubblici. I sorgenti pubblici congelati sono stati ripristinati verificandone gli
hash; SSID/password e header locali restano privati.

Il runner sperimentale accetta `--smoke-transport`, `--camera-off`,
`--activation-memory psram` e `--camera-paused`, con vincoli che impediscono i
controlli diagnostici nella campagna ordinaria. La cache PlatformIO usa il
percorso risolto, evitando alias di symlink. Firmware: telemetria RSSI/canale,
esito registrazione HTTP, controlli di posizione dell'arena e della camera.
I tre trasporti della campagna ordinaria restano con camera attiva e attivazioni
in RAM interna. Il launcher locale della prova di riferimento è conservato in
`results/reference_runner.py` e nello snapshot del relativo run.

Build sperimentali e riferimento riuscite, 27 test multiclient/socket e 5 test
analisi/ripristino superati; gli otto comandi seriali e i vincoli CLI diagnostici
verificati con seriale simulata. Nessuna modifica ai sorgenti del client
operativo o del server; nessun commit/push.

## Tentativo escluso dal confronto cavi

`LAPTOP_B_HTTP_CABLE2_01` è stato avviato prima della conferma del cambio cavo,
quindi interrotto esplicitamente. Non è una misura del secondo cavo e non
contribuisce alle conclusioni. Backup e ripristino integrale verificati;
boot originale confermato anche dopo questa interruzione. Per riprendere,
la conferma è stata poi ricevuta e la prova effettiva è conservata in `CABLE2_02`.
