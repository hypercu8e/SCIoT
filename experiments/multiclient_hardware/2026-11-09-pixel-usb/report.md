# Fisso, hotspot Pixel 9a e inoltro USB — 9 novembre 2026

## Collegamento e tentativi

Due ESP32-S3-EYE fisiche, stesso firmware HTTP v2 INT8 raw/ESP-NN e split
`block_2_add`. Il server gira sul fisso; il Pixel è vicino alle schede.
Credenziali, firmware, backup e log integrali sono esclusi da Git.

1. `results/2026-11-09-pixel-usb-smoke`: nome hotspot inizialmente errato.
   Entrambe le schede emettono `wifi_disconnected`, motivo 201
   (`WIFI_REASON_NO_AP_FOUND`). Nessuna inferenza. Flash originali ripristinate
   e verificate, con log di avvio, su entrambe.
2. `results/2026-11-09-pixel-usb-corrected`: nome corretto, entrambe arrivano
   a `ready`, quindi hanno ottenuto la connessione Wi-Fi. La registrazione
   di B verso `http://10.186.241.84:8000` va in timeout TCP; nessuna inferenza
   raggiunge il server. L'utente apre invece le API da browser sul Pixel.
   Il passaggio hotspot → PC su tethering USB non è riuscito; la specifica
   regola di rete responsabile non è stata isolata. Entrambe le flash originali
   sono state ripristinate e verificate, con log di avvio.

## Inoltro della porta con ADB

ADB era già installato sul fisso. L'utente abilita Debug USB e autorizza il PC.
Il comando seguente apre sul telefono la porta 8000 e inoltra le connessioni
al server sulla porta 8000 del fisso:

```sh
adb devices -l
adb shell ip -4 addr show
adb reverse --no-rebind tcp:8000 tcp:8000
adb reverse --list
```

Prima della creazione non erano presenti altri inoltri reverse. Controllare
quelli esistenti prima di ripetere il comando; non rimuovere regole estranee.

Indirizzi osservati in questa sessione:

| Nodo/interfaccia | Indirizzo |
|---|---|
| Fisso, Ethernet di casa | `192.168.1.152` |
| Fisso, tethering USB | `10.186.241.84` |
| Pixel, USB `ncm0` | `10.186.241.81` |
| Pixel, hotspot `wlan1` | `10.158.38.173` |

Dal fisso, sia `http://127.0.0.1:8000/openapi.json` sia
`http://10.186.241.81:8000/openapi.json` restituiscono HTTP 200 e le API del
server. Questo verifica l'inoltro dal lato USB; la verifica dalle ESP32
è una fase successiva distinta.

Nel file locale ignorato
`src/client/esp32-s3-eye-multiclient/include/network.local.h`, il valore
`SERVER_BASE_URL` diventa `http://10.158.38.173:8000`: le schede contattano
l'indirizzo del **Pixel sull'hotspot**, non l'indirizzo USB del fisso.

```text
ESP32 → Wi-Fi hotspot → Pixel:8000 → ADB su USB → fisso:8000
```

Gli indirizzi possono cambiare riattivando le connessioni. Prima di riprendere,
leggerli nuovamente e verificare l'inoltro; riconnessione USB/riavvio possono
richiedere di ricrearlo. Per rimuovere soltanto questo inoltro:

```sh
adb reverse --remove tcp:8000
```

## Prova individuale tramite ADB

Directory locale: `results/2026-11-09-pixel-adb-smoke`. Nuovi backup verificati
prima dell'installazione; stesso binario su entrambe; esecuzione con
`campaign.py --first-board B --single-only`.

| Scheda | Input incorporati | Frame camera | Errori dispositivo | RSSI camera | Mediana ciclo camera |
|---|---:|---:|---:|---|---:|
| B | 60/60 | 20/20 | 0 | −30 / −26 dBm | 249,019 ms |
| A | 60/60 | 20/20 | 0 | −38 / −34 dBm | 247,455 ms |

Sono prove **individuali consecutive**, 160 richieste totali. Questi 20 frame
per scheda bastano a verificare il collegamento breve; non dimostrano stabilità
prolungata o capacità multi-client. I frame camera non hanno annotazioni.

**Verifica completata:** 160 risposte HTTP 200; replay indipendente del suffisso
con punteggi identici byte per byte su tutte le 160 richieste archiviate.
Attivazioni dei tre input incorporati identiche fra le schede. Collegamento
dei log dispositivo all'archivio tramite FNV32, CRC32 verificato sui corpi:
gli hash FNV32 non sono una prova crittografica di uguaglianza.
Entrambe le flash da 8 MiB ripristinate e verificate prima del boot; log di
avvio originale controllati dall'analizzatore.
[Risultati e statistiche](summary.json).

L'analizzatore supporta `--single-only` per questo protocollo: richiede entrambe
le fasi individuali concluse, 60+20 campioni per scheda, nessun errore di campagna
e ripristini verificati. La modalità ordinaria continua a richiedere tutte le
fasi della campagna completa. Comando per il replay delle risposte:

```sh
PYTHONPATH=src TF_CPP_MIN_LOG_LEVEL=3 CUDA_VISIBLE_DEVICES=-1 .venv/bin/python experiments/multiclient_hardware/analyze.py --single-only --run experiments/multiclient_hardware/results/2026-11-09-pixel-adb-smoke --output experiments/multiclient_hardware/2026-11-09-pixel-usb/summary.json
```

Controlli negativi sui log reali: l'analizzatore rifiuta la prova breve in modalità
campagna completa, una copia priva della fase individuale A e una copia con
un campione camera rimosso. [Esiti dei controlli](audit-negative-checks.json).
Le copie alterate sono temporanee; i log originali restano invariati.

## Limiti delle misure

Questa rete include il trasporto ADB e differisce dalle campagne precedenti.
I tempi ottenuti descrivono questo percorso completo: non dimostrano un
miglioramento del firmware o della sola rete Wi-Fi. La prova breve individuale
non sostituisce la campagna simultanea, il riavvio isolato o l'ora di stabilità.
