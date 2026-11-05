# Misura della soglia raw / Rice temporale

Estensione isolata del [benchmark del 30 ottobre](../esp32_lossless_codec_benchmark/report.md).
Obiettivo: delimitare la fascia di rate applicativo in cui Rice temporale supera
il criterio predefinito, senza modificare gli esperimenti storici.

## Risultato — 1 novembre 2026

**Campagna conclusa:** [rapporto e grafico](sweep_2026-11-01/report.md),
[riepilogo numerico](sweep_2026-11-01/summary.json). Quattro rate applicativi
(600, 800, 900 e 1000 kbit/s), 7008 richieste fisiche, 21 test superati.
600 e 800 superano il criterio in tutte le tre coppie; 900 e 1000 no.
Il massimo punto verificato favorevole è **800 kbit/s**, con mediana aggregata
-6,27%; la fascia osservata di transizione è **800–900 kbit/s**.
È il limite del margine operativo scelto, non il pareggio: anche a 900/1000
le mediane aggregate sono migliori del raw. Non è una soglia universale.
La rete è l'hotspot attuale, diversa dalle campagne di ottobre e dalla base
della precedente stima offline. Nessun recupero seriale o tempo stimato;
attivazioni e uscite identiche al raw INT8. Ripristino integrale e avvio del
firmware originale verificati dopo ciascuna campagna.

Il [manifest finale dei sorgenti](source-sha256.json) descrive lo stato di
consegna, incluse le aggiunte ai report dopo la misura. Gli hash nei singoli
`verification.json` conservano invece lo stato registrato durante ogni prova.

## Protocollo della prova

- Stessi modelli INT8, ESP-NN e 146 ingressi canonici, verificati tramite hash.
- Solo configurazioni SLC2 `raw` (0) e `rice_temporal` (3), decoder server C++.
- Sei giri video a ogni rate, ordine raw/Rice e Rice/raw alternato. Sono 1752
  richieste e dodici sequenze per punto; nessuna camera o nuovo quantizzatore.
- CRC e ricostruzione byte per byte verificati offline dal decoder Python
  indipendente; uscite confrontate col raw degli stessi frame nella campagna.
- Mediana almeno -5% e p95 non oltre +5% in tutte le tre coppie di giri.
- Log seriali emessi dopo la misura, con pausa di 2 ms tra righe per ridurre
  le raffiche USB; la pausa è esclusa sia dal ciclo sia dal throughput riportato.

La ricerca inizia a 600, 800 e 1000 kbit/s. Se tutti passano estende a 1500,
2000 e 4000; se tutti falliscono cerca un riferimento a 512, 400, 256 e 128.
Con un punto superato e uno superiore non superato, dimezza l'intervallo su
multipli di 50 kbit/s fino ad ampiezza <=100 kbit/s. Esiti non monotoni fermano
la ricerca: non vengono forzati in una soglia unica. Massimo dodici punti.
La fascia è un intervallo fra punti osservati, non un intervallo di confidenza.

Il proxy limita il corpo della richiesta, non la velocità PHY Wi-Fi.
Luogo/rete possono essere cambiati rispetto a ottobre: non si mescolano coppie
di campagne differenti per decidere la soglia. Prima del flash servono accesso
Linux alla seriale e credenziali valide di una rete raggiungibile a 2,4 GHz.

## Preparazione

Usare la venv TensorFlow 2.15 e i componenti fissati del benchmark precedente.
I file generati, le credenziali e i backup rimangono ignorati da Git.

```sh
.venv/bin/python experiments/esp32_rice_threshold_benchmark/prepare.py
python3 experiments/esp32_rice_threshold_benchmark/idf/fetch_components.py
python3 experiments/esp32_rice_threshold_benchmark/idf/fetch_miniz.py
.venv/bin/python -m unittest discover -s experiments/esp32_rice_threshold_benchmark -p 'test_*.py' -v
```

Creare `results/build-tools` con Python 3.11; installare PlatformIO 6.1.18,
pyserial 3.5, esptool 5.1.0 e matplotlib 3.10.8. Nella preparazione locale questo
environment è condiviso tramite symlink con quello già verificato a ottobre.
Compilazione e prova del binario:

```sh
experiments/esp32_rice_threshold_benchmark/results/build-tools/bin/pio run -d experiments/esp32_rice_threshold_benchmark/idf
.venv/bin/python experiments/esp32_rice_threshold_benchmark/verify_build.py
```

Salvare il log della build in `results/build.log` e quello dei test in
`results/tests.txt` per la verifica. Configurare `include/network.local.h`
(escluso da Git) con rete e SERVER_URL `http://IP_DEL_PC:8786/infer`.
Dopo ogni modifica alla configurazione ricompilare e riverificare.

## Campagna automatica

```sh
.venv/bin/python -u experiments/esp32_rice_threshold_benchmark/sweep.py --tag 2026-11-01 --port /dev/ttyACM0
```

Ogni punto esegue backup/verifica integrale degli 8 MB, flash, misure,
ripristino in `finally`, verifica del digest e identificazione dell'avvio
originale prima dell'audit e dell'esportazione. `--seed-backup` può indicare
un'immagine già verificata: i primi 64 KiB vengono aggiornati e l'identità
dell'intera immagine viene comunque verificata contro la scheda presente.
Non avviare altri programmi sulla seriale durante la prova.

`sweep_TAG/report.md` e `summary.json` riportano risultati progressivi e motivo
della conclusione. In caso di errore la coda si ferma dopo il ripristino;
nessun retry silenzioso o riutilizzo di misure incomplete. Il recupero di un
prefisso USB, se necessario e se tutti i tempi sono integri, segue il metodo
stretto, tracciato e testato dell'esperimento precedente. Non si stimano tempi.
