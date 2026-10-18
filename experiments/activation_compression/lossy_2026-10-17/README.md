# Esperimento con perdita controllata — 17 ottobre 2026

Prima valutazione su PC di quantizzazione uniforme e codifica temporale delle
attivazioni FOMO, con controllo indipendente a **identica ricostruzione**.
Nessuna modifica a firmware o server SCIoT.

## Risultati da leggere per primi

- [report.md](report.md): metodo, tabelle a 5 e 1 fps, significato delle metriche e limiti.
- [summary.json](summary.json): misure complete, errore sulle uscite, sensibilità alle
  soglie, parametri di sessione, hash dei sorgenti/input e ambiente.
- [frames.csv](frames.csv): byte, modalità e diagnostica per ogni frame.
- [diario del tirocinio](../../../DIARIO_TIROCINIO.md): cronologia e decisioni.

A 5 fps e passo `0,001`, il temporale riduce il flusso del **48,66% sul raw**;
l'indipendente riduce del **40,61%**. Il solo vantaggio temporale è quindi
**13,57% rispetto all'indipendente** alla stessa qualità. Il massimo errore
osservato sulle attivazioni è circa `0,000500023`; sui punteggi di uscita circa
`0,000603`. Le etichette delle celle a soglia 0,5 non cambiano in questo campione.

Passo `0,1`: risparmio temporale **68,28%**, massimo errore sui punteggi circa
`0,0648`, una cella oggetto persa e una introdotta. Passo `0,5`: risparmio
**79,01%**, ma 20 celle perse e 29 introdotte. La media su tutte le celle, in gran
parte sfondo, da sola non basta a valutare il danno.

Il riferimento ha **151 celle oggetto su 21.024 celle-frame** alla soglia 0,5.
Non sono oggetti distinti; non applichiamo il postprocessing FOMO a componenti
connesse. L'accordo col modello non compresso non misura l'accuratezza rispetto
alla realtà. Non ci sono annotazioni e non è stata selezionata una precisione
definitiva per l'applicazione.

## Metodo e confronto

Passi: `0.0001 0.001 0.01 0.1 0.5 1.0`. Interi int32 ottenuti arrotondando
`attivazione/passo`, senza clipping; ricostruzione float32. La rete resta float32.
È quantizzazione dei dati al confine, non un modello INT8 né la replica di un paper.

Per ogni passo entrambi i metodi usano shuffle e zlib livello 1, finestra 32 KiB
e memLevel 8. Il temporale codifica la differenza esatta degli interi condivisi,
prova anche il completo e sceglie il payload minore. Completo iniziale e ogni
5 secondi. AQST/AQF1 con 24 byte per frame e CRC degli interi ricostruiti.
Conteggio inclusivo di sessione, header, wrapper, rinnovi e fallback raw.

Verifica degli interi ricostruiti e dei riferimenti a ogni frame in ognuna delle
tre ripetizioni; verifica del limite d'errore e di identica ricostruzione per i
due metodi. **15 test passati**, lint e controllo indipendente dei totali CSV/JSON.
I tempi lossy includono quantizzazione, selezione, CRC e diagnostica dei delta
nulli; la decodifica include ricostruzione float32. Escludono inferenza, confronto
con gli originali, file e rete. Sono mediana delle medie di tre ripetizioni su PC.

## Provenienza e riproduzione

I dati sono stati rigenerati dal video e dal modello originali, verificati con
i checksum della baseline. La nuova estrazione verifica 146 frame e uno split
Keras con differenza massima osservata 0,0 rispetto al modello intero.

**Le nuove attivazioni hanno SHA-256 diverso da quelle storiche.** Non attribuiamo
la differenza a una causa specifica senza una prova; ambiente e calcoli su macchine
diverse possono cambiare i risultati numerici. I controlli senza perdita e tutti
i candidati lossy di questa esecuzione usano gli stessi nuovi tensori.
La baseline del 15 ottobre non è stata modificata.

Le metriche confrontano il suffisso su attivazioni originali e approssimate con
batch uguali, verificando prima il suffisso rispetto alle uscite del modello
intero archiviate nell'estrazione (`rtol=1e-5, atol=1e-6`). Il piccolo scarto di
esecuzione è riportato nel JSON. Non è assunto identico bit per bit tra batch diversi.

- [input-metadata.json](input-metadata.json): nuova estrazione e verifica dello split.
- [requirements.txt](requirements.txt): freeze dell'ambiente minimo sperimentale,
  Python 3.11.17; non è il lock di tutta l'applicazione SCIoT.
- [verification.json](verification.json): esiti delle verifiche e confronti con
  la baseline storica.
- [environment.json](environment.json): Python, pacchetti, CPU, FFmpeg e impostazioni.
- [snapshot-sha256.txt](snapshot-sha256.txt): integrità degli artefatti e dei sorgenti
  usati, con percorsi relativi alla radice del repository.

Comandi per ricreare l'ambiente, estrarre e confrontare nel
[README dell'esperimento](../README.md#prima-prova-con-perdita-controllata).
I grandi tensori NPY sono ignorati sotto `../results/input_2026-10-17/` e si
possono rigenerare. L'esecuzione archiviata è stata prodotta da:

```bash
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 OMP_NUM_THREADS=1 \
  .venv/bin/python experiments/activation_compression/compare_lossy.py \
  --input-dir experiments/activation_compression/results/input_2026-10-17 \
  --output-dir experiments/activation_compression/results/lossy_2026-10-17_final
```

Dalla radice, controllo degli artefatti conservati:

```bash
sha256sum -c experiments/activation_compression/lossy_2026-10-17/snapshot-sha256.txt
```

Nessuna misura di tempi/RAM/energia su ESP32 o di traffico Wi-Fi reale. Il
riferimento minimo temporale resta 18.432 byte per lato, oltre al workspace e
ai temporanei. Un video e uno split non bastano per generalizzare.
