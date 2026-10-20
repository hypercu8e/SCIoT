# FOMO con early exiting: spiegazione e valutazione per SCIoT

Discussione documentata il 20 ottobre 2026. È un approfondimento del **tema 6**
del [catalogo delle tesi](TEMI_DI_TESI_E_RICERCA.md#21-uscite-anticipate-sul-microcontrollore).
Lo stato è **proposta da discutere con il relatore**: nessuna uscita aggiuntiva
è stata implementata o addestrata e nessun beneficio è stato misurato.

## 1. Il paper da studiare

Il riferimento individuato nel repository è **Yoshitomo Matsubara, Marco Levorato
e Francesco Restuccia, “Split Computing and Early Exiting for Deep Learning
Applications: Survey and Research Challenges”**:

- [PDF locale](papers/matsubara_csur2023_split_computing_survey.pdf).
- [Testo estratto](papers/matsubara_survey.txt).
- [Fonte arXiv](https://arxiv.org/abs/2103.04505).

È un survey generale di split computing ed early exiting, utile per capirne
le categorie; non è una tassonomia dedicata esclusivamente al multi-device.
La copia locale è il preprint v4 del 25 marzo 2022, associato al lavoro
successivamente pubblicato in ACM Computing Surveys nel 2023.

Vale la pena leggerlo tutto in due passaggi. Per la prima lettura:

1. Introduzione e concetti di base: problema, calcolo locale, comunicazione,
   latenza ed energia.
2. Sezione 4, **Split Computing: A Survey**, con attenzione alla Figura 2:
   partizionamento senza modificare il modello e approcci con bottleneck.
3. Sezione 6, sfide di ricerca e valutazione in condizioni realistiche.
4. Sezione 5, early exiting: prima comprenderne il meccanismo, poi approfondire
   architetture e metodi di addestramento se questa direzione viene scelta.

Non serve memorizzare ogni lavoro o comprendere ogni formula al primo giro.
Una domanda utile è: «Cosa cambia quando più dispositivi condividono rete e
server?». Le parti specifiche multiutente sono raccolte anche nella
[guida bibliografica](LETTERATURA_E_PAPER_SCIOT.md).

## 2. Architettura, addestramento e software di esecuzione

Una rete ordinaria produce una previsione attraverso la sua uscita finale.
L'early exiting aggiunge **teste intermedie**, cioè piccoli rami che trasformano
le caratteristiche già calcolate in una previsione utilizzabile.

```text
Input → Prima parte → Caratteristiche → Parte restante → Uscita finale
                            ↓
                    Uscita anticipata
```

Le teste aggiuntive richiedono addestramento. Il software applica invece la
regola di decisione: accetta una previsione anticipata oppure prosegue.
Una probabilità elevata espressa dalla rete è una stima di confidenza e può
essere errata; la regola va calibrata e valutata su dati distinti.

| Componente | Responsabilità |
|---|---|
| Architettura | Rendere disponibili uscite prima della fine del modello |
| Addestramento | Fare apprendere alle nuove teste il compito richiesto |
| Software di esecuzione | Scegliere l'uscita ed evitare davvero il calcolo successivo |

Lo split computing sceglie **dove eseguire** le parti della rete. L'early
exiting sceglie **fino a dove eseguirla** per un input. Le due tecniche possono
essere combinate: risultato locale per i casi accettati, completamento sul
server per gli altri.

## 3. Cosa abbiamo verificato sul FOMO disponibile

È stato ispezionato l'attributo `model_config` del `model.h5` contenuto in
`ei-object-detection-with-fomo---bottles-vs.-cans-object-detection-keras-h5-model-model.5.zip`.
Questo è il candidato degli esperimenti di compressione, distinto dal modello
RGB originariamente incluso nel framework.

Il grafo Keras è `Functional`, con 60 layer inclusa l'InputLayer,
un ingresso `input_1` e **una sola uscita dichiarata**, `softmax`.
La sua terminazione è:

```text
block_6_expand_relu → head → logits → softmax
                     Conv2D  Conv2D
                     32      3 canali
```

La testa usa convoluzioni 1×1. Non sono presenti teste di predizione anticipate
nel grafo ispezionato. I rami residui del backbone e gli eventuali tensori
intermedi esposti dal partizionamento non costituiscono uscite anticipate.
Questa è una verifica statica della configurazione, non un nuovo benchmark.

FOMO produce una griglia di probabilità delle classi e dello sfondo, dalla quale
si ricavano rilevamenti e centroidi. La [documentazione Edge Impulse](https://docs.edgeimpulse.com/studio/projects/learning-blocks/blocks/object-detection/fomo)
descrive un backbone MobileNetV2 troncato e una testa convoluzionale,
personalizzabili nel punto di taglio e nella capacità della testa.

## 4. Come costruire una variante con early exiting

L'estensione può partire dai pesi esistenti. Un primo esperimento circoscritto
aggiungerebbe **una sola testa**, confrontando al massimo due posizioni candidate.
Si possono inizialmente mantenere fissi i pesi originali e addestrare soltanto
il ramo aggiuntivo; un eventuale addestramento congiunto sarebbe un passo successivo.

Una testa FOMO intermedia deve produrre una mappa di rilevamento. Se cambia
la risoluzione spaziale delle caratteristiche, occorre adattare la costruzione
dei bersagli di addestramento e il postprocessing dei centroidi. I pesi della
testa finale non possono essere semplicemente copiati assumendo che funzionino
su caratteristiche diverse.

L'uscita va collocata dopo un prefisso con tutte le dipendenze necessarie.
`block_2_add` è un candidato già studiato per lo split, non un punto dimostrato
ottimale per l'early exiting: un buon confine di trasmissione non garantisce
caratteristiche sufficienti per una buona previsione locale.

Il runtime deve eseguire prefisso, testa e decisione, quindi eventualmente
continuare con il suffisso riutilizzando le caratteristiche. Un modello esportato
con più uscite non garantisce da solo l'interruzione anticipata: vanno controllati
il piano di esecuzione, la durata dei buffer, le copie e il costo degli interpreti.
La conversione e la quantizzazione della nuova testa devono essere verificate
anche per la qualità della decisione, oltre che per la compatibilità degli operatori.

## 5. Le due varianti da distinguere

| Variante | Risposta anticipata | Vantaggio possibile | Rischio principale |
|---|---|---|---|
| Rilevamento completo | Classi e posizioni degli oggetti | Risolve localmente anche immagini con oggetti | Testa e criterio di affidabilità più complessi |
| Riconoscimento di immagini vuote | Nessun oggetto d'interesse | Evita il completamento per scene vuote | Scambiare un oggetto difficile per sfondo |

Per il rilevamento completo, trovare un oggetto con alta confidenza non dimostra
di aver trovato tutti gli altri. Mediare la confidenza su tutte le celle può
essere ingannevole perché molte rappresentano sfondo. Servono misure di oggetti
persi, falsi rilevamenti e posizione, anche con occlusioni, oggetti piccoli,
variazioni di luce e scene con più oggetti.

Per le immagini vuote serve calibrare il rischio di dichiarare vuota una scena
che contiene oggetti. La convenienza dipende anche dalla frequenza di queste
immagini nell'uso reale. Questa variante usa caratteristiche neurali già
calcolate; il filtro leggero sui pixel del tema 3 è un'altra strategia da
considerare eventualmente come confronto.

### Precedente pertinente: BlankSkip

[Carlo Marra et al., “BlankSkip: Early-exit Object Detection onboard Nano-drones”](https://arxiv.org/abs/2603.28149),
presentato all'Embedded Vision Workshop di CVPR 2026, introduce un compito
ausiliario per riconoscere immagini senza oggetti d'interesse. Gli esperimenti
usano MobileNet-SSD e una piattaforma nano-drone con microcontrollore GAP8.

È un precedente per la variante delle immagini vuote, non una verifica di
FOMO su ESP32 o di SCIoT multi-client. La ricerca svolta per questa discussione
non è una revisione sistematica: non dimostra l'assenza di altri lavori o di
precedenti specifici su FOMO. Il contributo SCIoT va definito rispetto alla
letteratura, senza presumere novità dalla sola assenza di codice nel repository.

## 6. Valutazione tecnica e prima prova proposta

La fattibilità di aggiungere il ramo è plausibile. La convenienza resta incerta:
FOMO è già leggero; un ramo precoce può sbagliare troppo e uno tardivo può
risparmiare poco. Inoltre il ramo aggiuntivo viene pagato anche dai casi che
proseguono sul server. Il beneficio può includere trasmissione e attesa evitate,
oltre al calcolo risparmiato.

Il perimetro proposto è:

1. Fissare modello, ordine delle classi, preprocessing e dati annotati.
   Separare addestramento, calibrazione del criterio e test; evitare che frame
   quasi identici della stessa sequenza contaminino le partizioni.
2. Addestrare una sola testa su PC e misurare la curva tra quota di uscite
   accettate e qualità dei rilevamenti, contando anche il costo della testa.
3. Confrontare FOMO originale locale, invio dell'immagine al server, split senza
   uscita, split con uscita e un FOMO statico più piccolo quando fattibili.
   Identificare esplicitamente i casi che non entrano in memoria sul dispositivo.
4. Se il risultato è promettente, esportare la variante e verificare su ESP32
   correttezza, memoria, tempi e vantaggio completo, inclusi i casi che proseguono.
5. Solo dopo, valutare più client: traffico, coda e latenza per dispositivo.
   Usare stato e risposte correttamente isolati, senza assumere che l'early
   exiting risolva da solo la gestione della concorrenza.

La [raccolta pubblica già documentata](experiments/activation_compression/public_pc_2026-10-18/README.md)
include 84 fotografie annotate di test, ma non costituisce un set di
addestramento già pronto. I confronti registrati riguardano soprattutto fedeltà
tra modelli; non applicano il postprocessing FOMO né misurano accuratezza
completa rispetto alle annotazioni. L'ordine delle classi dell'H5 resta da
confermare. Servono dati e protocollo adeguati prima di promettere risultati.

Il criterio per proseguire deve essere concordato: una quota utile di inferenze
risolte localmente entro un limite sugli errori, con un risparmio che compensi
testa, decisione e gestione dei buffer. Non viene fissata una percentuale di
miglioramento priva di misure. Un risultato negativo può delimitare quando
questa architettura non conviene, senza diventare automaticamente sufficiente
per qualunque requisito di tesi.

## 7. Valutazione come proposta al professore

Gli [appunti del tirocinio](SCALETTA_TIROCINIO.md#contesto) riportano interesse
del docente per comunicazione di rete e limite del singolo client. Un'uscita
locale è collegabile a questi obiettivi se riduce richieste e traffico verso
il server condiviso. Studiare soltanto l'accuratezza di una nuova architettura
sposterebbe maggiormente il lavoro verso il machine learning.

**Valutazione progettuale:** è ragionevole proporre una verifica preliminare
circoscritta; per sceglierla come asse principale della tesi servono prima dati
utilizzabili, qualità della testa e un margine di risparmio credibile.
Questo giudizio non è una previsione certa della decisione del docente e
non sostituisce l'accordo su obiettivi, priorità e criteri di completamento.

Possibile formulazione da presentare personalmente:

> Vorrei verificare se una singola uscita anticipata aggiunta a FOMO può ridurre
> l'offloading in SCIoT, mantenendo un limite sugli errori di rilevamento.
> Partirei da una prova su PC; se il compromesso è promettente, misurerei costi
> e benefici su ESP32 e poi con più client. Possiamo concordare questa verifica
> preliminare e i criteri per decidere se proseguire?

Il [catalogo](TEMI_DI_TESI_E_RICERCA.md#6-perimetro-consigliato-e-criteri-di-valutazione)
mantiene come prima proposta il lavoro multi-client. L'approfondimento su
early exiting documenta un'alternativa, senza registrare una scelta definitiva
o un'approvazione del relatore.
