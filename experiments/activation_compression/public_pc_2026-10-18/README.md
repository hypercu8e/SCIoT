# Dati pubblici e verifica HTTP su PC — 18 ottobre 2026

Istruzioni e limiti: [TEST_SU_PC.md](../../../TEST_SU_PC.md).

- [dataset-manifest.json](dataset-manifest.json): 84 fotografie con annotazioni
  dal set pubblico di test Beer/can e due archivi OTB con 291/1.741 frame;
  URL, hash, indici e provenienza. Le immagini/ZIP sono nella cache ignorata da Git.
- [model-summary.json](model-summary.json): inferenza su 84 foto e 32 frame
  uniformemente selezionati per ciascuna sequenza OTB (148 input complessivi).
  Verifica Keras intero/prefisso/suffisso: errore massimo 0,0. Varianti TFLite
  float32, INT8 e 16×8 esistenti, senza nuova calibrazione.
- [images.csv](images.csv): punteggi massimi e celle di primo piano del modello
  Keras, senza assegnare nomi ai canali non ancora confermati del nostro H5.
- [http-summary.json](http-summary.json): prova dei veri componenti server HTTP,
  parser, inferenza e scelta dello split, con client Python e dati di stato isolati.
  Usa il modello RGB originale del framework; orologio locale al posto di NTP,
  profili copiati e tempi dispositivo nulli. Non prova avvio ordinario, accuratezza,
  ottimalità dello split o prestazioni hardware.
- [http-server-prediction.npy](http-server-prediction.npy): uscita osservata dentro
  il server HTTP e confrontata con Keras (max errore `2,38e-7`).
- [snapshot-sha256.txt](snapshot-sha256.txt): integrità dei risultati e sorgenti.

Sui 148 input, riferimento Keras con 355 celle oggetto a soglia 0,5: INT8 cambia
35 celle (24 perse, 11 introdotte); 16×8 ne cambia 33 (21 perse, 12 introdotte).
TFLite float32 non cambia celle. Non sono conteggi di oggetti distinti o accuratezza
rispetto alle annotazioni; non è applicato il postprocessing FOMO.

Le nuove sequenze mostrano scostamenti massimi dei punteggi maggiori di quelli
del primo video: circa 0,630 per INT8 e 0,608 per 16×8. Non estendere automaticamente
la fedeltà osservata nel primo campione a scenari differenti.

Fonti: [set pubblico Edge Impulse](https://studio.edgeimpulse.com/public/89078/latest/acquisition/testing)
e [Visual Tracker Benchmark](https://rvlab.snu.ac.kr/research/tracker_benchmark).
Il set è dichiarato di test dal progetto pubblico corrente, senza dimostrare
la corrispondenza con l'addestramento del nostro H5 esportato. Gli fps OTB originali
non sono verificati. Dati raccolti per prove locali; nessun nuovo modello addestrato,
nessuna simulazione prestazionale ESP32 e nessuna implementazione UDP.
