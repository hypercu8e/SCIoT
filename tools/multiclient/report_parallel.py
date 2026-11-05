"""Summarize a completed parallelism campaign without pooling percentiles."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics as st
from benchmark import energy_scope


def med(values):
    values=list(values)
    return st.median(values) if values else None


def report(root, destination):
    groups=defaultdict(list)
    for line in (root/'results.jsonl').open():
        row=json.loads(line)
        name=f"{row['kind']}-w{row['workers']}-t{row['threads']}-n{row['clients']}-r{row['repeat']}"
        path=root/name/'environment.json'
        snap=json.loads(path.read_text()) if path.exists() else None
        scope=row.get('energy_scope') or (energy_scope(snap['before'],snap['after']) if snap else 'unrecorded')
        groups[row['kind'],row['workers'],row['threads'],row['clients'],scope].append(row)
    output=[]
    for (kind,w,t,n,scope),rows in groups.items():
        resources=[s for r in rows for s in r['resources']]
        output.append({'energy_scope':scope,'kind':kind,'workers':w,'threads':t,'clients':n,'repeats':len(rows),
            'throughput_median':med(r['result']['completed_per_second'] for r in rows),
            'throughput_min':min(r['result']['completed_per_second'] for r in rows),
            'throughput_max':max(r['result']['completed_per_second'] for r in rows),
            'client_p95_median_ms':med(c['latency_ms']['p95'] for r in rows for c in r['result']['clients'] if c['latency_ms']),
            'invoke_p50_median_us':med(c.get('engine_timings_us',{}).get('invoke_us',{}).get('p50') for r in rows for c in r['result']['clients'] if c.get('engine_timings_us')),
            'completed':sum(c['completed'] for r in rows for c in r['result']['clients']),
            'rejected':sum(c['rejected'] for r in rows for c in r['result']['clients']),
            'failed':sum(c['failed'] for r in rows for c in r['result']['clients']),
            'missed_slots':sum(c['missed_scheduled_slots'] for r in rows for c in r['result']['clients']),
            'server_cpu_cores_mean':st.mean(s['cpu_cores'] for s in resources) if resources else None,
            'generator_cpu_cores_median':med(r['result']['generator_cpu_cores'] for r in rows),
            'rss_max_bytes':max((s['rss_bytes'] or 0 for s in resources),default=0),
            'max_active_workers':max((s['active_workers'] for s in resources),default=0)})
    engines=defaultdict(list)
    for path in root.glob('engine-*/summary.json'):
        r=json.loads(path.read_text())
        ep=path.parent/'environment.json'
        snap=json.loads(ep.read_text()) if ep.exists() else None
        scope=energy_scope(snap['before'],snap['after']) if snap else 'unrecorded'
        engines[r['workers'],r['threads'],scope].append(r)
    engine_rows=[{'energy_scope':scope,'workers':w,'threads':t,'throughput_median':med(r['throughput'] for r in rows),
                 'cpu_cores_median':med(r['cpu_cores'] for r in rows),'exact':all(r['exact'] for r in rows),
                 'repeats':len(rows)} for (w,t,scope),rows in sorted(engines.items())]
    destination.mkdir(parents=True,exist_ok=True)
    (destination/'summary.json').write_text(json.dumps({'http':output,'engine':engine_rows},indent=2)+'\n')
    matrix=[r for r in output if r['kind']=='matrix']
    complete=(root/'selection.json').exists()
    lines=['# Parallelismo SCIoT INT8: '+('campagna CPU' if complete else 'risultati preliminari'),'',
        '' if complete else '**Campagna incompleta e confronto prestazionale non conclusivo.** Consultare lo stato della campagna e i manifest per le condizioni di esecuzione.', '',
        'Stesso prefisso/suffisso congelato e split `block_2_add`; interpreti indipendenti, un processo HTTP. '
        'Client simulati su loopback nello stesso PC. I tempi non includono camera, prefisso ESP32 o Wi-Fi.', '',
        'I conteggi e le uscite HTTP riuscite sono verificati byte per byte. '
        'I risultati sono separati per alimentazione e profilo CPU. Le righe `transition` non permettono confronti prestazionali stabili. '
        'I valori di latenza riportati sono mediane dei p95 per client e ripetizione, non percentili aggregati.', '',
        '## Solo motore', '', '|Energia|Worker|Thread/inferenza|Inferenze/s, mediana|CPU logiche equivalenti, mediana|Ripetizioni|',
        '|---|---:|---:|---:|---:|---:|']
    for r in engine_rows:lines.append(f"|{r['energy_scope']}|{r['workers']}|{r['threads']}|{r['throughput_median']:.1f}|{r['cpu_cores_median']:.2f}|{r['repeats']}|")
    lines+=['','## HTTP', '', '|Energia|Worker|Thread|Client|Ripetizioni|Richieste/s, mediana [min–max]|p95 client, mediana ms|Rifiuti|Errori|',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in sorted(matrix,key=lambda r:(r['clients'],r['workers'],r['threads'])):
        lines.append(f"|{r['energy_scope']}|{r['workers']}|{r['threads']}|{r['clients']}|{r['repeats']}|{r['throughput_median']:.1f} [{r['throughput_min']:.1f}–{r['throughput_max']:.1f}]|{r['client_p95_median_ms']:.2f}|{r['rejected']}|{r['failed']}|")
    lines+=['','## Carico programmato', '', '|Energia|Regime|Worker|Thread|Richieste/s|p95 client ms|Rifiuti|Slot saltati|',
            '|---|---|---:|---:|---:|---:|---:|---:|']
    for r in output:
        if r['kind']=='matrix':continue
        lines.append(f"|{r['energy_scope']}|{r['kind']}|{r['workers']}|{r['threads']}|{r['throughput_median']:.1f}|{r['client_p95_median_ms']:.2f}|{r['rejected']}|{r['missed_slots']}|")
    lines+=['','## Interpretazione e limiti','',
        'Confrontare il motore isolato con HTTP: la capacità del servizio può essere limitata da ricezione, '
        'serializzazione, log sincroni e generatore, prima che dai kernel. Il numero di thread richiesto '
        'non dimostra l’utilizzo effettivo di altrettanti core. Il valore CPU è tempo CPU/tempo reale, '
        'comprende tutti i thread del processo: 1,0 equivale al tempo CPU di una CPU logica pienamente occupata, non misura i joule consumati. La prova solo motore include parsing, copie, invoke, postprocessing e controllo delle uscite. Le misure HTTP di CPU escludono il riscaldamento; quelle '
        'del solo motore e del generatore includono il riscaldamento.', '',
        'Il generatore mantiene una richiesta pendente per client, registra gli slot programmati saltati '
        'e applica il backoff originale sui 429: non è un generatore open-loop illimitato. '
        'La scelta esplorativa del candidato usa soltanto il regime energetico iniziale e la mediana del throughput con il massimo numero di client '
        'della matrice, ed è esplorativa. Altre applicazioni sul PC possono influenzare i tempi. '
        'RSS include runtime TensorFlow e interpreti: non è la sola memoria dei tensori.', '',
        'Gli invii programmati condividono la stessa origine temporale: generano raffiche sincronizzate. I rate sono target riferiti alla capacità della baseline nel regime iniziale su alimentatore; il carico consegnato può essere molto inferiore per effetto di 429, backoff e slot saltati. Il vantaggio di più worker in questa fase può comprendere la maggiore capacità di ammissione (coda più lavori attivi), oltre al calcolo. Questi risultati non misurano isolatamente la velocità dei kernel né rappresentano arrivi uniformi o traffico Wi-Fi reale.', '',
        'Le tre ripetizioni complessive sono ripartite fra diversi regimi energetici: ogni riga indica quante ripetizioni effettivamente confrontabili contiene. Non si ricava una classifica universale aggregando alimentazioni o profili differenti.', '',
        f"Richieste HTTP completate e verificate: **{sum(r['completed'] for r in output)}**; "
        f"errori: **{sum(r['failed'] for r in output)}**.", '',
        ('Audit: correzione della preparazione dei client dopo 35 prove HTTP complete; vedere `results/registration-audit.json`.' if (root/'registration-audit.json').exists() else 'Registrazioni iniziali completate prima del riscaldamento; alimentazione e profilo energetico controllati durante la campagna.'), '',
        'Dati completi: `results/manifest.json`, `results/results.jsonl` e directory per prova. '
        'Il manifest conserva hardware, dipendenze, hash dei sorgenti e manifest del modello.']
    (destination/'report.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report(a.root,a.output)
