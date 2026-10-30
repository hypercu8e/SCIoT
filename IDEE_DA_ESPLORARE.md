# Possibili idee da esplorare

Questo file raccoglie le piste da valutare in seguito. Al 29 ottobre 2026 la baseline INT8 ESP-NN e il confronto raw/zlib su una scheda sono completati; il prossimo controllo riguarda il servizio HTTP v2 con due ESP32. La selezione preventiva dei frame e la compressione temporale INT8 restano da valutare. Stato e priorità nel [recap](RECAP_LAVORO_FORK.md).

## 1. Selezione dei frame da elaborare e trasmettere

**Annotata il:** 15 ottobre 2026.  
**Stato:** da approfondire dopo l'esplorazione della compressione delle differenze delle attivazioni.

### Idea

Confrontare sull'ESP32 il frame corrente con un'immagine di riferimento, prima di eseguire la rete neurale. Se il cambiamento è abbastanza piccolo, saltare la nuova inferenza e le trasmissioni associate; altrimenti elaborare il frame e inviare al server le attivazioni intermedie.

### Motivazione

Una telecamera fissa potrebbe acquisire molti frame simili. Evitare elaborazioni e invii ridondanti potrebbe ridurre sia il calcolo locale sia il traffico di rete.

### Domanda da verificare

Un confronto leggero tra immagini permette di risparmiare calcolo e traffico senza perdere rilevazioni o introdurre ritardi eccessivi negli eventi importanti?

### Aspetti da chiarire

- Criterio di confronto, soglia e aggiornamento dell'immagine di riferimento.
- Sensibilità a piccoli oggetti, movimenti lenti, rumore e variazioni di luce.
- Costo del confronto sull'ESP32.
- Età del risultato conservato sul server ed eventuali aggiornamenti periodici obbligatori.

La fattibilità e la presenza di meccanismi analoghi nel codice e nella letteratura devono ancora essere verificate.
