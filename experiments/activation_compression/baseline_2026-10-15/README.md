# Baseline del 15 ottobre 2026

Copia consolidata il 17 ottobre, senza ripetere il benchmark e senza sostituire i
tempi della prima esecuzione. Questi file sono fuori da `results/`, quindi possono
essere versionati insieme agli script. Al momento sono ancora locali e non in un commit.

## Contenuto

- [comparison/report.md](comparison/report.md): tabelle del confronto originale a 5 e 1 fps.
- [comparison/summary.json](comparison/summary.json): dimensioni, tempi originali, hash e diagnostica float32.
- [comparison/frames.csv](comparison/frames.csv): dimensioni e codifica scelta per ogni frame/metodo.
- [input-metadata.json](input-metadata.json): video, preprocessing, split e verifica rispetto alla rete completa.
- [environment-check.json](environment-check.json): versioni e controllo iniziale del modello su ingresso sintetico.
- [environment.uv.lock](environment.uv.lock): copia del lock dell'ambiente originale, ripristinabile come `uv.lock` nella radice.
- [codec-tests-2026-10-17.txt](codec-tests-2026-10-17.txt): verifica dei sei test durante la preparazione del trasferimento.
- [provenance.json](provenance.json): origine dei file e controlli di consolidamento.
- [input-sha256.txt](input-sha256.txt): hash dei tre input da conservare nella radice del repository.
- [snapshot-sha256.txt](snapshot-sha256.txt): hash dei file di questa copia, con percorsi relativi alla radice del repository.

I tensori NPY e le anteprime restano sotto `../results/input/`, rigenerabili con
`extract_activations.py`. Il video, la foto e lo ZIP del modello restano nella
radice del progetto e vanno trasferiti insieme agli script per riprodurre le prove.

## Controlli sulla macchina di destinazione

Dalla radice del progetto:

```bash
sha256sum -c experiments/activation_compression/baseline_2026-10-15/input-sha256.txt
sha256sum -c experiments/activation_compression/baseline_2026-10-15/snapshot-sha256.txt
```

Il primo comando richiede che gli input siano stati trasferiti. I risultati di
benchmark ottenuti successivamente vanno confrontati con questa copia storica,
conservando separati i nuovi tempi dalla misura originale.

Per il contesto, le spiegazioni e le istruzioni di ambiente leggere
[ANALISI_COMPRESSIONE_ATTIVAZIONI.md](../../../ANALISI_COMPRESSIONE_ATTIVAZIONI.md).
