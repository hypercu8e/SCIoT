# Skip dei frame su HTTP persistente | 18 novembre 2026

Lo skip confronta l’input INT8 appena acquisito con quello dell’ultimo frame
selezionato e confermato dal server. Su un frame simile evita il prefisso
sulla ESP32, la richiesta HTTP e il suffisso sul server. La camera viene
riattivata e acquisisce un frame a ogni iterazione. Il rinnovo è verificato
sui timestamp dei frame, quindi scatta alla prima acquisizione utile.

## Replay

Il replay usa il prefisso INT8 no-PAD e il suffisso INT8 del server. I due
campionamenti di `VideoWithCan.mp4` hanno periodo 710 ms e offset di 0 e 355 ms.
La baseline rileva rispettivamente 9 intervalli di presenza per classe su 42
frame e 10 su 41. Il decoder FOMO usa soglia 0,5.

| Politica | Skip con offset 0 / 355 ms | Eventi persi con offset 0 / 355 ms |
|---|---:|---:|
| Ogni 2 frame | 21/42 · 20/41 | 1/9 · 0/10 |
| Ogni 3 frame | 28/42 · 27/41 | 0/9 · 3/10 |
| Globale 8, rinnovo 1,5 s | 15/42 · 14/41 | 0/9 · 0/10 |
| Globale 32, rinnovo 1,5 s | 27/42 · 26/41 | 0/9 · 1/10 |
| Globale 32, rinnovo 5 s | 34/42 · 32/41 | 6/9 · 7/10 |

Con offset zero, la soglia 32 e rinnovo 1,5 s conserva tutti gli eventi,
con ritardo di ingresso massimo di 1,43 s. A parità di 15 invii,
la distribuzione uniforme perde un evento. Sul campionamento a 355 ms
la stessa soglia perde un evento. La soglia 8 a 1,5 s conserva
tutti gli eventi nei due replay e riduce gli invii di circa un terzo.
I confronti sono con l’inferenza completa del modello sullo stesso video.

Report completi nella cache locale del benchmark.
[Report replay a offset 0](../results/frame-skip-replay-710ms-offset0/report.md) ·
[Report replay a offset 355 ms](../results/frame-skip-replay-710ms-offset355/report.md)

## Prova sulla ESP32 B

Cinque avvii con lo stesso binario e 100 frame camera per avvio. Client e
server concordano su **5.846 richieste riuscite**, incluse 5.500 richieste
di controllo e 346 richieste camera. L’audit ha verificato le 35 uscite
iniziali e il controllo canonico ogni 100 frame in ogni avvio. Le prove
usano scene riprese in momenti diversi. I risultati di qualità si
confrontano sullo stesso insieme di frame all’interno di ciascuno shadow.

| Avvio | Rinnovo | Richieste camera | Skip simulati | Ciclo p50 / p95 (ms) | Riuso TCP dopo skip |
|---|---:|---:|---:|---:|---:|
| Baseline | – | 100/100 | – | 725,8 / 772,5 | – |
| Shadow, soglia globale 32 | 1,5 s | 100/100 | 52/100 | 723,0 / 811,8 | – |
| Attivo, soglia globale 32 | 1,5 s | 34/100 | – | 602,7 / 778,9 | 32/32 |
| Shadow, soglia globale 32 | 5 s | 100/100 | 85/100 | 723,3 / 787,3 | – |
| Attivo, soglia globale 32 | 5 s | 12/100 | – | 602,4 / 744,7 | 11/11 |

L’acquisizione resta intorno a 601 ms di mediana in tutti gli avvii.
La decisione richiede circa 0,63 ms di mediana nelle modalità con
confronto. I due avvii attivi riducono i byte dei corpi HTTP dei frame
del 66% e dell’88%. Uvicorn e il client confermano una sola connessione
TCP per le richieste di inferenza in ogni avvio. Con keep-alive a 10 s,
il rinnovo a 5 s mantiene la connessione anche quando il divario tra
i timestamp di due frame inviati raggiunge 5,58 s.

### Rilevazioni sugli stessi frame

Nel primo shadow, la soglia 32 e rinnovo 1,5 s selezionano 48 frame su 100
e perdono 5 dei 13 intervalli FOMO, contro 4 persi dall’invio uniforme a
48 richieste. Al frame 16 il FOMO rileva un oggetto per un singolo frame
e la differenza globale è 27. L’invio uniforme lo include e lo skip lo
perde. Al frame 46 il rinnovo seleziona invece una comparsa di un solo
frame esclusa dall’invio uniforme. Tra gli intervalli conservati, il
ritardo massimo osservato è di 0,75 s in ingresso e 1,45 s in uscita.

Nel secondo shadow il FOMO non osserva intervalli di presenza.
La sequenza misura quante richieste evita il rinnovo a 5 s sulla scena
acquisita. Nel replay, quel rinnovo perde 6 e 7 intervalli sulle due fasi
di campionamento. La soglia 8 con rinnovo a 1,5 s resta la candidata da
verificare sulla camera per conservare più eventi. L’esperimento,
complessivamente, dimostra la riduzione degli invii e il riuso TCP.
Sul primo shadow l’invio uniforme perde meno eventi allo stesso budget.

Flash originale ripristinata e verificata su tutti gli 8 MiB. Boot
originale confermato e server sperimentale chiuso. Build ESP32 riuscito
e 47 test passati.

[Audit della prova sulla B](../results/FRAME_SKIP_B_01/frame-skip-summary.json) ·
[Esito del ripristino](../results/FRAME_SKIP_B_01/completion.json).
