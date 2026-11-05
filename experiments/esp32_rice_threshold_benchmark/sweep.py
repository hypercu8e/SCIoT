"""Sequential hardware campaigns; each restores the original image before audit."""
import argparse
import csv
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
from sweep_policy import choose_next
HERE=Path(__file__).resolve().parent


def summarize(records,reason,destination):
    report='# Soglia operativa Rice: prove hardware\n\n'
    report+='Solo INT8 raw e Rice temporale; sei giri video per rate, 146 frame/giro/metodo. Ogni punto comprende 1752 richieste. Il criterio richiede mediana almeno -5% e p95 non oltre +5% in tutte le tre coppie.\n\n'
    report+='|Proxy kbit/s|Raw p50 ms|Rice p50 ms|Variazione aggregata|Criterio 3 coppie|\n|---:|---:|---:|---:|---|\n'
    public=[];recoveries=0
    for rate,entry in sorted(records.items()):
        path=Path(entry['published']);summary=json.loads((path/'summary.json').read_text())
        assert summary['measured']==1752 and summary['lossless_exact'] and summary['restored_verified']
        verification=json.loads((path/'verification.json').read_text())
        assert verification['restored'] and verification['original_boot_verified']
        if summary.get('serial_recovery'):recoveries+=summary['serial_recovery']['recovered_records']
        assert summary['decoder_backend']=='native' and summary['bandwidth']['target_kbps']==rate
        with (path/'frames.csv').open() as stream:rows=list(csv.DictReader(stream))
        med={name:float(np.median([float(r['cycle_us']) for r in rows if r['mode']==name]))/1000 for name in ('raw','rice_temporal')}
        change=100*(med['rice_temporal']/med['raw']-1)
        public.append(dict(rate_kbps=rate,passes=entry['passes'],median_ms=med,median_change_percent=change,acceptance=summary['acceptance']['rice_temporal'],effective_rate=summary['bandwidth'],report=str(path.relative_to(HERE)/'report.md')))
        report+=f"|[{rate}](../{path.name}/report.md)|{med['raw']:.2f}|{med['rice_temporal']:.2f}|{change:+.2f}%|{'superato' if entry['passes'] else 'non superato'}|\n"
    passed=[p['rate_kbps'] for p in public if p['passes']]
    failed=[p['rate_kbps'] for p in public if not p['passes']]
    bracket=None
    if passed and failed and max(passed)<min(failed):
        bracket=dict(highest_passing=max(passed),lowest_failing=min(failed),width=min(failed)-max(passed))
        report+=f"\n**Massimo rate verificato che supera il criterio: {max(passed)} kbit/s. Fascia fra punti osservati: {max(passed)}–{min(failed)} kbit/s.**\n\n"
    report+='Esito della ricerca: '+reason+'.\n\n'
    report+='Il criterio è un margine operativo, non il semplice pareggio. Un punto non superato può comunque avere una mediana aggregata migliore: devono superare i limiti tutte le tre coppie, compreso il p95.\n\n'
    report+='## Coppie che non superano il criterio\n\n'
    for point in public:
        for pair in point['acceptance']['pairs']:
            if not pair['passes']:
                report+=f"- {point['rate_kbps']} kbit/s, coppia {pair['pair']+1}: guadagno mediano {100*(1-pair['median_ratio']):.2f}%, variazione p95 {100*(pair['p95_ratio']-1):+.2f}%.\n"
    report+=f"\nValidazione: {1752*len(public)} richieste fisiche; attivazioni e uscite identiche al raw INT8, ripristino integrale e avvio originale verificati dopo ogni punto. Recuperi di prefissi seriali: {recoveries}; nessun tempo stimato.\n\n"
    report+='[Grafico della fascia osservata](threshold.png) · [Versione SVG](threshold.svg).\n\n'

    report+='La fascia individuata è un intervallo fra punti osservati, non un intervallo di confidenza o una soglia universale. Rete e luogo possono differire dalle prove di ottobre. Il proxy limita il corpo della richiesta: non misura il PHY Wi-Fi né simula contesa o ritrasmissioni. I limiti del modello/video e la fedeltà al raw INT8 restano distinti dall’accuratezza annotata.\n'
    destination.mkdir(exist_ok=True,parents=True)
    (destination/'summary.json').write_text(json.dumps(dict(points=public,stop_reason=reason,observed_bracket_kbps=bracket,serial_prefix_recoveries=recoveries,measured_requests=1752*len(public)),indent=2)+'\n')
    (destination/'report.md').write_text(report)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--tag',default='2026-11-01');parser.add_argument('--port',default='/dev/ttyACM0');parser.add_argument('--seed-backup',type=Path)
    args=parser.parse_args()
    if not args.tag or any(c not in '0123456789abcdefghijklmnopqrstuvwxyz-_' for c in args.tag):parser.error('Use a simple tag')
    state=HERE/'results'/f'sweep-{args.tag}.json'
    records={}
    if state.exists():
        records={int(k):v for k,v in json.loads(state.read_text()).items()}
        for entry in records.values():
            s=json.loads((Path(entry['published'])/'summary.json').read_text())
            if not s['restored_verified']:raise ValueError('Do not resume before restoration')
    seed=args.seed_backup.resolve() if args.seed_backup else None
    while True:
        rate,reason=choose_next({r:v['passes'] for r,v in records.items()})
        if rate is None:
            summarize(records,reason,HERE/f'sweep_{args.tag}');print(json.dumps(dict(event='sweep_complete',reason=reason)),flush=True);return
        if len(records)>=12:raise RuntimeError('Search budget exceeded; inspect results before extending')
        run=HERE/'results'/f'{args.tag}-{rate}k';published=HERE/f'hardware_{args.tag}_{rate}k'
        print(json.dumps(dict(event='sweep_point_start',rate_kbps=rate,reason=reason)),flush=True)
        cmd=[sys.executable,'-u',str(HERE/'campaign.py'),'--run',str(run),'--backend','native','--rate',str(rate),'--port',args.port,'--publish',str(published)]
        if seed:cmd+=['--seed-backup',str(seed)]
        subprocess.run(cmd,check=True)
        s=json.loads((published/'summary.json').read_text())
        if s['measured']!=1752 or not s['lossless_exact'] or not s['restored_verified']:raise ValueError('Incomplete/unrestored point')
        records[rate]=dict(published=str(published),passes=s['acceptance']['rice_temporal']['passes'])
        state.parent.mkdir(parents=True,exist_ok=True);state.write_text(json.dumps(records,indent=2)+'\n')
        seed=run/'original-flash.bin'
        summarize(records,'ricerca in corso',HERE/f'sweep_{args.tag}')
if __name__=='__main__':main()
