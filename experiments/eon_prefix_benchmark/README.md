# EON sul prefisso INT8 di FOMO

Prova separata dal [benchmark FLOAT32/INT8](../esp32_representation_benchmark/README.md).
Obiettivo: confrontare TFLite Micro + ESP-NN con EON sullo **stesso prefisso**,
senza cambiare preprocessing, pesi, quantizzazione o taglio `block_2_add`.
Il suffisso e il server HTTP del benchmark restano il riferimento.

## Stato verificato al 28 ottobre 2026

- Preparati modello e tre input congelati, con verifica degli hash e del contratto
  INT8 tra prefisso e suffisso. Nessun training, conversione o ricalibrazione.
- SDK Edge Impulse installato separatamente in `/tmp/sciot-eon-tools`.
- Verificata offline la configurazione `other` / `freeform`, EON standard e INT8.
- Prima autenticazione riconosciuta ma rifiutata con HTTP 403: la API key aveva
  ruolo `ingestion_deployment`; il servizio richiede `admin` per la chiamata SDK.
- Dopo la sostituzione con la chiave Admin: **upload del prefisso e configurazione
  freeform riusciti**. Il servizio conferma ingresso/uscita INT8 e quantizzazione.
- **Compilazione EON bloccata dal piano del progetto:** il servizio richiede
  Enterprise per EON sui modelli importati (BYOM). La disponibilità di EON standard
  per modelli addestrati in Studio non implica disponibilità per il nostro prefisso
  già addestrato. Non è un errore tecnico del modello e non dimostra incompatibilità.
- **Nessuna libreria EON scaricata, build o verifica hardware.** Nessuna porta
  `/dev/serial/by-id`, `ttyACM0` o `ttyUSB0` presente durante il controllo iniziale.

Il [risultato persistente](STATUS.json) conserva il motivo ricevuto dal servizio.
Non sono stati avviati acquisti, training o ricalibrazioni. Per riprendere questa
stessa prova serve un progetto con accesso Enterprise a EON/BYOM; altrimenti si
può proseguire con TFLite Micro + ESP-NN per il multi-client. Riaddestrare un altro
modello in Studio non sarebbe un confronto sullo stesso modello congelato.

Il supporto freeform è documentato da Edge Impulse, ma non dimostra da solo che
l'esportazione MCU EON del nostro prefisso possa accedere all'uscita INT8 grezza.
Questa compatibilità è uno dei risultati da verificare.

## Decisione di lavoro — 29 ottobre 2026

EON è accantonato come dipendenza dei test successivi. Il confronto INT8 raw/zlib
è stato [completato con TFLite Micro + ESP-NN](../esp32_int8_compression_benchmark/2026-10-28/report.md),
come il percorso multi-client. Le istruzioni di esportazione e il piano dopo
l'esportazione qui sotto restano condizionali a un accesso adeguato al servizio;
non sono attività ancora obbligatorie o prove già eseguite.

## Preparazione locale riproducibile

Dalla radice SCIoT, con gli artefatti del benchmark precedente disponibili:

```sh
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 .venv/bin/python experiments/eon_prefix_benchmark/prepare.py
.venv/bin/python -m unittest discover -s experiments/eon_prefix_benchmark -p 'test_*.py' -v
```

Lo script richiede una directory di uscita vuota; per ripeterlo conservando i
risultati usare `--output /tmp/sciot-eon-preparation-repeat`.

`artifacts/` contiene il prefisso esatto da caricare, il suffisso di riferimento,
tre input quantizzati di 9.216 byte e `vectors.npz`. Il file
`upload-prefix.zip` è solo un pacchetto di consegna: in Studio va caricato il
**file `int8-prefix.tflite`**, non questo ZIP contenente anche il manifest.

Contratto: ingresso `[1,96,96,1]` INT8, uscita `[1,24,24,8]` INT8 (4.608 byte),
scala e zero point riportati in `artifacts/manifest.json`. Il prefisso ha SHA-256:

```text
d41048c7accf408e57d1f6a7882ee5acebd1e6d3e9a0ba008746481cfb05b30c
```

Sono conservati separatamente i risultati desktop `BUILTIN_WITHOUT_DEFAULT_DELEGATES`
e `BUILTIN_REF`, entrambi TensorFlow 2.15. Nei tre frame 48/96/145 differiscono
rispettivamente 674/680/587 attivazioni su 4.608, con scarto massimo di 4 unità INT8.
Non sono due misure hardware e nessuno dei due viene dichiarato automaticamente
equivalente a ESP-NN. Il confronto EON dovrà includere i byte della baseline sulla
scheda, senza nascondere scostamenti cambiando la tolleranza.

## Esportazione autenticata

Creare un progetto separato in Studio; in Dashboard → Keys creare una **API key
Admin** del progetto. HMAC è un altro tipo di chiave e non serve a questa prova.
Salvare la API key come unico contenuto di `sciot_eon_api_key` nella radice SCIoT.
Il percorso è escluso da Git; non inserirla nei comandi, nei report o nei sorgenti.

```sh
python3 -m venv /tmp/sciot-eon-tools
/tmp/sciot-eon-tools/bin/pip install -r experiments/eon_prefix_benchmark/requirements.txt
/tmp/sciot-eon-tools/bin/python experiments/eon_prefix_benchmark/deploy.py --check
/tmp/sciot-eon-tools/bin/python experiments/eon_prefix_benchmark/deploy.py --api-key-file sciot_eon_api_key --output experiments/eon_prefix_benchmark/exports/NUOVO-RUN
```

L'ultima operazione usa la rete e modifica il progetto identificato dalla chiave:
carica il prefisso, imposta ingresso `other` (senza preprocessing aggiuntivo),
uscita `freeform`, e richiede `int8`, `tflite-eon`, libreria C++ `zip`.
Non vengono forniti dati rappresentativi per una nuova quantizzazione.
Usare un nuovo percorso di output per ciascun tentativo.

Con SDK 1.0.20 l'interfaccia semplificata `model.deploy` non espone `Freeform` e
rifiuta l'uscita a quattro dimensioni come classificazione/regressione. Lo script
usa le API ufficiali sottostanti per upload/configurazione e
`edgeimpulse.experimental.impulse.build`, lo stesso entrypoint usato dal SDK.
Le versioni sono fissate perché questa interfaccia è sperimentale.

`--check` verifica localmente integrità dei file, serializzazione freeform e
disponibilità dell'entrypoint EON/INT8: **non autentica e non compila**.
Lo ZIP scaricato viene inventariato senza estrarlo né eseguirlo. Un download
riuscito non certifica tipo dei buffer, ESP-NN, build o correttezza numerica.

## Dopo l'esportazione

1. Ispezionare gli header generati, confermare EON standard e individuare le
   funzioni effettive di inizializzazione, input, esecuzione e uscita INT8.
2. Verificare dimensioni/quantizzazione e il mantenimento delle chiamate ai kernel
   ESP-NN S3; adattare al codice effettivamente generato, senza inventarne le API.
3. Preparare due firmware con **un solo modello INT8 residente ciascuno**: baseline
   TFLite Micro + ESP-NN ed EON. Non usare le due arene simultanee del benchmark
   FLOAT32/INT8 come riferimento di memoria della nuova variante.
4. Prima della flash verificare il backup originale. Eseguire i tre input fissi,
   confrontare byte delle attivazioni e uscite del suffisso, quindi camera e HTTP.
5. Tre sessioni alternate per variante, warmup escluso, almeno 1.000 inferenze
   consecutive per stabilità; misurare inferenza, tempo completo, memoria e flash.

La prima verifica di correttezza richiede uguaglianza esatta sulla stessa entrata.
Se cambiano le uscite, fermare il confronto prestazionale e studiare la causa.
Se cambiano anche i kernel, descrivere il confronto come due configurazioni
complete, senza attribuire ogni differenza al solo EON.

Il successivo lavoro multi-client resta impostato su N identità, due ESP32 come
prima prova fisica, coda limitata e un worker. EON non è un prerequisito.

## Fonti

- [EON Compiler: codice generato, opzioni e limitazioni](https://docs.edgeimpulse.com/studio/projects/deployment/eon-compiler).
- [BYOM: importare un modello TFLite già addestrato](https://docs.edgeimpulse.com/studio/projects/dashboard/byom).
- [Uscite freeform](https://docs.edgeimpulse.com/tutorials/topics/machine-learning/deploy-freeform-model).
- [Python SDK](https://docs.edgeimpulse.com/tools/libraries/sdks/studio/python).

Le stime RAM/tempo di Studio non sostituiscono misure sull'ESP32-S3-EYE.
