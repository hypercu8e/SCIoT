# SCIoT: dettagli implementativi

*Complemento di [SPIEGAZIONE_LAVORO.md](SPIEGAZIONE_LAVORO.md). Quel file racconta **cosa** abbiamo misurato; questo spiega **come** funziona il codice.*
*I percorsi dei file partono dalla radice del repository.*

---

## 0. Come è organizzato il codice

Ci sono due "mondi" separati: è una distinzione importante da avere chiara.

| Mondo | Dove | Cosa contiene |
|---|---|---|
| **SCIoT originale (legacy)** | `src/server/` (edge, communication, offloading_algo), `src/client/esp32-s3-eye-{http,mqtt,websocket}` | Server e client float32 originali, con l'algoritmo che sceglie lo split. Abbiamo corretto tre bug nei client, ma l'architettura è rimasta quella |
| **Servizio HTTP v2 multi-client** | `src/server/multiclient/`, `src/client/esp32-s3-eye-multiclient/` | Il nuovo servizio INT8 con stato per dispositivo. È il "client operativo" |
| **Esperimenti** | `experiments/<nome>/` | Un progetto isolato per ogni esperimento: firmware ESP-IDF in `idf/`, `run.py` (campagna), `analyze.py` (analisi), test, report datati |

**Le ottimizzazioni sul ciclo camera vivono solo nei firmware sperimentali.** Parliamo di LUT, PAD veloce, prefisso senza PAD, strisce ESP-NN, allocazione anticipata, gestione di XCLK, keep-alive e frame skip. Il firmware più completo è `experiments/esp32_websocket_benchmark/idf/src/`. Nessuna di queste è ancora stata portata nel client operativo `src/client/esp32-s3-eye-multiclient`: è uno dei prossimi passi.

### Come gira una campagna sperimentale (schema uguale in tutti gli esperimenti)
1. `run.py` compila il firmware con PlatformIO / ESP-IDF 5.4 e legge il MAC della scheda.
2. Fa il **backup completo della flash da 8 MiB** con esptool, poi carica il firmware sperimentale.
3. Lancia le fasi tramite comandi sulla seriale (per esempio `g` per 1.000 frame, `x` per la diagnostica di XCLK) e avvia il server di prova.
4. Il firmware stampa una riga JSON per ogni evento (`{"event":"sample",...}`, `memory`, `frame_policy`...). Il runner salva log seriale e log del server.
5. In un blocco `finally` ripristina la flash originale, ne verifica il digest e controlla il boot originale.
6. `analyze.py` ricalcola le statistiche dai log grezzi, applica i criteri fissati prima e scrive `summary.json` e `report.md`.

I componenti esterni (TFLite Micro, ESP-NN, esp32-camera) sono **congelati**: una copia locale con hash SHA-256 verificati (`frozen-components-sha256.json`). Ogni cambiamento è quindi esplicito e riproducibile.

---

## 1. SCIoT originale: come sceglie lo split

File: `src/server/offloading_algo/offloading_algo.py`.

Per ogni possibile layer di taglio `L` stima un costo:

```
costo(L) = Σ tempi_dispositivo[0..L]  +  dimensione_output[L] / velocità_media  +  Σ tempi_server[L+1..N]
```

e sceglie il layer con il costo minore (`static_offloading`). Valuta anche i casi "tutto sul dispositivo" e "tutto sul server", ma il secondo non entra nella scelta.

**I limiti trovati:**
- i tempi sono medie globali, condivise tra **tutti** i client (file `device_inference_times.json` / `edge_inference_times.json`);
- la stima non tiene conto del carico del server;
- un taglio arbitrario su FOMO può richiedere più tensori (rami residui), mentre il protocollo ne invia uno;
- le attivazioni viaggiano in float32 e il client manda anche l'immagine.

**I bug corretti nei client legacy il 19 ottobre** (`experiments/firmware_fixes_2026-10-19/`):
- l'interprete TFLite aveva una durata non valida: un oggetto locale veniva usato dopo la fine della funzione;
- la serializzazione degli identificativi era sbagliata;
- le lunghezze dei tempi inviati erano incoerenti.

In più il buffer del messaggio è sceso da 922.253 a 461.261 byte di PSRAM. Abbiamo verificato tutto sul PC eseguendo le stesse funzioni C++ con TFLite Micro: 1.170 invocazioni identiche al riferimento, nessun errore con AddressSanitizer e UBSan.

---

## 2. Modello e split

- **Modello:** FOMO "Beer vs cans" da Edge Impulse (`.h5` nella radice del repo). Ingresso 96×96×1 in grigio, uscita 12×12×3 (sfondo e due classi). Ogni cella della griglia copre 8×8 pixel.
- **Split `block_2_add`:** il prefisso ha 11 operatori, fino alla somma residua del secondo blocco. Il confine è un solo tensore 24×24×8, cioè 4.608 valori.
- **Quantizzazione INT8** (`experiments/activation_compression/int8_2026-10-18/`): conversione con il TFLite Converter. La calibrazione usa 48 frame del video, la valutazione altri 98. Ogni tensore ha `scale` e `zero_point`, con `valore_reale = (q - zero_point) * scale`.
- **Taglio del binario INT8** (`esp32_prep_2026-10-19`): abbiamo diviso il `.tflite` INT8 già salvato in prefisso (16.400 B) e suffisso (41.168 B), **senza riconvertire**, quindi con gli stessi pesi e parametri. Abbiamo verificato byte per byte che `prefisso → suffisso` coincida con il modello intero su 146 frame.
- **Il prefisso è compilato nel firmware** come array C (`include/generated/*.h`). Lo SHA-256 del modello serve al client per registrarsi al server, che rifiuta un modello diverso con 422.

**Profilo del prefisso INT8 su ESP32** (93,8 ms in totale, arena in PSRAM):

| # | Operatore | Uscita | ms | Quota |
|---:|---|---|---:|---:|
| 0 | CONV 3×3 stride 2 | 48×48×16 | 23,4 | 25% |
| 1 | DEPTHWISE | 48×48×16 | 8,6 | 9% |
| 2 | CONV 1×1 | 48×48×8 | 3,8 | 4% |
| 3 | CONV 1×1 espansione | 48×48×48 | 18,0 | 19% |
| 4 | **PAD** | 49×49×48 | **14,6** | **16%** |
| 5 | DEPTHWISE stride 2 | 24×24×48 | 9,5 | 10% |
| 6–10 | conv 1×1, espansione, depthwise, conv 1×1, ADD | 24×24×… | ~15,8 | ~17% |

Il profilo è misurato con un wrapper che registra un timer per ogni nodo (`kernel_probe.cpp`). La strumentazione costa lo +0,12%.

---

## 3. INT8 + ESP-NN: perché è 5× più veloce

- **ESP-NN** è la libreria di Espressif con kernel scritti in assembly per le istruzioni SIMD (vettoriali) dell'ESP32-S3. TFLite Micro li usa **solo per tensori INT8**. In float32 tutto passa dai kernel di riferimento in C.
- Abbiamo verificato che i kernel ottimizzati vengano davvero chiamati con dei **wrapper contatori** sui kernel di convoluzione e depthwise. Sul prefisso INT8 risultano 6 convoluzioni e 3 depthwise ottimizzate, sul FLOAT32 zero.
- **Il risultato:** il prefisso scende da 814 a 95 ms. Inoltre i byte da inviare sono 4 volte meno (1 byte per valore invece di 4).

---

## 4. Protocollo e server HTTP v2 multi-client

Codice: `src/server/multiclient/`, con `service.py` (logica), `http.py` / `websocket.py` (trasporti), `engine.py` (suffisso), `protocol.py` (formato), `fomo.py` (decodifica dei box).

### Formato dei messaggi (`protocol.py`)
- **Richiesta SCB1:** 32 byte di header (`<8I`: magic, versione, dtype, frame, iterazione, immagine, dimensione, **CRC32**) seguiti da 4.608 byte INT8. In totale **4.640 B**.
- **Risposta SCR1:** 32 byte di header (con i tempi di decodifica, invoke e post-processing in µs) seguiti da 432 float32, cioè i punteggi 12×12×3.
- Il server controlla dimensione, magic, dtype e CRC prima di accettare.

### API
1. `POST /api/v2/registration` con `{"client_id": "eye-<MAC>", "model_sha256": ...}`. Risponde con `session_id` (un UUID), split, dtype e scadenze.
2. `POST /api/v2/infer` con gli header `X-Client-ID`, `X-Session-ID`, `X-Request-ID` (contatore crescente) e `X-Model-SHA256`.

### Stato e ammissione (`service.py`)
- Un dizionario `clients[client_id]` tiene, per ogni dispositivo, sessione, ultimo request-ID e **al massimo un lavoro pendente**.
- `reserve()` controlla nell'ordine:
  1. sessione valida, altrimenti **410**;
  2. modello uguale, altrimenti **422**;
  3. request-ID maggiore del precedente e nessun lavoro pendente, altrimenti **409**;
  4. capienza, altrimenti **429**. Al massimo 8 corpi in ricezione contemporanea e una coda FIFO lunga al massimo 8.
- **Scadenze:** 3 s per ricevere il corpo (altrimenti **408**), 10 s in totale (altrimenti **504**).
- **Worker:** ogni worker è un thread dedicato (`ThreadPoolExecutor(max_workers=1)`) con il **suo** interprete TFLite. Crea, riscalda e invoca il modello sempre nello stesso thread. Tutto lo stato vive su un unico loop asyncio, quindi non servono lock.
- **Protezione dalle risposte tardive:** quando un lavoro termina, `release()` controlla che `client.pending is job`, confrontando l'identità dell'oggetto. Così un lavoro vecchio, per esempio di una sessione sostituita dopo un riavvio, non può liberare quello nuovo.
- Ogni evento finisce in `server.jsonl` (reserved, admitted, worker_started, terminal…). È da lì che ricaviamo i tempi di coda e di elaborazione.

### Suffisso (`engine.py`)
- All'avvio verifica gli hash di prefisso e suffisso e che scala e zero-point del confine coincidano tra le due parti.
- Esegue un'inferenza di riscaldamento.
- Per ogni richiesta: `set_tensor` → `invoke` → dequantizzazione dei punteggi → decodifica FOMO (lo stesso algoritmo dell'SDK Edge Impulse, riscritto in Python e verificato su 250 mappe).

### WebSocket (`websocket.py`)
Usa la **stessa** logica di ammissione. Ogni messaggio ha una busta `SCW1` di 16 byte (magic, versione, tipo, sequenza) seguita dal corpo SCB1. La registrazione avviene come primo messaggio di testo JSON.

### Client operativo (`src/client/esp32-s3-eye-multiclient/src/main.cpp`)
- L'identità viene dal MAC.
- Si registra all'avvio e di nuovo prima di ogni comando.
- Usa un'unica arena INT8 in PSRAM e confronta gli header di correlazione della risposta prima di accettarla.
- Dopo un 429 aspetta 250–500 ms e passa al frame successivo, **senza ritentare** lo stesso frame. Dopo un timeout rinnova la sessione.

### Parallelismo (`experiments/server_parallelism/`)
`--inference-workers N --inference-threads T`. Il motore da solo scala (×3,15 con 4 worker), ma il servizio HTTP no (+2,9%). Uvicorn gira in un solo processo e ricezione, parsing e scrittura sincrona dei log fanno da collo di bottiglia. Il default resta 1×1.

---

## 5. Codec delle attivazioni

### Su PC (`experiments/activation_compression/`)
- **XOR + byte shuffle + zlib:** XOR bit a bit con il frame precedente (reversibile, a differenza della sottrazione float), poi riordino dei byte per posizione (prima tutti i byte 0 di ogni float, poi tutti i byte 1…) per aiutare zlib.
- **Lossy:** si arrotonda a un passo fisso, ottenendo interi. L'indipendente comprime gli interi del frame, il temporale comprime la differenza con i precedenti.
- Il protocollo del prototipo ha header, numeri di sequenza, checksum, un frame completo iniziale e periodico, la scelta del payload più piccolo e il recupero tramite completo.

### Su ESP32: Rice (`experiments/esp32_lossless_codec_benchmark/`)
1. **Residuo:** in modalità indipendente è `q - zero_point`; in modalità temporale è `q - q_precedente_ricostruito`, calcolato in INT16.
2. **ZigZag:** trasforma i residui con segno in numeri senza segno piccoli: `r ≥ 0 → 2r`, `r < 0 → -2r-1`.
3. **Rice con parametro k per canale:** per ognuno degli 8 canali sceglie `k ∈ 0..8` che minimizza il numero **esatto** di bit. I primi 8 byte del payload sono i k.
4. **Codifica di ogni simbolo:** quoziente `v >> k` in unario (tanti zeri, poi un 1), seguito dai k bit bassi.
5. **Regole di sicurezza:**
   - se il risultato non è più piccolo di 4.608 B, si invia raw;
   - un frame completo all'inizio e ogni 30 frame;
   - il riferimento avanza solo dopo l'ACK del server.
6. **Decoder lato server in C++** (estensione nativa): porta la decodifica da circa 12 ms (Python) a 0,4 ms. Un decoder Python indipendente verifica offline tutti i pacchetti.

**Perché funziona:** frame consecutivi simili danno residui piccoli, e la codifica Rice è ottima per numeri piccoli con distribuzione geometrica.
**zlib (miniz)** è stato provato a livello 1: costa 6,8 ms sulla scheda per un guadagno minore.

---

## 6. Ottimizzazioni del ciclo camera (firmware sperimentale)

File principale: `experiments/esp32_websocket_benchmark/idf/src/main.cpp`.

### Il ciclo di un frame
```
acquire frame (RGB565 96×96) → conversione LUT → [frame skip?] → Invoke prefisso
→ copia 4.608 B nel messaggio → exchange HTTP/WS → (ogni 100 frame: controllo canonico)
```
La camera è configurata a 96×96 RGB565 con un solo framebuffer. Il ritaglio e il resize non servono più sulla scheda.

### LUT per l'ingresso
- **Prima:** per ogni pixel si faceva RGB565 → grigio float (BT.601: `0,299·R + 0,587·G + 0,114·B`, con canali normalizzati su 31/63/31), e poi `quantize()`:
  ```cpp
  q = nearbyint(double(value) / kInputScale + kInputZero);  // clamp a [-128,127]
  ```
  La FPU dell'ESP32-S3 è **solo a precisione singola**: il `double` è emulato in software, circa 4 µs per pixel × 9.216 pixel.
- **Dopo:** il pixel RGB565 è un `uint16_t`, quindi esistono solo 65.536 casi. All'avvio:
  ```cpp
  for (p = 0; p < 65536; ++p) rgbLut[p] = quantize(grigio(p));   // 64 KiB in PSRAM, ~327 ms una volta
  ```
  e nel ciclo:
  ```cpp
  image[i] = rgbLut[(buf[2*i] << 8) | buf[2*i+1]];
  ```
  Lo stesso `quantize()` riempie la tabella, quindi l'uscita è **identica per costruzione**. L'abbiamo comunque verificata su tutti i 65.536 colori e sui frame reali.

### PAD veloce (`fast_pad.cpp`)
- In TFLite Micro ogni operatore ha `Init`, `Prepare` ed `Eval`. Registriamo un PAD con `Init` e `Prepare` **originali di TFLM** (stessi parametri, stesso valore di padding = zero-point) e un `Eval` nostro.
- Il nostro `Eval` vale solo nel caso INT8 4D con padding sulle sole H e W. Copia ogni riga con `memcpy` e riempie i bordi, invece di visitare ogni elemento controllando gli indici come `PadImageStyle`. Negli altri casi passa al kernel di riferimento.
- **Modalità di verifica:** esegue anche il kernel di riferimento in un buffer di appoggio e confronta i byte (3,7 milioni di byte confrontati, 0 diversi).
- **Risultato:** da 14,6 a 5,2 ms. Il limite che resta è la banda della PSRAM: la stessa copia in RAM interna costa 0,3 ms.

### Prefisso senza PAD (`make_nopad.py`)
- Il PAD aggiunge una riga in basso e una colonna a destra prima di una depthwise 3×3 stride 2 con padding VALID.
- Su un ingresso 48×48 è **esattamente** ciò che fa la stessa depthwise con padding **SAME**. Lo script riscrive il flatbuffer `.tflite` (schema TFLite) togliendo il nodo 4 e cambiando il padding della depthwise. Pesi e quantizzazione restano copiati identici.
- L'uscita è uguale byte per byte su 503 input (PC) e sulla scheda. Il tensore intermedio da 115 KB sparisce: il picco scende da 225.840 a 178.688 B.

### Buffer a strisce ESP-NN (`esp-nn-strip.patch`)
- La depthwise ESP-NN con padding lavora a "strisce" di righe in un buffer scratch. ESP-NN lo dimensiona per circa 40 KB: `rows = (40·1024 − filter − 32) / row_bytes`, cioè 17 righe.
- La patch aggiunge `sciot_set_strip_rows(n)` per limitare le righe. Con 3 righe lo scratch scende e il **picco dell'arena arriva a 145.760 B (−18%)**, al costo dello +0,3% di tempo.
- Con 0 righe il comportamento resta quello originale. La patch è applicata alla copia congelata di ESP-NN.

### Arena in RAM interna e allocazione anticipata
- TFLite Micro mette tutte le attivazioni in un'unica "arena". In PSRAM è lenta (bus esterno), in RAM interna è veloce. Con l'arena in RAM interna `Invoke()` passa da 84,7 a 62,3 ms.
- **Il problema:** con Wi-Fi e camera attivi, la RAM interna libera è frammentata. Il blocco contiguo più grande era di 124.928 B, contro i 145.824 richiesti.
- **La soluzione:** allocare l'arena (`heap_caps_aligned_alloc(..., MALLOC_CAP_INTERNAL)`) **prima** di avviare Wi-Fi e camera. Restano circa 70 KB liberi, sopra la riserva di 32 KB che abbiamo imposto per la rete.
- **Sentinelle:** 32 byte a `0xA5` prima e dopo l'arena, ricontrollati a ogni frame per rilevare scritture fuori dai limiti.

### Keep-alive (`transport.h`)
`esp_http_client` viene creato una volta e riusato, con l'header `Connection: keep-alive` (oppure `close` nella modalità di confronto). Lato server, `--http-keep-alive` imposta il `timeout_keep_alive` di Uvicorn. Aprire la connessione scende da 12–13 a 2 ms.

---

## 7. XCLK: diagnosi e gestione

### Cos'è
- Il sensore della camera riceve dall'ESP32 un **clock XCLK a 16 MHz** sul **GPIO15**. Lo genera una periferica (il segnale `CAM_CLK_IDX`) instradata sul pin tramite la **GPIO matrix**.
- `cam_stop()` del driver congelato ferma acquisizione e interrupt, ma **lascia il clock attivo**. Per questo "sospendere l'acquisizione" non risolveva i blocchi.

### Diagnostica (`xclk_probe.cpp`, comando seriale `x`)
- **OFF:** `gpio_set_level(15, 0)` e `esp_rom_gpio_connect_out_signal(15, SIG_GPIO_OUT_IDX)`. Il pin diventa un GPIO normale tenuto basso, e il clock non esce più.
- **ON:** si ricollega il pin a `CAM_CLK_IDX`.
- **Verifica:** leggendo i registri della GPIO matrix si controlla che l'instradamento sia davvero cambiato. L'oscilloscopio non è stato usato.
- **Misura:** a ogni fase partono 50 ping ICMP verso il gateway e verso il laptop (`esp_ping`), nella sequenza baseline → ON → OFF → ON → OFF. I buffer della camera restano trattenuti, così si controlla che la RAM resti identica.

### Gestione nel ciclo (`gated_camera.cpp`)
1. `park()`: prende il framebuffer (l'unico) e spegne XCLK. Il driver non può avviare un'altra acquisizione finché non restituiamo il buffer.
2. Inferenza e invio avvengono **con il clock spento**. Il frame resta in mano nostra e un hash FNV verifica che non cambi.
3. `acquire()`:
   - riaccende XCLK e **attende 200 ms** (il tempo di assestamento del sensore, un'ipotesi da validare);
   - restituisce il buffer vecchio;
   - **scarta il primo frame completo** e tiene il secondo;
   - controlla che il timestamp sia successivo alla riaccensione e al frame precedente, e che il formato sia RGB565 96×96;
   - spegne di nuovo XCLK.
4. **Costo:** circa 601 ms per frame, tra 200 ms di attesa e due acquisizioni. È la voce dominante del ciclo da 710 ms.

**Idee per ridurlo:** attesa più corta (va misurato quanto basta), non scartare frame se non serve, oppure separare alimentazione e schermatura per capire se il problema è interferenza o carico elettrico.

---

## 8. Frame skip (`frame_skip.h`)

- **Metrica globale:** media della differenza assoluta tra l'input INT8 corrente e quello di riferimento, `Σ|a−b| / 9.216`.
- **Metrica locale:** il massimo, sulle tessere 8×8, della differenza media nella tessera.
- **Decisione:**
  - primo frame → invia;
  - differenza ≥ soglia → invia (`Change`);
  - età del riferimento ≥ rinnovo → invia (`Refresh`);
  - altrimenti → **salta** (`Similar`). Il salto evita sia `Invoke()` sia l'HTTP.
- **Doppio buffer:** il frame scelto viene copiato in `pending` (`stage`). Diventa riferimento (`acknowledge`, scambio di puntatori) **solo dopo la risposta del server**, così un invio fallito non sposta il riferimento.
- **Modalità:**
  - **Baseline:** nessuna logica;
  - **Shadow:** invia tutto, ma registra cosa avrebbe saltato, per confrontare la qualità sugli stessi frame;
  - **Active:** salta davvero.
- **Replay offline** (`frame_skip_replay.py`): applica la stessa politica ai frame del video e confronta gli eventi FOMO (intervalli di presenza per classe) con l'inferenza su tutti i frame.

---

## 9. Verifiche di correttezza ricorrenti

- **Attivazioni canoniche:** tre input fissi con SHA-256 noti, ricontrollati a ogni avvio e ogni 100 frame.
- **35 input iniziali:** il prefisso deve dare esattamente i byte attesi.
- **1.100 input deterministici per avvio:** le risposte del server devono coincidere byte per byte con quelle precalcolate.
- **Replay lato server:** i punteggi di ogni risposta salvata vengono ricalcolati dal suffisso e confrontati.
- **Memoria:** minimi di heap interno, blocco contiguo più grande e sentinelle, stampati a ogni frame.
- **Test automatici:** ogni esperimento ha `test_*.py` per l'analizzatore e per le parti di logica (frame skip, gestione di XCLK, ripristino). Nell'ultima campagna sono passati 47 test.

---

## 10. Parole chiave da saper spiegare

| Termine | In una frase |
|---|---|
| GPIO matrix | Instradamento configurabile tra le periferiche interne e i pin fisici dell'ESP32 |
| PSRAM | RAM esterna da 8 MB su bus SPI ottale: tanta capacità, accesso lento |
| `heap_caps_malloc` | Allocazione ESP-IDF in cui si sceglie la memoria (interna o PSRAM) |
| Arena TFLM | Il blocco unico in cui TFLite Micro mette tutti i tensori intermedi |
| Op registration | La tripla `Init` / `Prepare` / `Eval` di un operatore TFLM: noi abbiamo sostituito solo `Eval` |
| Flatbuffer `.tflite` | Il formato binario del modello: si può riscrivere senza riaddestrare |
| Zero-point / scale | I parametri della quantizzazione: `reale = (q − zp) · scale` |
| ZigZag + Rice | Mappare i residui con segno su interi piccoli, poi codificarli con un prefisso unario e k bit |
| 408 / 409 / 410 / 429 | Corpo non ricevuto in tempo / richiesta duplicata o occupata / sessione non valida / server pieno |
| Shadow mode | Eseguire la politica senza applicarla, per confrontare sugli stessi frame |
