# FOMO INT8: DPCM e dead-zone sulla ESP32

**Campagna completa: video e camera sulla ESP32.**

Nel video, deadzone4 ha il payload minimo: 1934.3 B/frame, 58.02% sotto INT8 raw. Cambia complessivamente 82 celle nei due giri; non è una configurazione approvata per l’applicazione. Tutti i nuovi codec con quantizzazione hanno un ciclo mediano maggiore del raw in entrambi i giri. Le modalità zlib senza perdita conservano esattamente attivazioni e punteggi.

4224 richieste misurate e 720 diagnostiche, due giri in ordine invertito. Video: 146 ingressi identici, campionamento 5 fps e replay senza attese. Camera: sequenze diverse; qualità confrontata con il raw sugli stessi frame tramite diagnostica fuori misura.

| Input | Giro | Metodo | Payload B/frame | HTTP B/frame | Ciclo p50/p95 ms | FPS | Celle cambiate | Max errore punteggio |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| video | 1 | raw | 4608.0 | 6886.0 | 176.03/201.71 | 5.58 | 0 | 0.000000 |
| video | 1 | zlib1 | 3934.1 | 6212.1 | 181.52/206.84 | 5.40 | 0 | 0.000000 |
| video | 1 | zlib6 | 3934.2 | 6212.2 | 181.28/203.51 | 5.42 | 0 | 0.000000 |
| video | 1 | independent4 | 2211.6 | 4489.6 | 203.16/227.18 | 4.84 | 57 | 0.406250 |
| video | 1 | independent6 | 3162.4 | 5440.4 | 203.28/227.44 | 4.83 | 31 | 0.195312 |
| video | 1 | independent8 | 3928.1 | 6206.1 | 203.14/216.15 | 4.88 | 22 | 0.175781 |
| video | 1 | dpcm4 | 2047.7 | 4325.7 | 204.67/226.86 | 4.83 | 41 | 0.468750 |
| video | 1 | dpcm6 | 2772.9 | 5050.9 | 203.03/225.44 | 4.86 | 21 | 0.410156 |
| video | 1 | dpcm8 | 3137.6 | 5415.6 | 204.82/234.69 | 4.80 | 15 | 0.382812 |
| video | 1 | deadzone4 | 1934.3 | 4212.3 | 206.74/232.91 | 4.73 | 41 | 0.453125 |
| video | 1 | deadzone6 | 2751.0 | 5029.0 | 205.02/216.09 | 4.84 | 17 | 0.410156 |
| video | 1 | deadzone8 | 3129.6 | 5407.6 | 206.30/230.05 | 4.76 | 15 | 0.382812 |
| video | 2 | raw | 4608.0 | 6886.0 | 177.33/203.45 | 5.56 | 0 | 0.000000 |
| video | 2 | zlib1 | 3934.1 | 6212.1 | 183.01/211.24 | 5.38 | 0 | 0.000000 |
| video | 2 | zlib6 | 3934.2 | 6212.2 | 185.45/207.31 | 5.32 | 0 | 0.000000 |
| video | 2 | independent4 | 2211.6 | 4489.6 | 203.75/234.72 | 4.83 | 57 | 0.406250 |
| video | 2 | independent6 | 3162.4 | 5440.4 | 205.05/251.63 | 4.75 | 31 | 0.195312 |
| video | 2 | independent8 | 3928.1 | 6206.1 | 204.83/233.18 | 4.80 | 22 | 0.175781 |
| video | 2 | dpcm4 | 2047.7 | 4325.7 | 208.20/238.81 | 4.74 | 41 | 0.468750 |
| video | 2 | dpcm6 | 2772.9 | 5050.9 | 205.76/218.65 | 4.81 | 21 | 0.410156 |
| video | 2 | dpcm8 | 3137.6 | 5415.6 | 207.10/240.39 | 4.70 | 15 | 0.382812 |
| video | 2 | deadzone4 | 1934.3 | 4212.3 | 209.81/225.45 | 4.72 | 41 | 0.453125 |
| video | 2 | deadzone6 | 2751.0 | 5029.0 | 207.85/234.38 | 4.74 | 17 | 0.410156 |
| video | 2 | deadzone8 | 3129.6 | 5407.6 | 210.53/240.48 | 4.68 | 15 | 0.382812 |
| camera | 1 | raw | 4608.0 | 6886.0 | 216.87/278.53 | 4.49 | 0 | 0.000000 |
| camera | 1 | zlib1 | 3698.0 | 5976.0 | 201.31/344.75 | 4.55 | 0 | 0.000000 |
| camera | 1 | zlib6 | 3732.1 | 6010.1 | 199.02/249.09 | 4.89 | 0 | 0.000000 |
| camera | 1 | independent4 | 1988.7 | 4266.7 | 214.27/234.72 | 4.62 | 0 | 0.000000 |
| camera | 1 | independent6 | 3166.2 | 5444.2 | 212.22/249.69 | 4.61 | 0 | 0.000000 |
| camera | 1 | independent8 | 3714.4 | 5992.4 | 212.85/287.44 | 4.41 | 0 | 0.000000 |
| camera | 1 | dpcm4 | 2383.3 | 4661.3 | 216.43/240.13 | 4.57 | 0 | 0.000000 |
| camera | 1 | dpcm6 | 3072.7 | 5350.7 | 211.68/226.50 | 4.66 | 0 | 0.000000 |
| camera | 1 | dpcm8 | 3355.0 | 5633.0 | 215.23/242.95 | 4.59 | 0 | 0.000000 |
| camera | 1 | deadzone4 | 2353.6 | 4631.6 | 218.76/274.73 | 4.46 | 0 | 0.000000 |
| camera | 1 | deadzone6 | 3139.2 | 5417.2 | 219.27/240.75 | 4.50 | 0 | 0.000000 |
| camera | 1 | deadzone8 | 3404.0 | 5682.0 | 218.96/238.37 | 4.52 | 0 | 0.000000 |
| camera | 2 | raw | 4608.0 | 6886.0 | 180.42/189.78 | 5.48 | 0 | 0.000000 |
| camera | 2 | zlib1 | 3693.3 | 5971.3 | 188.35/223.36 | 5.12 | 0 | 0.000000 |
| camera | 2 | zlib6 | 3692.4 | 5970.4 | 187.41/204.36 | 5.25 | 0 | 0.000000 |
| camera | 2 | independent4 | 2031.1 | 4309.1 | 205.89/232.64 | 4.78 | 0 | 0.000000 |
| camera | 2 | independent6 | 3182.4 | 5460.4 | 207.02/237.89 | 4.71 | 0 | 0.000000 |
| camera | 2 | independent8 | 3687.7 | 5965.7 | 211.41/233.86 | 4.68 | 0 | 0.000000 |
| camera | 2 | dpcm4 | 2389.4 | 4667.4 | 211.44/236.81 | 4.63 | 0 | 0.000000 |
| camera | 2 | dpcm6 | 3207.6 | 5485.6 | 212.20/269.18 | 4.57 | 0 | 0.000000 |
| camera | 2 | dpcm8 | 3276.6 | 5554.6 | 210.80/261.00 | 4.62 | 0 | 0.000000 |
| camera | 2 | deadzone4 | 2365.5 | 4643.5 | 211.64/219.03 | 4.71 | 0 | 0.000000 |
| camera | 2 | deadzone6 | 3195.8 | 5473.8 | 213.47/234.28 | 4.62 | 0 | 0.000000 |
| camera | 2 | deadzone8 | 3313.0 | 5591.0 | 212.76/242.16 | 4.58 | 0 | 0.000000 |

## Interpretazione e limiti

Il ciclo include ingresso, inferenza ESP-NN, quantizzazione/ricostruzione locale, compressione, checksum, HTTP fino alla risposta completa e cleanup. I tempi del server sono già dentro HTTP. L’allocazione e il cambio livello del compressore sono fuori misura; il reset per frame è incluso. Le copie diagnostiche camera sono incluse nel throughput ma fuori dal timer del singolo frame. Stampe seriali e upload diagnostico avvengono dopo la sequenza. Il server salva i pacchetti prima della risposta: questo costo comune è dentro il tempo di rete.

Camera XCLK 20 MHz, contro i 16 MHz della baseline precedente; tutte le modalità della campagna usano la medesima configurazione. Non si attribuiscono al solo codec le differenze rispetto ai vecchi firmware. Il limite HTTP è 60 secondi, identico per tutti i metodi. Le sonde RSSI/canale sono fuori misura e disponibili nel JSON; non sono una registrazione continua della qualità radio.

HTTP include le intestazioni ricostruite e la risposta; esclude TCP/IP, ACK, ritrasmissioni e traffico diagnostico, che è riportato separatamente. Rinnovi ogni 30 frame, nessun fallback adattivo. Il codec usa miniz 3.0.2, non garantisce byte identici a zlib livello 6 del paper.

Le metriche di fedeltà confrontano lo stesso suffisso desktop sugli INT8 originali prodotti dalla scheda. Non sono accuratezza su annotazioni; le classi restano canali anonimi. Nessuna tolleranza applicativa è stata approvata. Il clipping P99 può lasciare errore anche a 8 bit: aumentare i bit non elimina le saturazioni degli estremi. Il riferimento DPCM sincronizzato evita la divergenza fra encoder e decoder, non garantisce predizioni identiche al raw. Il benchmark non prova altri video, reti, schede o client concorrenti.

La memoria libera minima è cumulativa dalla partenza e tutte le configurazioni condividono i buffer del benchmark; non è il picco di firmware separati. La riserva diagnostica e la tensor arena vanno distinte dal costo del codec.
