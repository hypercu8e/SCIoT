# Fonti per nuovi test e primo benchmark ESP32

Ricerca e download eseguiti il 17 ottobre 2026. Non sono stati avviati nuovi
benchmark di compressione su queste sequenze né prove sulla scheda.

## 1. Sequenze reali trovate e scaricate

Fonte degli autori: [Visual Tracker Benchmark, SNU Robot Vision Lab](https://rvlab.snu.ac.kr/research/tracker_benchmark).
La pagina attuale offre archivi pubblici tramite Google Drive. Sono stati scaricati
due archivi, verificati con i CRC interni ZIP e controllati in ordine numerico.
Sono state ispezionate anche immagini di esempio.

| Sequenza | Contenuto nell'immagine iniziale | Frame ordinati | Dimensioni iniziali | Archivio |
|---|---|---:|---|---|
| Coke | Lattina Coca-Cola tenuta da una persona | 291 | 640×480 | [Coke.zip](https://drive.google.com/file/d/1nGsvt_IImvA4iJD22Qzm9jFPJxi-AudA/view) |
| Liquor | Bottiglia di liquore su un tavolo | 1.741 | 640×480 | [Liquor.zip](https://drive.google.com/file/d/1npRoxKorlgVqnf7fYtDkPrJ4pPBLQO1u/view) |

Non sono raccolte di foto indipendenti: ciascun archivio contiene immagini
consecutive di una ripresa, numerate da 0001 senza interruzioni, e annotazioni di
tracking `groundtruth_rect.txt`. Non assumiamo che quelle annotazioni descrivano
tutti gli oggetti o forniscano etichette compatibili con le classi del FOMO.

Percorso locale ignorato da Git:
`experiments/activation_compression/results/public_sources/otb/`.
Contiene archivi, esempi e `download-manifest.json`. Le immagini non sono state
ridistribuite in una cartella versionata. Questi download non stabiliscono una
licenza generale di riutilizzo o redistribuzione; la pagina degli autori è la
fonte di provenienza da conservare e le condizioni vanno verificate per una
pubblicazione/redistribuzione del materiale.

| Archivio | Byte | SHA-256 |
|---|---:|---|
| Coke.zip | 23.547.911 | `3158a246da79646d0ef86bde44761d77c8d2df89cfb287ff25aa536f187a520b` |
| Liquor.zip | 68.154.452 | `75632ad053e87c3b9bfd55916ac576d9eb7ea0cc6cc614bcbbdf8f9dc704469a` |

**Frequenza originale non verificata:** archivi e pagina consultata non ci hanno
fornito un valore verificato di fps. Per le prossime prove conviene confrontare
salti tra immagini (per esempio una ogni 1, 5 o 10), senza chiamarli automaticamente
5 fps o 1 fps. Assegnare 30 fps a un MP4 ricostruito non dimostrerebbe che la ripresa
originale avesse quella frequenza. Anche i rinnovi dovranno essere dichiarati in
numero di frame, salvo ottenere una temporizzazione verificata.

Queste sequenze permettono un confronto su altri contenuti e movimenti; la
presenza di lattine o bottiglie non garantisce buone rilevazioni del nostro FOMO,
che potrebbe essere sensibile a dimensioni, sfondo e tipo di oggetto. Fedeltà al
modello originale e accuratezza su annotazioni restano misure diverse.

## 2. Cosa abbiamo trovato su Edge Impulse

Il [progetto Beer vs. cans 89078](https://studio.edgeimpulse.com/public/89078/latest)
mostra 524 elementi e campioni JPG. Non abbiamo trovato una sequenza video
temporale scaricabile da quel progetto. Le immagini possono servire per verificare
modello e approssimazioni, ma non vanno ordinate arbitrariamente presentandole
come una ripresa reale.

Inoltre il dataset del modello non è automaticamente un insieme esterno di test:
va distinto ciò che è stato usato per training, validation e test. Non è stato
scaricato un nuovo modello né modificato il progetto Edge Impulse.

## 3. Scheda dell'utente identificata dal link

Il link fornito dall'utente `https://amzn.eu/d/0doYfu64` rimanda ad Amazon ASIN
`B074RGW2VQ`, titolo letto: AZDelivery ESP32 NodeMCU WiFi CP2102, ESP32 WROOM.
È un ESP32 classico, distinto dall'ESP32-S3 selezionato nel firmware del repository.

[Pagina del produttore AZDelivery](https://www.az-delivery.de/en/products/esp32-developmentboard):
modulo ESP32-WROOM 32, fino a 240 MHz, flash 4 MB e RAM indicata come 512 kB;
non dichiara PSRAM esterna. Il [datasheet Espressif del WROOM-32](https://documentation.espressif.com/esp32-wroom-32_datasheet_en.html)
riporta 520 KB di SRAM sul chip. Il quantitativo effettivamente libero per i buffer
va misurato a runtime e non coincide con la RAM totale. Il numero esatto del modulo
e la presenza di PSRAM sulla scheda fisica restano verifiche da fare, non misure
già effettuate sul dispositivo.

Nel progetto attuale `platformio.ini` seleziona `esp32-s3-devkitc-1-n8r8` e
`conf.template.h` imposta una tensor arena di `1000*1024` byte; il firmware usa
anche allocazioni in PSRAM. Non si assume quindi che il firmware completo funzioni
invariato sulla NodeMCU WROOM dell'utente.

## 4. Primo test utile senza acquistare una camera

Proposta da implementare, non firmware già pronto:

```text
PC con attivazioni registrate
       │ USB/seriale, fuori dalla misura del codec
       ▼
ESP32: riceve un tensore → quantizza/comprime → restituisce payload e misure
       │
       ▼
PC: decodifica e verifica il riferimento e il tensore ricostruito
```

1. Collegare la scheda al PC via USB con un cavo dati e identificarla.
2. Preparare un piccolo firmware C/C++ dedicato al codec, separato da camera,
   TensorFlow e servizi SCIoT. Il prototipo attuale è Python e va portato.
3. Fornire un frame di attivazioni alla volta; non conservare l'intero video in RAM.
4. Misurare tempo del codec, memoria libera/minima e maggiore blocco allocabile;
   confrontare raw, indipendente e temporale con gli stessi parametri e qualità.
5. Verificare sul PC la ricostruzione e le sequenze. Tenere il trasferimento USB
   e le stampe seriali fuori dall'intervallo misurato del codec.
6. Aggiungere una prova Wi-Fi con ricezione/conferma sul PC, misurando il flusso
   completo e distinguendolo dal solo costo di compressione. Il ritorno da una
   funzione di invio non dimostra la ricezione completa del messaggio.

Il vantaggio di questo approccio è che non richiede ancora camera né inferenza
sulla scheda. Misura realmente la compressione sulla NodeMCU; non dimostra da solo
che rete neurale, camera e codec possano convivere in memoria o che le prestazioni
siano le stesse di un ESP32-S3.

Zlib con i parametri di riferimento può richiedere troppo heap libero o un blocco
troppo grande sulla WROOM, specialmente con Wi-Fi. Se si riducono finestra o
memLevel bisogna registrare i parametri e ripetere il confronto: non si possono
riusare automaticamente gli stessi rapporti di compressione della prova su PC.

## 5. Hardware e confronto con il docente

Prima di un acquisto, chiedere se il laboratorio ha la scheda prevista per SCIoT
e quale target usare come riferimento. Non è necessario aspettare una camera per
preparare il benchmark del solo codec. Esempio di messaggio da inviare personalmente:

> Ho completato una prima prova su PC di compressione indipendente e temporale
> delle attivazioni FOMO con perdita controllata. Ho già una NodeMCU ESP32-WROOM-32:
> vorrei usarla per un primo benchmark del codec con tensori registrati, senza
> camera. Il laboratorio dispone di ESP-EYE/ESP32-S3-EYE o di altre schede per la
> successiva integrazione? Quale hardware conviene prendere come riferimento?

Non acquistare una camera generica assumendo che renda la NodeMCU equivalente
alla scheda del progetto. Collegamenti, sensore, pin e RAM vanno scelti insieme.
Il [driver ufficiale esp32-camera](https://github.com/espressif/esp32-camera)
supporta sensori specifici e richiede PSRAM nella maggior parte delle configurazioni,
con eccezioni dichiarate per JPEG a bassa risoluzione.

Per una futura acquisizione integrata, una candidata coerente da concordare è
[ESP32-S3-EYE](https://documentation.espressif.com/esp-who/master/docs/en/get-started/ESP32-S3-EYE_Getting_Started_Guide.md):
la guida ufficiale indica camera OV2640 e 8 MB di PSRAM. Questo non garantisce
che il candidato FOMO in grigio e il codec funzionino senza adattamenti.
Non sono stati acquistati dispositivi né inviati messaggi al docente.

## 6. Zlib: spazio del firmware e memoria di lavoro

Negli ultimi chiarimenti abbiamo distinto due costi:

- **Flash:** il codice compilato di zlib aggiunto al firmware. Dipende dalle
  funzioni collegate e dalle opzioni di compilazione; non abbiamo ancora una
  misura per ESP32. La dimensione dell'archivio dei sorgenti non è questa misura.
- **RAM:** lo stato interno del compressore durante l'esecuzione, oltre ai buffer
  dell'applicazione. La configurazione usata negli esperimenti è livello 1,
  `windowBits=15`, `memLevel=8`; il livello 1 non equivale a memoria minima.

La [documentazione tecnica di zlib](https://www.zlib.net/zlib_tech.html) fornisce
una formula indicativa, dipendente anche dalla compilazione:

```text
RAM deflate ≈ 2^(windowBits + 2) + 2^(memLevel + 9) + 6 KiB
```

| windowBits / memLevel | Finestra | RAM interna stimata del compressore |
|---|---:|---:|
| 15 / 8, configurazione attuale | 32 KiB | 262 KiB, circa 268 kB |
| 13 / 5 | 8 KiB | 54 KiB |
| 12 / 4 | 4 KiB | 30 KiB |

Sono stime calcolate dalla formula, **non misure ottenute sulla scheda**.
Non includono tensore corrente, riferimento temporale da 18 KiB, risultati,
shuffle, altri temporanei, stack, Wi-Fi o inferenza. Il
[manuale zlib](https://www.zlib.net/manual.html) distingue `level`, `windowBits`
e `memLevel`: cambiare gli ultimi due può modificare dimensioni compresse e tempi.

Il prossimo confronto utile sulla memoria sarebbe ripetere la prova su PC con
parametri ridotti e misurare quanto risparmio rimane, prima di scegliere il porting.
**Questo confronto non è ancora stato eseguito**: i risultati del 48,66% e degli
altri passi restano quelli della configurazione 15/8.

## 7. Scheda del docente e allocazioni in PSRAM

Il modello effettivamente disponibile presso il docente non è stato confermato.
Il confronto discusso in chat è condizionale: se fosse ESP-EYE o ESP32-S3-EYE,
entrambe dispongono di 8 MB di PSRAM secondo il
[confronto ufficiale Espressif](https://documentation.espressif.com/esp-who/master/docs/en/get-started/ESP32-S3-EYE_Getting_Started_Guide.md).
La presenza di 8 MB rende più plausibile il budget di memoria, ma non dimostra
che tutti i componenti del sistema entrino o funzionino contemporaneamente.

**PSRAM disponibile non significa PSRAM automaticamente usata da zlib.** Nel
porting vanno controllati allocatore, configurazione e posizione dei buffer,
preservando RAM interna sufficiente per sistema e comunicazione. Memoria interna
libera, PSRAM libera e maggiore blocco allocabile vanno rilevati separatamente.
Tempi di compressione, vantaggio complessivo ed energia restano da misurare.

## 8. Chiarimenti di lettura e limiti dell'emulazione

I risultati e le spiegazioni principali sono già negli altri documenti:

- 5 fps e 1 fps sono campionamenti del video, non un rallentamento del PC per
  simulare ESP32; corrispondono a distanze nominali di 0,2 e 1 secondo tra campioni.
- Un «valore originale» dell'esempio di arrotondamento è un singolo elemento del
  tensore al punto di split, identificato da posizione e canale. Arrotondiamo
  tutti gli elementi del tensore trasmesso, non i pesi di tutta la rete.
- Passo 0,1 implica errore assoluto di arrotondamento circa entro 0,05, non errore
  percentuale del 10% e non una soglia già dichiarata accettabile.
- «Temporale» descrive l'uso di un riferimento tra frame. Le percentuali misurate
  sono risparmi di byte, non riduzioni di tempo già ottenute sulla scheda.

L'emulazione del firmware e la previsione delle prestazioni sono compiti distinti.
Abbiamo citato [QEMU per ESP32-S3](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/api-guides/tools/qemu.html)
e [Wokwi](https://docs.wokwi.com/guides/esp32) come strumenti possibili di sviluppo,
senza installarli o eseguire SCIoT al loro interno. QEMU
[dichiara che il conteggio delle istruzioni non è una simulazione accurata dei cicli](https://www.qemu.org/docs/master/devel/tcg-icount.html):
non si possono presentare i tempi dell'emulatore come tempi esatti dell'ESP32.
Nemmeno limitare la CPU del PC o moltiplicare tutti i tempi per un fattore fisso
costituisce una simulazione prestazionale validata.
