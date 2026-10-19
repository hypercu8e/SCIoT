# Prova client–server TCP — 18 ottobre 2026

Due processi distinti sullo stesso PC: il client riproduce le attivazioni salvate
del video; il server ricostruisce il tensore ed esegue il suffisso Keras dopo
`block_2_add`. Si confrontano raw float32, compressione indipendente e temporale
a passo `0,001`. Queste ultime riusano il codec sperimentale del 17 ottobre.
Non è un'integrazione nel server/firmware SCIoT né una replica del paper D+DZ.

## Risultato

146 frame a campionamento 5 fps, tre ripetizioni per metodo; prima del frame 73
si chiude volontariamente la connessione dopo l'ultima risposta e se ne apre
una nuova. Ogni connessione crea encoder e decoder nuovi, con primo completo e
sequenza zero. Il replay procede senza attese: 5 fps non è un throughput misurato.

| Metodo | Byte client → server | Risparmio sul raw | Mediana dei tre p50 di codifica + RTT |
|---|---:|---:|---:|
| Raw | 2.696.760 | 0% | 0,673 ms |
| Indipendente | 1.602.438 | 40,58% | 1,181 ms |
| Temporale | 1.385.197 | 48,63% | 1,483 ms |

Il temporale risparmia **13,56% rispetto all'indipendente** a identica
ricostruzione. Il server invia anche 261.146 byte per ciascun metodo e giro:
griglia completa dell'uscita, hash del tensore e metadati di risposta.
I conteggi includono handshake, frame, risposte e prefissi di lunghezza da 4 byte;
escludono header TCP/IP, ACK TCP, ritrasmissioni e chiusura.

Sul loopback di questo PC il risparmio di byte non compensa il lavoro del codec:
raw è più veloce. Non dimostra cosa succeda su ESP32 o su una rete limitata.
I tempi escludono caricamento/compilazione iniziale del modello, handshake,
camera, inferenza del prefisso, lettura dei file e verifiche del client.
Comprendono codifica, scambio, decodifica, inferenza del suffisso e risposta.

## Verifiche

- 1.314 richieste verificate: 146 frame × 3 metodi × 3 giri, 18 connessioni.
- Hash del tensore ricostruito verificato a ogni risposta; il server riceve solo
  il modello e i messaggi, senza accesso ai file delle attivazioni originali.
- Uscite raw confrontate con l'estrazione (`rtol=1e-5`, `atol=1e-6`).
- Indipendente e temporale producono uscite identiche byte per byte in ogni giro.
- Nessuna cella cambia a soglia 0,5 rispetto al raw nel campione: è accordo con
  il modello, senza annotazioni né valutazione dell'accuratezza reale.
- I 20 test includono framing, limiti di lunghezza, rifiuto del modello errato,
  checksum, sequenze e replay TCP con riconnessione.
- Audit separato di conteggi CSV/JSON, sequenze e hash dei sorgenti archiviato.

La riconnessione prova il rinnovo dello stato tra frame confermati; non prova
recupero automatico, disconnessione durante un messaggio o perdita reale di rete.
I test del codec precedente coprono separatamente il riferimento mancante.
La prima prova con perdita del 17 ottobre usava attivazioni rigenerate con hash
diverso: questi numeri identificano una nuova esecuzione sugli input locali
`results/input`, non una ripetizione byte per byte di quel report.

## Esecuzione

Ambiente esistente: Python 3.11, NumPy 1.26.4, TensorFlow 2.15.0; nessuna nuova
dipendenza. Dalla radice, con `results/input` generato secondo il README principale:

```bash
.venv/bin/python experiments/activation_compression/socket_benchmark.py run \
  --input-dir experiments/activation_compression/results/input \
  --output-dir experiments/activation_compression/results/tcp_nuova_prova \
  --rounds 3 --reconnect-at 73

.venv/bin/python -m unittest discover -s experiments/activation_compression -p 'test_*.py' -v
```

`run` avvia il server come processo figlio su una porta loopback disponibile,
ruota l'ordine dei metodi a ogni giro e termina il server anche in caso di errore.
I risultati generati rimangono sotto `results/`, ignorata da Git. Gli input grandi
NPY e il modello non sono duplicati qui; sono identificati dagli hash nel JSON.
Il processo TensorFlow deve poter aprire socket TCP locali nell'ambiente usato.

Per usare due terminali, nel primo:

```bash
CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=3 TF_ENABLE_ONEDNN_OPTS=0 \
  .venv/bin/python experiments/activation_compression/socket_benchmark.py server \
  --model experiments/activation_compression/results/input/model.h5 --port 8765
```

Nel secondo:

```bash
.venv/bin/python experiments/activation_compression/socket_benchmark.py client \
  --input-dir experiments/activation_compression/results/input \
  --method temporal --port 8765 --reconnect-at 73
```

Il server predefinito ascolta soltanto su `127.0.0.1`. Il protocollo sperimentale
prevede un solo client alla volta e uno split fisso, senza autenticazione.
La verifica automatica delle uscite raw e dell'identità tra metodi è in `run`;
il comando `client` verifica l'hash dei tensori ricevuti dal server.

## Artefatti

- [report.md](report.md): tempi di ciascuna ripetizione e limiti della misura.
- [summary.json](summary.json): metriche, hash, ambiente e identità dei processi.
- [frames.csv](frames.csv): conteggi e tempi di ogni richiesta.
- [verification.json](verification.json): audit indipendente dei conteggi e degli hash.
- [tests.txt](tests.txt): esito dei test.

Per la provenienza e le istruzioni dell'estrazione vedere
[README degli esperimenti](../README.md). DPCM e dead-zone del paper di Shiba
restano un'ulteriore modalità da implementare; questa prova misura il nostro
prototipo con quantizzazione uniforme del tensore e differenze intere esatte.
