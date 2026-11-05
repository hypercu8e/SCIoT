# Parallelismo SCIoT: campagna completata con alimentazione variabile

Completate **144 prove HTTP e 30 prove del motore**, con **5.783.532 risposte
HTTP verificate byte per byte** e zero errori d’inferenza nelle prove complete.
**20 test automatici superati.** Tabelle nel [report](report.md), dati compatti
nel [sommario](summary.json), conteggi nello [stato finale](campaign-status.json).

Nel confronto completo iniziale su alimentatore (una ripetizione, 32 client),
passare da 1 a 4 worker con un thread ciascuno porta il motore da 5.946 a 18.718
esecuzioni/s (**3,15×**), ma HTTP da 1.956 a 2.013 richieste/s (**+2,9%**).
Il motore comprende anche preparazione e postprocessing. Questo confronto
descrittivo non è una garanzia statistica per altri carichi o server.

La selezione esplorativa sul regime iniziale ha scelto 4 worker × 1 thread.
Nelle raffiche programmate su alimentatore, a target pari al 100% della baseline
iniziale, le mediane osservate sono circa 615 richieste/s con un worker e 785
con quattro. Il target non coincide con il carico consegnato: 429, backoff e slot
saltati sono registrati. La maggiore ammissione di richieste contribuisce al
risultato; non va attribuito tutto ai kernel.

Il parallelismo è disponibile e corretto. Il servizio completo non scala come
il motore isolato: ricezione, scheduling, logging e generatore restano possibili
limiti, senza che questa campagna ne isoli causalmente il peso. Manteniamo i
valori predefiniti riproducibili 1 worker × 1 thread; la scelta dipende dal carico.


La campagna è ripartita da zero su alimentatore, separata dalla precedente prova
incompleta a batteria. Dopo 66 prove HTTP complete l'alimentatore è stato
scollegato; la prova seguente è stata esclusa automaticamente e conservata.
Su richiesta esplicita dell'utente si prosegue con `--allow-battery` e
`--allow-energy-changes`, registrando tutte le condizioni.

I confronti sono separati per alimentazione e profilo CPU. Le prove con cambio
di condizione fra inizio e fine sono marcate `transition`: conservano valore
funzionale ma non permettono un confronto prestazionale stabile. Non si ottengono
necessariamente tre ripetizioni per ogni configurazione in ogni regime energetico.
I campioni a batteria non vengono mediati con quelli su alimentatore.

La selezione esplorativa per la fase a carico programmato usa solo i campioni
nel regime energetico iniziale (alimentatore e `balance_performance`); i rate
restano assoluti, registrati per prova. Questa scelta non dimostra un vincitore
universale su tutti i regimi energetici. I manifest di ripresa conservano gli hash
dei sorgenti aggiornati; il server e il modello non sono cambiati.

Artefatti finali: `report.md`, `summary.json`, `results/selection.json` e manifest/log
per tutte le prove. Il quadro generale e i comandi sono nel README superiore.

Durante la fase a rate programmato è stata corretta una race nel generatore:
due letture dell'orologio potevano produrre una durata negativa per `sleep`.
Ora il ritardo viene calcolato da una sola lettura; il test di regressione passa.
La prova incompleta è archiviata in `results/failed_trials/` e ripetuta, senza
includere i suoi campioni parziali nel sommario. I manifest di ripresa registrano
le versioni del generatore; modello e server d'inferenza sono invariati.

Per riprodurre la campagna usare una directory nuova, seguendo i comandi nel
README superiore. I dati completi sono in `results/`, esclusi da Git.
