"""Audit the reversible XCLK experiment; incomplete evidence is inconclusive."""
import argparse
import hashlib
import json
from pathlib import Path

PHASES=('baseline','on_1','off_1','on_2','off_2')
TARGETS=('gateway','laptop')
COUNT=50

def percentile(values,q):
    values=sorted(values)
    if not values:return None
    pos=(len(values)-1)*q/100;lo=int(pos);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(pos-lo)

def stats(probes):
    good=[r['elapsed_ms'] for r in probes if r['received']]
    return dict(attempted=len(probes),sent=None,received=len(good),loss_pct=100*(len(probes)-len(good))/len(probes) if probes else None,
                p50_ms=percentile(good,50),p95_ms=percentile(good,95),max_ms=max(good) if good else None)

def analyze_boot(rows):
    issues=[]
    begins=[r for r in rows if r['event']=='xclk_phase_begin']
    if [(r['phase'],r['name']) for r in begins]!=list(enumerate(PHASES)):
        issues.append('Missing, repeated or reordered phase')
    for r in begins:
        if r['phase'] not in range(5) or r['camera_initialized']!=(r['phase']>0) or r['xclk_enabled']!=(r['phase'] in (1,3)):
            issues.append('Wrong phase configuration')
    gates=[r for r in rows if r['event']=='xclk_gate']
    if [r['phase'] for r in gates]!=[1,2,3,4]:issues.append('Missing or reordered GPIO gate')
    for r in gates:
        enabled=r['phase'] in (1,3)
        if r['enabled']!=enabled or r['signal_index']!=(149 if enabled else 256) or not r['route_verified'] or not r['buffers_retained'] or r['gpio']!=15 or (not enabled and not r['output_latch_low']):
            issues.append('GPIO route/latch or retained-buffer check failed')
    done=[r for r in rows if r['event']=='done']
    if len(done)!=1 or done[0].get('experiment')!='xclk_diagnostic' or done[0].get('phases_completed')!=5 or done[0].get('probes_expected')!=500 or not done[0].get('guards') or not done[0].get('heap_integrity'):
        issues.append('Missing successful diagnostic completion')
    if any(r['event']=='error' for r in rows):issues.append('Firmware error')
    if not any(r['event']=='validation' and r.get('inputs')==35 and r.get('exact') and r.get('guards') for r in rows):
        issues.append('Prefix validation missing')
    if not any(r['event']=='camera_init' and r['status']==0 for r in rows):issues.append('Camera init missing')
    if not any(r['event']=='xclk_camera_paused' and r.get('buffers_retained') and r.get('clock_not_disabled') for r in rows):
        issues.append('Camera pause missing')
    memory=[r['internal_min_free'] for r in rows if 'internal_min_free' in r]
    if not memory or min(memory)<32768:issues.append('Internal RAM reserve missing or violated')
    all_probes=[r for r in rows if r['event']=='xclk_ping']
    if len(all_probes)!=500:issues.append('Expected 500 probes per boot')
    summaries=[r for r in rows if r['event']=='xclk_ping_summary']
    if len(summaries)!=10:issues.append('Expected ten target summaries')
    phases={}
    for phase,name in enumerate(PHASES):
        phases[name]={}
        for role in TARGETS:
            probes=[r for r in all_probes if r['phase']==phase and r['target']==role]
            values=stats(probes);phases[name][role]=values
            if [r['sequence'] for r in probes]!=list(range(1,51)):
                issues.append(f'{name}/{role}: missing or duplicate sequence')
            summary=[r for r in summaries if r['phase']==phase and r['target']==role]
            if len(summary)!=1 or summary[0]['attempted']!=COUNT or not values['received']<=summary[0]['sent']<=COUNT or summary[0]['received']!=values['received']:
                issues.append(f'{name}/{role}: counter mismatch')
            elif summary:
                values.update(sent=summary[0]['sent'],local_send_failures=COUNT-summary[0]['sent'])
    # Records must actually appear inside the corresponding phase window.
    current=None
    for row in rows:
        if row['event']=='xclk_phase_begin':current=row['phase']
        if row['event'] in ('xclk_ping','xclk_ping_summary') and row['phase']!=current:
            issues.append('Probe outside its phase window')
    effects={}
    for role in TARGETS:
        baseline=phases['baseline'][role]
        baseline_ok=baseline['received']>=49
        pairs=[]
        for a,b in (('on_1','off_1'),('on_2','off_2')):
            on,off=phases[a][role],phases[b][role]
            healthy=baseline_ok and off['received']>=49 and off['p95_ms'] is not None and off['p95_ms']<=max(100,2*baseline['p95_ms'])
            worse=on['loss_pct'] is not None and off['loss_pct'] is not None and on['loss_pct']-off['loss_pct']>=10
            if on['p50_ms'] is not None and off['p50_ms'] is not None:
                worse=worse or on['p50_ms']>=max(20,3*max(1,off['p50_ms']))
            pairs.append(dict(on=a,off=b,off_recovers=healthy,on_degrades=worse))
        effects[role]=dict(baseline_usable=baseline_ok,pairs=pairs,reproduced=all(p['off_recovers'] and p['on_degrades'] for p in pairs))
    return dict(complete=not issues,issues=sorted(set(issues)),phases=phases,gate_checks=gates,
                minimum_internal_free=min(memory) if memory else None,effects=effects,
                wifi_disconnections=[r for r in rows if r['event']=='wifi_disconnected'])

def classify(boots,measurements_complete):
    complete=measurements_complete and len(boots)==3 and all(b['complete'] for b in boots)
    reproduced=complete and all(b['effects'][role]['reproduced'] for b in boots for role in TARGETS)
    return dict(campaign_complete=complete,conclusion='xclk_effect_reproduced' if reproduced else 'inconclusive',promotion_eligible=False)

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def audit(run):
    run=Path(run);completion=json.loads((run/'completion.json').read_text());meta=json.loads((run/'board/hardware.json').read_text())
    backup=run/'board/original-flash.bin'
    if not (completion['original_boot_confirmed'] and completion['restore_error'] is None and meta['backup_verified'] and meta['restored'] and backup.stat().st_size==8388608 and sha(backup)==meta['backup_sha256']):
        raise ValueError('Complete verified flash recovery required')
    if sha(run/'firmware/firmware.bin')!=meta['installed_sha256']:raise ValueError('Firmware digest mismatch')
    configuration=json.loads((run/'configuration.json').read_text())
    if not configuration.get('xclk_diagnostic') or configuration['commands']!='xxx':raise ValueError('Not the three-boot XCLK campaign')
    for name,digest in json.loads((run/'source-sha256.json').read_text()).items():
        p=run/'sources'/name
        if p.is_file():
            if sha(p)!=digest:raise ValueError('Source snapshot mismatch')
        elif '/idf/.pio/build/' in name:
            if sha(run/'firmware'/Path(name).name)!=digest:raise ValueError('Saved build digest mismatch')
        elif '/idf/components/' not in name:raise ValueError('Required source snapshot missing')
    boots=[]
    for path in sorted((run/'board').glob('round-*.events.jsonl')):
        boot=analyze_boot([json.loads(l)['row'] for l in path.read_text().splitlines()]);boot['file']=path.name;boots.append(boot)
    result=classify(boots,completion['measurements_complete']);result.update(restored=True,boots=boots,error=completion['error'],firmware_sha256=meta['installed_sha256'])
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit(a.run);a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    text='# Diagnostica XCLK della camera\n\n'
    text+='Esito: **'+result['conclusion']+'**. Flash originale ripristinata e boot verificato.\n\n'
    text+='| Avvio | Fase | Destinazione | Risposte | p50 ms | p95 ms |\n|---|---|---|---:|---:|---:|\n'
    for i,boot in enumerate(result['boots'],1):
        for phase,roles in boot['phases'].items():
            for role,s in roles.items():text+=f"| {i} | {phase} | {role} | {s['received']}/{s['attempted']} | {s['p50_ms']} | {s['p95_ms']} |\n"
        if boot['issues']:text+='\nProblemi avvio '+str(i)+': '+', '.join(boot['issues'])+'\n'
    text+='\nCriterio prefissato: tre avvii completi, due recuperi per destinazione/avvio. Baseline e fasi OFF almeno 49/50 risposte; p95 OFF entro max(100 ms, due volte il p95 baseline). Ogni fase ON deve perdere almeno 10 punti percentuali in più della fase OFF abbinata, oppure avere p50 almeno max(20 ms, tre volte max(1 ms, p50 OFF)).\n'
    text+='\nIl routing GPIO è verificato via registri, senza misura con oscilloscopio. Anche un effetto riprodotto non distingue interferenza elettromagnetica e alimentazione, né dimostra stabilità del ciclo camera o vantaggi WebSocket. Nessuna promozione operativa.\n'
    (a.output/'report.md').write_text(text)
    print(json.dumps({k:result[k] for k in ('conclusion','campaign_complete','restored','promotion_eligible')}))

if __name__=='__main__':main()
