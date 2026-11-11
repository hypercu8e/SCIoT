# Filoni di ottimizzazione software SCIoT

Aggiornamento: 10 novembre 2026. Le direzioni proposte non sono vantaggi già dimostrati né dichiarazioni di novità scientifica; gli esiti misurati sono distinti sotto.

**Profilazione completata:** [11 operatori del prefisso](experiments/esp32_layer_profile/2026-11-10/report.md),
93,762 ms in modalità normale, strumentazione +0,119%. Prima convoluzione
25,0%, espansione 1×1 19,2%, PAD 15,6%. Il PAD è un candidato concreto per
la prossima ottimizzazione; nessuna modifica dei kernel ancora eseguita.

**Chiusura concordata, 10 novembre:** filone LUT considerato concluso per
l'obiettivo attuale: beneficio locale e equivalenza numerica verificati,
vantaggio end-to-end misurato nei confronti. Timeout probabilmente legato al
percorso sperimentale Pixel/ADB, senza causa isolata. Nessun nuovo test di rete
programmato; l'ora interrotta resta dichiarata come tale. Integrazione nel
client operativo non eseguita.

**Ultimo esito 10 novembre:** [confronto lungo originale/LUT](experiments/esp32_input_camera_benchmark/2026-11-10/lut-hold-full-report.md)
supera i criteri individuali (ciclo mediano -27,2%) e il confronto simultaneo,
ma l'ora si interrompe dopo circa 34 minuti per HTTP 408 su A. Replay esatto
di 23.829 risposte riuscite; causa del timeout non isolata. La proposta di
diagnostica aggiuntiva è stata accantonata nella chiusura concordata sopra.

**Aggiornamento 10 novembre:** [screening HTTP breve](experiments/esp32_input_camera_benchmark/2026-11-10/report.md)
completato, 1.520 risposte fra riferimento e varianti con replay esatto e zero
408. La sola LUT con buffer trattenuto è promettente sul ciclo completo;
il rilascio anticipato peggiora la freschezza nelle prove brevi. Trasporto
variabile, causa dei precedenti 408 non isolata. Nessuna promozione: il confronto
HTTP completo, la conferma su due schede e l'ora della variante restano da fare.

## Punto di partenza misurato

La [campagna con due ESP32](experiments/multiclient_hardware/2026-11-09-pixel-adb-full/report.md) usa INT8, ESP-NN, split `block_2_add`, HTTP v2 con connessione ricreata per richiesta, un worker e un thread. La rete è hotspot Pixel + USB/ADB reverse: i risultati non rappresentano qualsiasi access point.

Dai log dell'ora, mediane per scheda in ms:

| Fase | A | B |
|---|---:|---:|
| Acquisizione/attesa frame | 71,447 | 72,602 |
| Preprocessing RGB565 → float | 8,100 | 8,100 |
| Preparazione input INT8 | 38,631 | 38,530 |
| Prefisso | 94,803 | 94,828 |
| Preparazione messaggio | 1,055 | 1,055 |
| Scambio HTTP | 30,504 | 31,185 |
| Ciclo | 244,916 | 246,768 |

Le mediane delle fasi non sono additive. La mediana di ciclo meno HTTP, calcolata su ogni frame, è 214,394/215,467 ms. La coda server p95 è circa 0,1 ms. Il ciclo parte prima di richiedere il framebuffer: non misura da solo l'età del frame.

## Catalogo operativo

| Filone | Domanda / primo esperimento | Metriche e vincoli | Stato |
|---|---|---|---|
| 1. Conversione input | RGB565 → INT8 mediante tabella, evitando float e double per ogni pixel | Identici byte sullo stesso frame, tempi, memoria e startup | Implementato; correttezza e tempi locali verificati |
| 2. Acquisizione camera | Restituire il buffer dopo conversione per consentire acquisizione durante il lavoro successivo; grayscale nativo separato | Attesa, età del frame, FPS, stabilità; grayscale richiede successiva verifica qualità | Implementato; compromesso FPS/età misurato localmente |
| 3. Memoria | Misurare buffer critici in RAM interna rispetto a PSRAM | Latenza, memoria minima e stabilità Wi-Fi/camera | Proposta |
| 4. Profilazione layer | Attribuire i ~95 ms del prefisso a operatori e copie | Tempi per operatore, kernel effettivamente usati | Completata su B, input fissi; [report](experiments/esp32_layer_profile/2026-11-10/report.md) |
| 5. Pipeline | Sovrapporre inferenza e invio con proprietà dei buffer esplicita | FPS, latenza, età, RAM e contesa | Proposta; distinta dal rilascio anticipato camera |
| 6. HTTP persistente | Confrontare riuso della connessione e apertura per richiesta | p50/p95/p99, riconnessioni e ciclo completo | Proposta |
| 7. Split statici alternativi | Confrontare pochi tagli validi sulla scheda | Calcolo, byte, RAM e latenza completa | Proposta |
| 8. Selezione frame | Evitare prefisso e invio per frame ridondanti | Eventi persi, ritardo, qualità, traffico e FPS utili | Proposta; vedi [temi](TEMI_DI_TESI_E_RICERCA.md) |
| 9. Compilazione specifica | Generare esecuzione e riuso memoria per modello/split, con ESP-NN | Equivalenza, RAM, flash e tempi contro TFLM + ESP-NN | Proposta; [precedente EON](experiments/eon_prefix_benchmark/README.md) |
| 10. Frequenza adattiva | Assegnare budget prima del prefisso sotto congestione controllata | Freschezza nel tempo, equità, risultati utili, latenza e traffico | Proposta; prima serve un banco di congestione |

## Primi due filoni

[Esperimento, riproduzione e criteri di selezione](experiments/esp32_input_camera_benchmark/README.md).

Modello e split restano congelati. Per RGB565 si richiede equivalenza numerica; il grayscale nativo resta esplorativo fino a una valutazione su scene annotate. Ottimizzare le conversioni è distinto dal migliorare i kernel di inferenza.

[Stato delle prove fisiche del 9 novembre](experiments/esp32_input_camera_benchmark/2026-11-09/report.md).

Esito dei primi due filoni: conversione da circa 47 a 1,3 ms; combinazione LUT + rilascio anticipato da circa 195 a 98 ms e da 5,00 a 9,62 attivazioni/s, **solo sul prefisso locale senza HTTP**. La conferma del servizio completo è sospesa per HTTP 408 riprodotto anche con il vecchio firmware. Il grayscale resta esplorativo.
