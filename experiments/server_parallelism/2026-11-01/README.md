# Parallelismo CPU del suffisso SCIoT INT8

**Aggiornamento:** la campagna successiva è completata: [risultati e interpretazione](ac/README.md), [report](ac/report.md). È iniziata su alimentatore ed è proseguita con alimentazione variabile su richiesta; i risultati sono separati per regime energetico. Le sezioni sullo stato interrotto qui sotto descrivono la prima campagna archiviata.

Obiettivo: distinguere parallelismo fra inferenze e thread interni alla singola
inferenza, prima di estendere il selettore dinamico al multi-client.

Modello congelato e taglio `block_2_add`, interpreti TFLite CPU senza delegati
predefiniti. Le prove non cambiano firmware o protocollo HTTP. Ogni worker usa
un interprete indipendente sul proprio thread. La configurazione di riferimento
resta un worker con un thread TFLite.

Dalla radice del repository, con TensorFlow 2.15, FastAPI e Uvicorn installati:

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests/multiclient -v
PYTHONPATH=src .venv/bin/python tools/multiclient/benchmark.py --output experiments/server_parallelism/2026-11-01/results
.venv/bin/python tools/multiclient/report_parallel.py experiments/server_parallelism/2026-11-01/results --output experiments/server_parallelism/2026-11-01
```

L'output deve essere nuovo. Una campagna completa richiede circa 90–110 minuti;
non esegue configurazioni simultanee. Per una prova della procedura si possono
usare `--duration 0.3 --warmup 0.1 --repeats 1 --clients 2` e un'altra directory:
questi risultati brevi non sostituiscono la campagna completa.

Matrice: worker e thread in {1,2,4,8}, prodotto massimo 8; client in {1,2,8,32}.
Tre ripetizioni, 5 secondi di riscaldamento e 30 misurati per prova. Ordine delle
configurazioni e dei client invertito nella seconda ripetizione. Stessa matrice
per il solo motore, con attivazioni dei tre frame congelati e tensori sintetici
agli estremi INT8. Ogni risultato viene verificato rispetto al riferimento.
La fase HTTP confronta tutti i risultati riusciti e gli identificativi.

La configurazione con la maggiore mediana di throughput al massimo numero di
client viene confrontata con la baseline a frequenze aggregate del 50%, 80%,
100% e 120% della capacità osservata della baseline, con tre ripetizioni.
Il generatore mantiene una richiesta pendente per client e riporta gli slot
saltati. Durante il riscaldamento il generatore non limita la frequenza;
le statistiche delle richieste misurate escludono il riscaldamento.

`manifest.json` conserva hardware, dipendenze, hash dei sorgenti e modello.
`results.jsonl` contiene risultati incrementali. I log completi sono locali in
`results/`, esclusi da Git; report e sommario compatti possono essere versionati.
Le misure HTTP separano coda e occupazione del worker; CPU e RSS sono campionate
ogni secondo. La CPU del generatore è registrata separatamente. I client girano
sullo stesso PC: un plateau HTTP può riflettere anche un limite del generatore.

Nessuna conclusione su ESP32, contesa Wi-Fi, GPU o altri server deriva da questa
campagna. Anche l'attività di altre applicazioni sul PC può influire sui tempi.

## Ripresa e audit della registrazione

`--resume` riprende una campagna esistente saltando le prove complete. Una prova
incompleta viene conservata in `results/failed_trials/` prima di essere ripetuta;
nessun campione parziale entra nel sommario. Ogni ripresa salva un nuovo manifest
con gli hash dei sorgenti e l'ambiente.

Dopo 35 prove HTTP complete, il generatore ha interrotto la prova
`matrix-w4-t2-n32-r0` su un 429 durante la registrazione. Le registrazioni iniziali
sono state spostate prima del riscaldamento e i 429 di una registrazione successiva
vengono ritentati. Il server, il modello e il percorso di inferenza non sono stati
modificati. `registration-audit.json` e i manifest conservano questo passaggio;
i risultati precedenti restano prove con la preparazione originale dei client.

## Stato della campagna

**Interrotta: confronto prestazionale non conclusivo.** Durante la seconda
ripetizione sono stati osservati forti rallentamenti; il controllo ha rilevato
batteria al 17%, stato `Discharging`, preferenza energetica CPU `power` e frequenze
intorno a 1,1–2,4 GHz. Il governor era `powersave`, temperatura letta 51 °C.
Non è dimostrato quanto ogni fattore abbia contribuito alla variabilità.

Il report corrente conserva le prove complete come risultati preliminari e
verifiche funzionali. Non viene scelta una configurazione vincente. Per il
confronto prestazionale occorre una nuova campagna su alimentatore e profilo
stabile, in una directory nuova: riprendere i campioni attuali mescolerebbe le
condizioni. La prova parziale finale non entra nel sommario.

Il runner ora controlla l'alimentazione prima di creare l'output e fra le prove,
conserva alimentazione, profilo CPU, frequenze, temperature e carico nei manifest
e nei file `environment.json`, e interrompe il confronto se cambia il profilo
energetico. `--allow-battery` serve soltanto a prove esplicitamente dedicate al
funzionamento a batteria. Non vengono modificate impostazioni del sistema.
