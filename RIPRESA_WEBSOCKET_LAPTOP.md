# Ripresa WebSocket sul laptop — 17 novembre 2026

## Confronto completato sulla B — 18 novembre 2026

Nove avvii con gestione XCLK, **18.900/18.900 richieste**, 9.000 frame reali,
zero timeout e disconnessioni durante la misura. Mediana del ciclo camera
710 ms con HTTP persistente, 711 ms con WebSocket e 754 ms con HTTP
con chiusura. HTTP persistente conserva 12.188 byte di RAM interna in più
al minimo rispetto a WebSocket. È la scelta per questa configurazione.
[Report per trasporto e per avvio](experiments/esp32_websocket_benchmark/2026-11-18-comparison/report.md).

Flash originale ripristinata e verificata su tutti gli 8 MiB, boot
confermato e server chiuso. B scollegabile.

## Prove iniziali — HTTP e WebSocket superano lo smoke sulla B

Con `--gate-camera` ciascun trasporto ha completato **2.100/2.100 richieste**,
di cui **1.000 frame reali**, senza timeout o disconnessioni durante la misura.
Stesso binario, stessa B e stessa porta USB. Il clock XCLK è acceso durante
l'acquisizione e spento durante inferenza e invio. I controlli su timestamp,
dimensioni, formato, hash del buffer e routing GPIO15 sono passati per tutti
i frame. Il report contiene latenze e minimi di RAM per entrambi i trasporti.
[Report delle prove](experiments/esp32_websocket_benchmark/2026-11-17-gated-camera/report.md).

Flash originale ripristinata con digest degli 8 MiB e boot verificati dopo
entrambi gli avvii. B scollegabile, server e seriale chiusi. La campagna successiva di nove avvii è riportata sopra.

## Diagnostica precedente — effetto XCLK riprodotto sulla B

[Report XCLK](experiments/esp32_websocket_benchmark/2026-11-17-xclk/report.md):
**tre avvii indipendenti, 1.500 ping; baseline 300/300, XCLK ON 82/600,
XCLK OFF 600/600**. Acquisizione ferma e buffer camera trattenuti; le 12
commutazioni GPIO15 hanno routing verificato e nessuna variazione immediata
della RAM libera. Tutte le coppie ON/OFF soddisfano i criteri preregistrati per
router e laptop. Minimo interno 55.895 B, heap/sentinelle integri, zero
disconnessioni Wi-Fi. Non è una distinzione fra interferenza e alimentazione.

Il comando `cam_stop()` non spegne XCLK nel driver S3 congelato. La diagnostica
`x` lo scollega invece da `CAM_CLK_IDX`, imposta GPIO15 basso e ripristina il
routing per riaccenderlo, mantenendo invariati clock-rate, buffer e rete.

**Stato hardware:** B su USB `pci-0000:63:00.3-usb-0:1:1.0`, con secondo cavo
confermato dall'utente. Firmware originale ripristinato, digest di tutti gli
8 MiB e boot verificati; B scollegabile. Nessun server o monitor seriale attivo.

**Implementazione disponibile:** `run.py --xclk-diagnostic --run NUOVA_DIRECTORY`
seleziona tre boot `xxx`; non richiede server HTTP. Analisi con
`analyze_xclk.py RUN --output NUOVA_DIRECTORY_REPORT`. Credenziali solo nell'header
locale ignorato. Nessuna modifica al client operativo o promozione WS.

La prova successiva del ciclo con clock gestito è riportata sopra.

[Controlli precedenti su porte, cavi, memoria e client di riferimento](experiments/esp32_websocket_benchmark/2026-11-17-laptop/report.md).
Il tentativo prematuro `CABLE2_01` resta escluso; `CABLE2_02` è la prova valida
con secondo cavo (53 richieste corrette, poi 408). Log, firmware e backup restano
in `results/`, ignorati da Git. Nessun commit/push.

## Obiettivo e limite del confronto

Usare **soltanto B sulla porta USB affidabile**, vicino al router, per diagnosticare
il timeout WebSocket e poi confrontare HTTP close, HTTP persistente e WebSocket.
Una sola ESP32 basta: i tre trasporti si provano a turno sulla stessa scheda,
con modello, input, camera, frequenze e rete invariati. Questo verifica latenza,
traffico, correttezza e RAM per un dispositivo; due schede servono per verificare
la contesa tra dispositivi fisici. I client PC simulati rimangono una verifica
separata del server. Non usare la porta USB sospetta per questo confronto.

Le precedenti prove HTTP sul laptop hanno mostrato guasti che seguivano cavo/porta USB ([cronologia](RIPRESA_MULTICLIENT_LAPTOP.md)); questo è un motivo ulteriore per mantenere fissi cavo, alimentazione e porta durante il confronto, senza attribuire automaticamente i timeout al Wi-Fi.

I test WS sul fisso si sono interrotti dopo 78 e 97 richieste riuscite, prima
delle misure complete. **Non è dimostrato che WS sia più veloce o più lento di
HTTP. Non è dimostrato che la causa sia il Wi-Fi.** Il maggiore buffer non ha
risolto il timeout. [Risultati](experiments/esp32_websocket_benchmark/2026-11-16/README.md).
La revisione successiva aggiunge confronti integrali dei punteggi canonici e
backoff. È stata ora provata sul laptop con la diagnostica riportata sopra:
non ha completato lo smoke con camera attiva.

B: MAC `24:ec:4a:0e:c3:14`, collegamento Linux atteso
`/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_24:EC:4A:0E:C3:14-if00`.
Flash originale ripristinata, digest e boot verificati dopo entrambi i tentativi.
Il numero ttyACM può cambiare. Fare un **nuovo backup sul laptop**; non serve
trasferire la flash del fisso né usare `--seed`. Nessun test hardware in corso.

## Dopo il pull

1. Sul clone del laptop controllare `git status`, preservare le eventuali
   modifiche locali, quindi `git pull --ff-only`. Non copiare ambienti virtuali.
2. Ripristinare gli artefatti pubblici congelati, con verifica degli hash:

   ```sh
   python3 experiments/multiclient_hardware/restore_runtime.py
   python3 experiments/esp32_websocket_benchmark/restore_components.py
   ```

   Il secondo archivio contiene soltanto 877 sorgenti pubblici TFLM/ESP-NN,
   camera e JPEG, nelle revisioni usate sul fisso. I due script verificano il
   contenuto prima di scrivere e rifiutano di sovrascrivere file locali diversi.
   WebSocket Espressif 1.8.0 è già in `vendor/`. Sono esclusi da Git credenziali,
   firmware compilati, backup, ambienti, cache PlatformIO e risultati grezzi.
3. Riutilizzare `.venv` se funzionante (Python 3.11, TensorFlow 2.15 e NumPy <2).
   In assenza dell'ambiente, dalla radice:

   ```sh
   python3.11 -m venv .venv
   .venv/bin/python -m pip install -e .
   python3 -m venv experiments/esp32_deadzone_benchmark/results/build-tools
   experiments/esp32_deadzone_benchmark/results/build-tools/bin/python -m pip install pyserial esptool==5.1.0 platformio==6.1.18
   ```

   Il runner usa questi percorsi esatti; il primo download della toolchain
   PlatformIO richiede rete. CPU/PSRAM 240/80 MHz, ESP-IDF 5.4.0 con piattaforma
   espressif32 6.10.0. La sandbox può impedire thread/socket: eseguire i test di
   concorrenza e il server nel normale ambiente locale quando necessario.
4. Preparare i componenti privati e il modello:

   ```sh
   .venv/bin/python experiments/esp32_websocket_benchmark/prepare.py
   ```

   Crea `include/network.local.h` dall'esempio se manca. Modificare **soltanto**
   `experiments/esp32_websocket_benchmark/include/network.local.h`: SSID/password
   della rete 2,4 GHz e `SERVER_BASE_URL` con l'**IP LAN attuale del laptop**, ad
   esempio `http://192.168.1.100:8000`. Non riutilizzare l'IP del fisso. Il file
   rimane ignorato da Git; non incollare credenziali nei report o nella chat.
   Il laptop può essere in Wi-Fi sulla stessa LAN o in Ethernet. La B deve poter
   raggiungere la porta 8000; non occorrono Pixel, ADB o una seconda ESP32.
5. Verificare i test prima di accedere alla scheda:

   ```sh
   PYTHONPATH=src .venv/bin/python -m unittest discover -s tests/multiclient -v
   .venv/bin/python -m unittest discover -s experiments/esp32_websocket_benchmark -p 'test_*.py' -v
   ```

   I test dell'analizzatore usano fixture pubbliche sintetiche e non dipendono
   dai backup o log privati del fisso.

## Prova iniziale con una sola scheda

Avviare in un terminale il server condiviso, dalla radice:

```sh
PYTHONPATH=src .venv/bin/python -m server.multiclient.run --model-registry experiments/esp32_websocket_benchmark/artifacts/model-registry.json --output experiments/esp32_websocket_benchmark/results/LAPTOP_SERVER_01
```

In un altro terminale, dopo avere identificato B sulla porta affidabile:

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_websocket_benchmark/run.py --smoke --gate-camera --run experiments/esp32_websocket_benchmark/results/NUOVO_WS_GATED_RUN
```

Le directory devono essere nuove. Il runner ricompila con la configurazione
locale, crea e verifica il backup completo prima dell'installazione, esegue un
avvio WS e ripristina in `finally`, con verifica degli 8 MiB e del boot originale.
Non scollegare finché il ripristino non è confermato. La porta non deve essere
occupata da monitor seriali. Il limite del singolo avvio è 30 minuti; non è un
invito ad aumentare i timeout del protocollo. Il primo scambio fallito interrompe
la prova senza reinvio automatico.

Se il test fallisce, conservare tutto e analizzare:

```sh
.venv/bin/python experiments/esp32_websocket_benchmark/analyze.py experiments/esp32_websocket_benchmark/results/LAPTOP_B_WS_01 --output experiments/esp32_websocket_benchmark/results/LAPTOP_B_WS_01/report
```

Confrontare gli eventi seriali e server; eventualmente aggiungere un relay TCP
locale per individuare dove si interrompe il messaggio. Il segnale più forte sul
laptop è una condizione da registrare, non una spiegazione già dimostrata. Per
isolare il solo effetto della posizione ripetere anche nella posizione iniziale,
con lo stesso laptop/cavo/porta/rete, senza cambiare contemporaneamente firmware.

## Confronto dopo il superamento dello smoke

Il runner ordinario usa **sempre la sola B**, con nove avvii indipendenti e ordine
ruotato: WS/HTTP persistente/HTTP close, HTTP persistente/HTTP close/WS,
HTTP close/WS/HTTP persistente. Nessun requisito di collegare A.

```sh
experiments/esp32_deadzone_benchmark/results/build-tools/bin/python experiments/esp32_websocket_benchmark/run.py --gate-camera --run experiments/esp32_websocket_benchmark/results/LAPTOP_B_COMPARE_01
```

Ogni avvio: 35 confronti del prefisso, 100 richieste iniziali, 1.000 richieste
deterministiche misurate e 1.000 frame camera. Il server e la posizione rimangono
uguali. Tenere fissa l'alimentazione del laptop e registrare modalità energetica
e rete; non confrontare direttamente le vecchie latenze del fisso con quelle
del laptop, perché cambia anche il computer che esegue il suffisso.

Il confronto principale è **WS contro HTTP persistente**; entrambi riutilizzano
la connessione. Conservare ritardi, rifiuti, timeout e tentativi incompleti.
Il report attuale dell'analizzatore riassume le latenze richiesta/risposta e
verifica il ripristino, ma **non abilita automaticamente la promozione**: restano
da completare analisi del ciclo completo, confronto per round, stack/memoria,
20 riconnessioni, 10 riavvii server e traffico. Un test con una sola ESP32 non
dimostra le prestazioni di due dispositivi in contemporanea.

Per riprendere con l'agente sul laptop:

> Leggi RIPRESA_WEBSOCKET_LAPTOP.md. Usa solo B sulla porta USB affidabile.
> Ripristina i sorgenti pubblici congelati, verifica configurazione LAN e nuovi
> backup, poi diagnostica il timeout WS vicino al router. Confronta HTTP close,
> HTTP persistente e WS sulla stessa B solo dopo uno smoke stabile. Conserva
> ogni tentativo e verifica sempre il ripristino del firmware originale.

## Coesistenza con il lavoro già sul remoto

Sono stati integrati in fast-forward i sette commit fino a `7d9a797`, conservando gli esperimenti `esp32_dwstrip_benchmark`, `esp32_cycle_benchmark` e `esp32_client_fit_benchmark` del 12 novembre. La variante locale del 16 novembre è ora `experiments/esp32_client_fit_early_benchmark/`, per evitare la collisione con il nome del precedente esperimento. I riferimenti attivi sono aggiornati; hash, nomi di snapshot e percorsi nei record storici JSON rimangono quelli originali per non alterare le evidenze.
