# Prova di capienza con buffer Wi-Fi/lwIP in PSRAM — 12 novembre 2026

**Esito.** Con `CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP=y` la rete **non si
blocca più** con il blocco da 152 KiB tenuto in RAM interna. La fase 2 (R)
completa 1.000 frame su 1.000 senza errori. Il verdetto secondo i criteri
fissati prima resta comunque **non entra**, per tre motivi:

- **Margine:** il minimo interno libero nelle fasi R è **26.779 e 26.651
  byte**, sotto la soglia di 32.768. Manca circa 6 KB.
- **Fase 4:** una registrazione dopo un 408 è fallita lato client e poi è
  riuscita al nuovo tentativo. La regola chiede tutte le registrazioni riuscite.
- **Ciclo:** il ciclo p50 peggiore delle fasi R è 1,28 volte la media delle
  fasi N. Però la rete è rallentata a metà run per tutte e due le modalità
  (vedi sotto), quindi questo criterio qui misura soprattutto l'ambiente.

Le fasi di controllo N passano tutte. A differenza della prima prova, il
minimo libero ora è **stabile**: si fissa all'avvio e non scende durante
l'invio. Il passo che manca è recuperare circa 6 KB interni.

## Configurazione

Come nella [prima prova](report.md), con il firmware `psramnet`: ESP-IDF
attiva insieme all'opzione i suoi default Wi-Fi, cioè 16 buffer RX statici,
16 TX statici, finestra BA 16 e nessun pbuf fuori ordine
([README](../README.md#seconda-prova-buffer-wi-filwip-in-psram)). Il runner
chiude una fase all'11° errore; non è mai successo. Run
`results/2026-11-12-board-B-psramnet` (non versionato), audit in
[summary-psramnet.json](summary-psramnet.json).

## Risultati per fase

| Fase | Camera | Risposte server | Min. libero interno | Libero (min. campionato) | Blocco max (min.) | Ciclo p50 / p95 | Rete p50 |
|---|---:|---|---:|---:|---:|---:|---:|
| 1 N | 1.000 | 1.060 × 200 | 183.039 | 189.683 | 94.208 | 316 / 921 ms | 98 ms |
| 2 R | 1.000 | 1.060 × 200 | **26.779** | 33.531 | 21.504 | 362 / 551 ms | 145 ms |
| 3 N | 999 | 1.059 × 200, 1 × 408 | 183.043 | 189.683 | 94.208 | 580 / 1.203 ms | 361 ms |
| 4 R | 997 | 1.057 × 200, 2 × 408 | **26.651** | 33.531 | 21.504 | 574 / 1.655 ms | 353 ms |

- Inferenza p50 invariata, circa 95 ms. Nessuna disconnessione Wi-Fi, nessun
  panic o riavvio.
- I 408 sono tutti `body_timeout`, e sono 1–2 per fase sia in N sia in R.
- Dalla fase 3 la rete è più lenta per tutte e due le modalità: rete p50 da
  98–145 ms a 353–361 ms. Confrontate a coppie, R costa +46 ms sul ciclo nelle
  fasi 1→2 e −6 ms nelle fasi 3→4.

## Confronto con la prima prova

| | Prima prova (buffer in RAM interna) | `psramnet` |
|---|---:|---:|
| Fasi R completate | 360 e 4 frame | 1.000 e 997 frame |
| Min. libero R | 22.751 / 11.831, in calo | 26.779 / 26.651, stabile |
| Min. libero N | 196.807 / 193.363 | 183.039 / 183.043 |
| Ciclo p50 N | 284 / 277 ms | 316 / 580 ms |

Con `psramnet` il client usa a regime circa **13,7 KB in più** di RAM interna
anche senza blocco: 183 KB liberi invece di 197 KB. La causa probabile sono i
buffer statici che l'opzione introduce, 16 TX e 16 RX invece di 10 RX.
Senza blocco, il resto del client usa a regime circa 112–119 KB di RAM
interna: camera, Wi-Fi, stack dei task, HTTP.

Il ciclo N non si confronta in modo pulito con la prima prova: la rete è
cambiata già dentro questo run.

## Lettura

Spostare in PSRAM i buffer dinamici di rete risolve il problema della prima
prova: la rete non si contende più la RAM interna con il blocco. Resta un
margine di circa 26,7 KB contro i 32 KB richiesti. La leva più diretta è
togliere l'aumento dei buffer statici: tenere l'opzione PSRAM, ma riportare i
buffer RX statici a 10 e il TX a dinamico, come nel client originale. Questo
recupererebbe circa 13 KB e porterebbe il minimo atteso intorno a 40 KB. Va
misurato.

## Recupero

Backup di 8 MiB verificato (seme dal run precedente). Firmware originale
riscritto e verificato prima dell'avvio, avvio del client originale
confermato.
