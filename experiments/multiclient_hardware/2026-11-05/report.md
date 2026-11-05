# Due tentativi diagnostici; validazione multi-client ancora aperta

Il 5 novembre 2026 la campagna si interrompe nella prova individuale di A,
prima delle prove simultanee e dell'ora di stabilità. Entrambe le flash
originali vengono ripristinate, verificate integralmente nella stessa
connessione prima del boot e avviate dopo ciascun tentativo.

| Tentativo | Input incorporati A | Camera A | Esito |
|---|---:|---:|---|
| [Iniziale](initial/summary.json) | 60 completati | 0 completati | Timeout HTTP senza una richiesta camera ammessa dal server |
| [Buffer trattenuto](frame-lease/summary.json) | 60 completati | 1 completato | Primo ciclo camera 6.298,938 ms; richiesta successiva HTTP 408 |

Il primo firmware restituisce il framebuffer prima dell'inferenza/invio.
Il secondo lo trattiene fino al termine, come nel benchmark di rappresentazione,
e aggiunge log/riconnessione Wi-Fi. Il cambiamento **non risolve** il problema;
la sua causa non è stata isolata. Il timeout di ricezione server resta tre
secondi. Il segnale osservato durante il campione camera riuscito è −76 dBm.

Il replay indipendente del suffisso verifica esattamente i byte dei punteggi
su tutte le **60 e 61 richieste archiviate**, rispettivamente. Questo riscontro
di correttezza parziale non valida il traffico simultaneo o la stabilità.
B raggiunge l'attesa iniziale con kernel ESP-NN verificati, ma non avvia una
propria sequenza di richieste: il runner si ferma sull'errore di A.

**Verifiche di preparazione:** [20 test server](tests.log) superati;
[build firmware](firmware-build.log) riuscita, 51.540 byte RAM statica,
1.197.182 byte flash secondo il log conservato. Queste dimensioni non sono
picchi di RAM misurati. [Versioni server](server-environment.json).

Ogni sottodirectory conserva eventi dispositivo/server, sorgente firmware
effettivo, hash dei sorgenti e digest delle evidenze private. Flash, credenziali,
log USB integrali e archivi binari restano in `../results/` sul PC della prova,
esclusi da Git. Nessun tempo è stimato né sostituito.

Una terza directory locale, `results/2026-11-05-B-first`, contiene solamente
backup verificati e log di avvio originale: il passaggio al laptop avviene prima
di installare altro firmware. Non è un terzo tentativo di inferenza.

Il [punto di ripresa sul laptop](../../../RIPRESA_MULTICLIENT_LAPTOP.md) richiede
nuova configurazione LAN e nuovi backup, poi una prova che inizi da B.
L'archivio [frozen-runtime.tar.gz](../frozen-runtime.tar.gz) trasferisce tramite
Git gli artefatti di modello necessari, senza trasferire dati locali riservati.
