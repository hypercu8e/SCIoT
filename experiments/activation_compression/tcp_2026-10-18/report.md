# Prova TCP delle attivazioni su PC

Data UTC: 2026-10-18T10:06:43.725483+00:00

Client e server sono processi distinti sullo stesso PC, collegati via TCP loopback.
Il client riproduce attivazioni registrate; il server esegue il suffisso Keras.
Nessuna modifica al protocollo SCIoT. Nessuna misura ESP32, camera, Wi-Fi o energia.

Passo: 0.001; frame: 146; riconnessione prima del frame 73 (indice da zero).

Ogni riga è una ripetizione; l'ordine ruota per ridurre gli effetti di riscaldamento.

| Giro | Metodo | Byte client | Byte server | Codifica media ms | Codifica + RTT p50 ms | p95 ms |
|---:|---|---:|---:|---:|---:|---:|
| 1 | raw | 2696760 | 261146 | 0.013 | 0.659 | 0.861 |
| 1 | independent | 1602438 | 261146 | 0.334 | 1.183 | 1.212 |
| 1 | temporal | 1385197 | 261146 | 0.618 | 1.489 | 1.527 |
| 2 | independent | 1602438 | 261146 | 0.332 | 1.181 | 1.240 |
| 2 | temporal | 1385197 | 261146 | 0.620 | 1.483 | 1.568 |
| 2 | raw | 2696760 | 261146 | 0.015 | 0.713 | 0.736 |
| 3 | temporal | 1385197 | 261146 | 0.652 | 1.462 | 1.799 |
| 3 | raw | 2696760 | 261146 | 0.015 | 0.673 | 1.019 |
| 3 | independent | 1602438 | 261146 | 0.322 | 1.099 | 1.670 |

## Verifiche

- SHA256 del tensore ricostruito verificato dal client per ogni risposta.
- Uscite raw confrontate con quelle salvate dall'estrazione: rtol=1e-5, atol=1e-6.
- Uscite indipendenti e temporali identiche byte per byte a pari passo in ogni giro.
- Nuova sessione e primo completo dopo ogni riconnessione; sequenze ripartono da zero.
- Metriche delle celle rispetto al raw nel JSON; nessuna accuratezza su annotazioni.

## Conteggi e tempi

I byte applicativi comprendono handshake, frame, risposte e prefissi di lunghezza di 4 byte del nostro formato. Escludono header TCP/IP, ACK TCP, ritrasmissioni e chiusura.
Il server restituisce tutta la griglia di uscita e l'hash del tensore: questo traffico di risposta va considerato separatamente dal risparmio in salita.
RTT comprende invio, decodifica, inferenza, hash, risposta e ricezione. Codifica + RTT esclude handshake, verifica locale, file, camera e prefisso della rete.
Caricamento modello e prima compilazione del suffisso sono esclusi; il traffico è sequenziale senza attesa per riprodurre i fps. I fps descrivono il video campionato.
La riconnessione è una chiusura volontaria tra frame confermati: non misura perdita di pacchetti, interruzioni durante un frame o riconnessione automatica.
I risultati usano gli input locali identificati dagli hash nel JSON; non si assume uguaglianza numerica con esecuzioni storiche su altri tensori.
