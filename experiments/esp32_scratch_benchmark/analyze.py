"""Strict audit and predeclared selection for the strip scratch experiment."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from statistics import median

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
VARIANTS=(0,3,5,7,9)
MEMORIES=('psram','internal')
MODES=('plain','profiled')
FRAMES=(48,96,145)
FIT_LIMIT=194091-32768
ROUNDS=(1,2,3)
TAGS=('CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','CONV_2D','DEPTHWISE_CONV_2D','CONV_2D','ADD')

def percentile(xs,p):
    xs=sorted(xs);x=(len(xs)-1)*p/100;lo=int(x);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(x-lo)

def unique(rows,event,fields,expected):
    result={}
    for r in rows:
        if r['event']!=event:continue
        k=tuple(r[f] for f in fields)
        if k in result:raise ValueError('Duplicate '+event)
        result[k]=r
    if set(result)!=set(expected):raise ValueError('Incomplete '+event)
    return result

def summarize(rows):
    if any(r['event'] in ('error','internal_arena_unavailable') for r in rows):raise ValueError('Device error')
    peaks=unique(rows,'activation_peak',('variant',),[(v,) for v in VARIANTS])
    for (v,),r in peaks.items():
        n=r['min_activation_bytes']
        if n<=0 or n%16 or r['effective_rows']!=(17 if v==0 else v) or r['scratch_bytes']!=432+r['effective_rows']*2352+32:
            raise ValueError('Unexpected scratch variant')
    if peaks[(0,)]['min_activation_bytes']!=178688:raise ValueError('Baseline memory changed')
    validated=unique(rows,'validation',('variant','memory'),[(v,m) for v in VARIANTS for m in MEMORIES])
    if any(r['inputs']!=35 or not r['exact'] or not r['guards'] for r in validated.values()):raise ValueError('Validation mismatch')
    keys=[(v,m,mode,r) for v in VARIANTS for m in MEMORIES for mode in MODES for r in ROUNDS]
    blocks=unique(rows,'block',('variant','memory','mode','round'),keys)
    unique(rows,'block_done',('variant','memory','mode','round'),keys)
    for (v,m,mode,r),b in blocks.items():
        if b['arena_bytes']!=peaks[(v,)]['min_activation_bytes']:raise ValueError('Wrong arena size')
    if len({b['persistent_address'] for b in blocks.values()})!=1:raise ValueError('Persistent address changed')
    for m in MEMORIES:
        if len({b['activation_address'] for k,b in blocks.items() if k[1]==m})!=1:raise ValueError('Activation address changed')
    if blocks[(0,'psram','plain',1)]['activation_address']==blocks[(0,'internal','plain',1)]['activation_address']:raise ValueError('Memory addresses overlap')
    skeys=[k+(f,i) for k in keys for f in FRAMES for i in range(30)]
    samples=unique(rows,'sample',('variant','memory','mode','round','frame','iteration'),skeys)
    okeys=[(v,m,r,f,i,n) for v in VARIANTS for m in MEMORIES for r in ROUNDS for f in FRAMES for i in range(30) for n in range(10)]
    ops=unique(rows,'operator',('variant','memory','round','frame','iteration','index'),okeys)
    for k,s in samples.items():
        if not s['exact'] or not s['guards'] or (s['conv_calls'],s['depthwise_calls'])!=(6,3):raise ValueError('Sample correctness failed')
        if s['invoke_us']<=0:raise ValueError('Invalid timing')
        if k[2]=='plain':
            if s['operator_sum_us']:raise ValueError('Plain profiler active')
        else:
            selected=[ops[(k[0],k[1],k[3],k[4],k[5],n)] for n in range(10)]
            for n,o in enumerate(selected):
                if o['op']!=TAGS[n] or not 0<=o['esp_nn_us']<=o['elapsed_us']:raise ValueError('Operator mismatch')
            if sum(o['elapsed_us'] for o in selected)!=s['operator_sum_us'] or not 0<=s['operator_sum_us']<=s['invoke_us']:raise ValueError('Timing budget mismatch')
    done=[r for r in rows if r['event']=='done']
    if len(done)!=1 or any(done[0].get(k)!=v for k,v in dict(samples=5400,operator_records=27000,warmup_invocations=900,all_activations_exact=True).items()):raise ValueError('Run incomplete')
    unique(rows,'golden',('frame',),[(f,) for f in FRAMES])
    stats={}
    for v in VARIANTS:
        stats[str(v)]={}
        for m in MEMORIES:
            stats[str(v)][m]={}
            for mode in MODES:
                rs=[]
                for r in ROUNDS:
                    values=[samples[(v,m,mode,r,f,i)]['invoke_us'] for f in FRAMES for i in range(30)]
                    rs.append(dict(round=r,p50=percentile(values,50),p95=percentile(values,95)))
                stats[str(v)][m][mode]=dict(rounds=rs,p50=median(x['p50'] for x in rs),p95=median(x['p95'] for x in rs))
    eligible=[];decisions={}
    for v in VARIANTS[1:]:
        candidate=stats[str(v)]['internal']['plain'];base=stats['0']['internal']['plain']
        fits=peaks[(v,)]['min_activation_bytes']<=FIT_LIMIT
        timing=all(c[p]<=b[p]*1.05 for c,b in zip(candidate['rounds'],base['rounds']) for p in ('p50','p95'))
        decisions[str(v)]=dict(fits=fits,timing_within_5pct_each_round=timing)
        if fits and timing:eligible.append(v)
    winner=None
    if eligible:
        best=min(stats[str(v)]['internal']['plain']['p50'] for v in eligible)
        tied=[v for v in eligible if stats[str(v)]['internal']['plain']['p50']<=best*1.01]
        winner=min(tied,key=lambda v:(peaks[(v,)]['min_activation_bytes'],stats[str(v)]['internal']['plain']['p50'],v))
    operator_times={str(v):{m:[median(percentile([ops[(v,m,r,f,i,n)]['elapsed_us'] for f in FRAMES for i in range(30)],50) for r in ROUNDS) for n in range(10)] for m in MEMORIES} for v in VARIANTS}
    return dict(measured_invocations=5400,activation_peak_bytes={str(v):peaks[(v,)]['min_activation_bytes'] for v in VARIANTS},
                scratch_bytes={str(v):peaks[(v,)]['scratch_bytes'] for v in VARIANTS},fit_limit=FIT_LIMIT,stats=stats,decisions=decisions,
                selected_variant=winner,operator_p50_us=operator_times,hardware_fit_not_yet_verified=True)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def verify_sources(run,hashes):
    # Audit the captured source versions: later README/report updates are valid.
    # Components are frozen locally; installed binaries have private run copies.
    for path,digest in hashes.items():
        if '/idf/components/' in path:
            source=ROOT/path
        elif '/idf/.pio/build/espnn/' in path:
            source=run/'firmware'/Path(path).name
        else:
            source=run/'sources'/path
        if not source.is_file() or sha(source)!=digest:
            raise ValueError('Captured source or firmware changed: '+path)

def check_recovery(completion,hardware):
    if completion.get('board')!='B' or hardware.get('mac')!='24:ec:4a:0e:c3:14':raise ValueError('Wrong board')
    if not completion.get('measurements_complete') or completion.get('error') or completion.get('restore_error') or not completion.get('original_boot_confirmed') or not hardware.get('restored') or not hardware.get('restored_digest_verified_before_boot'):
        raise ValueError('Run or recovery incomplete')

def audit(run,legacy_archive):
    completion=json.loads((run/'completion.json').read_text());hardware=json.loads((run/'board/hardware.json').read_text())
    check_recovery(completion,hardware)
    if sha(run/'board/original-flash.bin')!=hardware['backup_sha256']:raise ValueError('Backup changed')
    if b'sciot_esp32_client' not in (run/'board/restored-boot.log').read_bytes():raise ValueError('Original boot unconfirmed')
    raw=(run/'board/serial.log').read_bytes()
    if any(x in raw for x in (b'task_wdt:',b'Guru Meditation Error',b'Brownout detector')):raise ValueError('Invalid device log')
    rows=[json.loads(s)['row'] for s in (run/'board/events.jsonl').read_text().splitlines()]
    boot=[r for r in rows if r['event']=='boot']
    maps={name:json.loads((run/f'model-map{suffix}.json').read_text()) for name,suffix in [('pad',''),('nopad','-nopad')]}
    if len(boot)!=1 or boot[0]['experiment']!='scratch_benchmark' or any(boot[0][k] for k in ('wifi','camera','http')) or (boot[0]['cpu_mhz'],boot[0]['psram_mhz'])!=(240,80):raise ValueError('Unexpected runtime')
    if boot[0]['model_sha256']!=maps['pad']['model_sha256'] or boot[0]['nopad_model_sha256']!=maps['nopad']['model_sha256']:raise ValueError('Wrong model')
    if tuple(n['op'] for n in maps['nopad']['nodes'])!=TAGS:raise ValueError('Wrong model operators')
    hashes=json.loads((run/'source-sha256.json').read_text())
    verify_sources(run,hashes)
    # The canonical archive is mandatory, and independently verifies earlier device output.
    import importlib.util
    spec=importlib.util.spec_from_file_location('nopad_audit',ROOT/'experiments/esp32_nopad_benchmark/analyze.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=summarize(rows)
    goldens={r['frame']:r for r in rows if r['event']=='golden'}
    result['legacy_device_comparison']=module.legacy_check(legacy_archive,goldens,maps['pad']['model_sha256'])
    result.update(original_flash_and_boot_verified=True,board='B',mac=hardware['mac'],model_sha256=maps['nopad']['model_sha256'])
    return result

def write_report(result,output):
    output.mkdir(parents=True,exist_ok=True)
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    table=io.StringIO();writer=csv.writer(table);writer.writerow(['rows','memory','peak_bytes','scratch_bytes','p50_us','p95_us','eligible'])
    for v in VARIANTS:
        for m in MEMORIES:
            s=result['stats'][str(v)][m]['plain'];d=result['decisions'].get(str(v),{})
            writer.writerow([17 if v==0 else v,m,result['activation_peak_bytes'][str(v)],result['scratch_bytes'][str(v)],s['p50'],s['p95'],d.get('fits',False) and d.get('timing_within_5pct_each_round',False)])
    (output/'measurements.csv').write_text(table.getvalue())
    winner=result['selected_variant']
    text='# Buffer a strisce ESP-NN — risultati\n\n'
    text+=f'Variante selezionata: **{str(winner)+" righe" if winner else "nessuna"}**. 5.400 inferenze misurate, output esatti e ripristino verificato.\n\n'
    text+='| Righe | Memoria | Picco byte | p50 ms | p95 ms |\n|---|---|---:|---:|---:|\n'
    for v in VARIANTS:
        for m in MEMORIES:
            s=result['stats'][str(v)][m]['plain'];text+=f'| {17 if v==0 else v} | {m} | {result["activation_peak_bytes"][str(v)]} | {s["p50"]/1000:.3f} | {s["p95"]/1000:.3f} |\n'
    text+='\nMediane dei percentili di tre round. Limite preliminare: 161.323 byte; guardie, correttezza e tempi controllati. Una scheda, input fissi, senza camera/Wi-Fi/HTTP. La capienza del client completo e il suo ciclo restano da misurare.\n'
    (output/'report.md').write_text(text)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--legacy-archive',type=Path,required=True)
    a=p.parse_args();write_report(audit(a.run,a.legacy_archive),a.output)
