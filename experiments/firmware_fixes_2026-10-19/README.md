# Correzioni firmware SCIoT — 19 ottobre 2026

**HTTP, MQTT e WebSocket compilano. Le funzioni condivise sono state eseguite sul
PC con TensorFlowLite_ESP32 1.0.0 e controlli di memoria. Nessuna esecuzione ESP32
o misura di prestazione hardware è stata effettuata.**

## Modifica

I tre client float32 originali ora usano due funzioni condivise in
`src/client/common/`, distinte dal firmware sperimentale del candidato INT8:

- Un interprete per layer viene costruito, allocato, invocato e distrutto nello
  stesso ambito; l'uscita è copiata nel buffer di lavoro prima del ritorno.
  Il resolver rimane valido per l'intero programma. Non rimangono puntatori
  globali a interpreti o tensori già distrutti.
- L'allocatore Micro viene creato e controllato esplicitamente: il costruttore
  che riceve direttamente l'arena nella libreria selezionata dereferenzia il
  risultato di `Create` senza verificarlo. Un'arena insufficiente ora produce
  un errore gestito. Sono verificati tipo float32 e dimensione di ogni input,
  secondo ingresso FOMO e output, con arresto su allocazione/inferenza fallita.
- La serializzazione conserva il formato esistente: timestamp float64, 9 byte
  di testo dispositivo, 4 di messaggio, split int32, dimensione uint32 e valori
  float32 dell'uscita, dimensione int32 e tempi float32. I campi numerici sono
  scritti little-endian. Si usa il contenuto delle String e si inviano soltanto
  `(split+1)` tempi validi; nessuna scrittura se dati/capacità non sono validi.
- Sono controllati split ricevuti, allocazioni principali e formato/dimensioni
  del frame. Il secondo ingresso FOMO usa la propria dimensione. La camera ha
  configurazione azzerata; un fallimento di PSRAM/camera/allocazioni blocca il
  ciclo operativo. L'arena PSRAM è allineata a 16 byte.

La misura per-layer inviata al server resta il costo di selezione/preparazione,
copie e calcolo, espresso in secondi; usa differenze intere del contatore
monotono prima della conversione a float. Non è stata sostituita dalla sola
`Invoke`. Rimosse le stampe dettagliate dei tensori nel vecchio percorso, mantenuti
esiti/errori e riepilogo per-layer fuori dalla misura.

Con i template inclusi, il messaggio riserva spazio per una sola attivazione:
**922.253 → 461.261 byte**, differenza **460.992 byte**. È riduzione della richiesta
esplicita all'allocatore PSRAM, non picco RAM totale o accelerazione misurata.
Arena, buffer di lavoro e buffer FOMO conservano le dimensioni precedenti. Chi
usa un `conf.h` locale deve aggiornarne la costante per ottenere la riduzione.

## Evidenze

- Tutti i 59 modelli TFLite del server coincidono byte per byte con i modelli
  incorporati nei tre client. Massimo output 115.248 float; buffer sufficiente.
  Il grafo Keras conferma i riferimenti residui `25←16`, `43←34`, `52←43`.
- **1.170 invocazioni** reali della libreria Micro sul PC: tre input sintetici
  deterministici, sei split e due ripetizioni. Confrontati **33.363.072 valori**
  intermedi con i kernel di riferimento desktop sugli stessi binari: differenza
  massima osservata **0**. Tolleranza dichiarata `rtol=1e-5`, `atol=1e-5`.
- Confronto separato del riferimento TFLite con Keras: massimo scostamento
  intermedio `0.0007476806640625`, massimo sulle uscite finali
  `4.76837158203125e-7`. Le differenze tra i due percorsi numerici non vengono
  attribuite al refactoring. Non sono misure di accuratezza su annotazioni.
- AddressSanitizer e UndefinedBehaviorSanitizer attivi sul codice condiviso e
  sulla libreria Micro nativa; nessun errore rilevato. Le prove negative coprono
  errori di argomenti, schema, allocazione, tipi, capacità, riferimenti e Invoke.
  I messaggi di errore nello stderr provengono dai fallimenti intenzionali.
- Quattro pacchetti generati dal C++, incluso quello da **461.261 byte**, letti
  dal parser Python originale senza modificarlo. Verificati campi, valori e
  lunghezza esatta. Pacchetti insufficienti/invalidi non modificano il buffer.
- Compilazione e collegamento riusciti per i tre client completi. Passati anche
  i **31 test degli esperimenti e i 4 del verificatore seriale** preesistenti.

Non è stato eseguito il vecchio percorso C++ con puntatori già distrutti per
produrre un confronto numerico prima/dopo: quel comportamento è indefinito.
Il riferimento di correttezza sono gli stessi binari eseguiti correttamente.

## Build e riproduzione

I progetti ora fissano espressif32 6.10.0, Arduino ESP32 2.0.17 e le dipendenze
dirette; usano il profilo generico S3 con flash 8 MB e PSRAM OPI, evitando la
necessità della precedente definizione di scheda personalizzata non inclusa.
UUID è fissata a 0.1.6, disponibile nel registro e compresa nel precedente
intervallo `^0.1.5`. Camera, WebServer e FS provengono dal framework Arduino.
HTTP/MQTT selezionano AsyncTCP 1.1.1; i pacchetti aggiuntivi risolti da dipendenze
transitive sono registrati separatamente dal codice effettivamente usato.

La compilazione HTTP segnala un riferimento di ESPAsync_WiFiManager a un vecchio
pacchetto non disponibile; quel componente non è nel grafo delle librerie usate
dal client e non impedisce il build. Restano avvisi preesistenti delle macro dei
modelli e di sorgenti display della libreria non usati. Non sono errori di link.

[Istruzioni native e scenari](../../tests/firmware/README.md),
[configurazione dei client](../../src/client/README.md).
Le credenziali di esempio sono vuote; `conf.h` locale ha precedenza sul template.

Conservati `summary.json`, stdout/stderr nativi, risultati dei test di regressione,
`build-verification.json` con hash dei sorgenti e dei binari, versioni dei pacchetti
e riepiloghi dei tre build. Input, riferimenti sintetici, eseguibile nativo e file
firmware restano nelle directory di build/cache ignorate e sono rigenerabili.

## Limiti e prossima prova

Nessun modello è stato rigenerato, e il server non è modificato. I test non
coprono acquisizione fisica della camera, rete, proprietà dei buffer negli invii
asincroni, concorrenza delle callback, frammentazione MQTT, timer, sincronizzazione
NTP o riconnessioni. Questi aspetti restano da verificare e sviluppare separatamente.

Sulla scheda: prima il firmware INT8 isolato con input fissi già preparato, poi
il client float32 scelto con camera/rete e confronto delle attivazioni su input
noti. Misurare tempi, heap interno e PSRAM senza dedurli dai byte statici del
compilatore. Nessuna ottimizzazione ESP-NN è stata introdotta.
