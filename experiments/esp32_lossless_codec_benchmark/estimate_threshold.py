"""Offline inference from archived measurements; never opens a hardware port."""
import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
MODES = ('raw', 'rice_temporal')
CPU_PHASES = ('prepare_us', 'invoke_us', 'quantize_reconstruct_us',
              'compression_us', 'packing_us', 'server_decode_us',
              'server_invoke_us', 'server_post_us')


def inverse_rate_fit(low, high):
    # Time in ms, effective configured rate in Mbit/s: T(R) = a/R + b.
    a = (low - high) / (1 / .128 - 1 / .512)
    return {'a_ms_mbps': float(a), 'b_ms': float(high - a / .512)}


def thresholds(raw, rice):
    a = raw['a_ms_mbps'] - rice['a_ms_mbps']
    b = raw['b_ms'] - rice['b_ms']
    check = lambda fraction: (a - fraction * raw['a_ms_mbps']) / (fraction * raw['b_ms'] - b)
    return {'zero_gain_mbps': float(check(0)), 'five_percent_median_gain_mbps': float(check(.05))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a new output directory')
    published = json.loads((HERE / 'campaign-summary.json').read_text())
    archived = {c['folder']: c for c in published['campaigns']}
    datasets, hashes, pooled, paired = {}, {}, {}, {}
    for rate, folder in [(0, 'hardware_native_network_2026-10-30'),
                         (128, 'hardware_native_128k_2026-10-30'),
                         (512, 'hardware_native_512k_2026-10-30')]:
        path = HERE / folder / 'frames.csv'
        hashes[str(path.relative_to(HERE))] = hashlib.sha256(path.read_bytes()).hexdigest()
        with path.open() as stream:
            data = [r for r in csv.DictReader(stream) if r['source'] == '0' and r['mode'] in MODES]
        assert all(sum(r['mode'] == mode for r in data) == 876 for mode in MODES)
        datasets[rate] = data
        pooled[rate] = {mode: float(np.median([float(r['cycle_us']) / 1000 for r in data if r['mode'] == mode])) for mode in MODES}
        for mode in MODES:
            assert abs(pooled[rate][mode] - archived[folder]['methods'][mode]['cycle_p50_ms']) < 1e-8
        paired[rate] = [{mode: float(np.median([float(r['cycle_us']) / 1000 for r in data if r['mode'] == mode and int(r['round']) // 2 == pair])) for mode in MODES} for pair in range(3)]
    fits = {mode: inverse_rate_fit(pooled[128][mode], pooled[512][mode]) for mode in MODES}
    point = thresholds(fits['raw'], fits['rice_temporal'])
    for rate in (128, 512):
        for mode in MODES:
            assert abs(fits[mode]['a_ms_mbps'] / (rate / 1000) + fits[mode]['b_ms'] - pooled[rate][mode]) < 1e-8
    sensitivity = []
    for low, high in itertools.product(paired[128], paired[512]):
        candidate = {mode: inverse_rate_fit(low[mode], high[mode]) for mode in MODES}
        sensitivity.append(dict(fits=candidate, **thresholds(candidate['raw'], candidate['rice_temporal'])))
    ranges = {key: {'min': min(s[key] for s in sensitivity), 'median': float(np.median([s[key] for s in sensitivity])), 'max': max(s[key] for s in sensitivity)} for key in point}
    # Match the same frame and round; exclude network_us, which includes transport.
    data = datasets[0]
    indexed = {(r['round'], r['frame'], r['mode']): r for r in data}
    overhead, savings = [], []
    for raw in data:
        if raw['mode'] != 'raw':
            continue
        rice = indexed[raw['round'], raw['frame'], 'rice_temporal']
        overhead.append(sum(float(rice[k]) - float(raw[k]) for k in CPU_PHASES) / 1000)
        savings.append(float(raw['payload_bytes']) - float(rice['payload_bytes']))
    cpu_ms = float(np.median(overhead))
    saved_bytes = float(np.mean(savings))
    ideal_mbps = 8 * saved_bytes / (cpu_ms * 1000)
    result = dict(kind='OFFLINE ESTIMATE, not a new hardware measurement',
                  scope='Only Rice temporal with native C++ server decoder and this FOMO/split/video',
                  observed_cycle_p50_ms=pooled, fits=fits, point_estimates=point,
                  nine_combination_sensitivity=ranges, sensitivity_fits=sensitivity,
                  sensitivity_is_confidence_interval=False,
                  compute_only_model=dict(extra_cpu_p50_ms=cpu_ms, saved_payload_mean_bytes=saved_bytes, ideal_zero_gain_mbps=ideal_mbps),
                  assumptions=['Each capped method follows T(R)=a/R+b between or beyond two configured proxy rates.',
                               'The nine fits combine the three two-round blocks at each rate; this is sensitivity, not a confidence interval.',
                               'Ordinary Wi-Fi has unknown uplink goodput and is not the infinite-rate limit of the proxy experiment.',
                               'The 5% estimate concerns only the median; the original p95 condition is not predicted.',
                               'The CPU-only model excludes differences in transport/stack/proxy costs and is optimistic.',
                               'Only 128 and 512 kbit/s were measured with a rate cap. No actual switch threshold was observed.'],
                  source_sha256=hashes, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    args.output.mkdir(parents=True)
    (args.output / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    five, zero = point['five_percent_median_gain_mbps'], point['zero_gain_mbps']
    f_range, z_range = ranges['five_percent_median_gain_mbps'], ranges['zero_gain_mbps']
    text = f'''# Soglia Rice: stima offline, 1 novembre 2026

**Nessuna nuova prova hardware.** Si usano i CSV delle campagne native del 30 ottobre.

|Quantità stimata|Fit sulle mediane aggregate|Sensibilità ai nove abbinamenti di blocchi|
|---|---:|---:|
|Guadagno del 5% sulla sola mediana|{five:.3f} Mbit/s|{f_range['min']:.3f}–{f_range['max']:.3f} Mbit/s|
|Semplice pareggio del ciclo mediano|{zero:.3f} Mbit/s|{z_range['min']:.3f}–{z_range['max']:.3f} Mbit/s|

Queste fasce **non sono intervalli di confidenza** e non coprono tutti gli errori del modello.
A 512 kbit/s Rice supera già il criterio hardware; fra 512 kbit/s e le soglie stimate
non ci sono nuove misure. Il vincolo p95 del criterio originale resta da verificare.

## Metodo

Per ciascun metodo si adatta `T(R) = a/R + b`, con T in millisecondi e R in Mbit/s,
alle mediane misurate con proxy a 128 e 512 kbit/s. Si risolvono `Traw = Trice`
e `Trice = 0,95*Traw`. Due punti determinano esattamente una curva: il fit non
costituisce una validazione del modello. Le tre coppie di giri di ogni regime
producono nove abbinamenti per esaminare la sensibilità alla variabilità osservata;
i blocchi delle due sessioni non sono coppie temporali corrispondenti.

La Wi-Fi ordinaria non ha una banda effettiva identificata e usa un percorso
senza proxy: non viene trattata come un campione a banda infinita.

## Controllo con un modello ideale

Il risparmio medio è {saved_bytes:.2f} byte/frame. Il costo computazionale aggiuntivo,
accoppiando stesso frame e giro ed escludendo `network_us`, ha mediana {cpu_ms:.3f} ms.
La sola relazione `8*byte_risparmiati / costo_aggiuntivo` darebbe un pareggio
ideale di **{ideal_mbps:.2f} Mbit/s**. Non considera differenze di stack, trasferimento,
proxy e variabilità radio. La distanza dalla stima empirica ({zero:.2f} Mbit/s)
mostra che non possiamo identificare con precisione una soglia reale da questi dati.
Non va usata come soglia di commutazione verificata.

## Conclusione utilizzabile

Senza ESP32 possiamo proporre **circa 0,6–0,85 Mbit/s come fascia da verificare
per un guadagno mediano del 5%**, con stima centrale intorno a 0,7 Mbit/s.
Il limite più alto per un qualunque guadagno è molto meno identificato.
La prova disponibile più vicina resta quella a 512 kbit/s. Per decidere una soglia
operativa reale servono nuove misure vicino alla fascia stimata, con p95 e più scene;
non basta fare replay sul PC o emulare il tempo della scheda con attese artificiali.

I riferimenti sono velocità del corpo applicativo in upload nel proxy, non PHY Wi-Fi.
La campagna 128 kbit/s conserva la nota di recupero del prefisso USB nel rapporto originale;
nessun tempo è stato stimato o sostituito in quell'archivio.
'''
    (args.output / 'report.md').write_text(text)
    print(json.dumps(dict(point_estimates=point, sensitivity=ranges, ideal_cpu_mbps=ideal_mbps), indent=2))


if __name__ == '__main__':
    main()
