"""Audit the depthwise strip-cap comparison and evaluate the criteria in README.md."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import median

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
FRAMES=(48,96,145)
MODES=('plain','profiled')
ROUNDS=(1,2,3)
# name -> (cap, rows per strip, strips per Invoke) for the 49x49x48 padded depthwise.
VARIANTS={'rows17':(0,17,3),'rows7':(7,7,8),'rows5':(5,5,12),'rows3':(3,3,24)}
BASELINE='rows17'
DEPTHWISE_INDEX=4
# Fixed before the measurement (README.md).
CLIENT_INTERNAL_MIN_FREE=194091
CLIENT_RESERVE=32768
FIT_LIMIT=CLIENT_INTERNAL_MIN_FREE-CLIENT_RESERVE
TIE_US=50
NOPAD_BENCHMARK={'invoke_plain_us':62244,'depthwise_us':4697,'activation_peak':178688}  # 11 November, nopad-internal

def percentile(values,p):
    xs=sorted(values);x=(len(xs)-1)*p/100;lo=int(x);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(x-lo)

def metrics(values):
    return dict(p50=percentile(values,50),p95=percentile(values,95),
                mean=sum(values)/len(values),minimum=min(values),maximum=max(values))

def choose(peaks,plain):
    """Fastest variant within the limit; within TIE_US of it, the one with the smaller peak."""
    fitting=[v for v in VARIANTS if peaks[v]<=FIT_LIMIT]
    if not fitting:return None
    best=min(plain[v] for v in fitting)
    return min((v for v in fitting if plain[v]-best<=TIE_US),key=lambda v:(peaks[v],plain[v]))

def summarize(rows,node_map):
    if any(r['event']=='error' for r in rows):raise ValueError('Device error')
    if any(r['event']=='internal_arena_unavailable' for r in rows):raise ValueError('Internal arena unavailable')
    nodes_expected=node_map['nodes']
    if nodes_expected[DEPTHWISE_INDEX]['op']!='DEPTHWISE_CONV_2D':raise ValueError('Unexpected model map')
    peaks={}
    for r in rows:
        if r['event']=='activation_peak':
            if r['model']!='nopad' or r['variant'] in peaks:raise ValueError('Unexpected or duplicate activation peak')
            if r['cap']!=VARIANTS[r['variant']][0]:raise ValueError('Wrong cap in activation peak')
            peaks[r['variant']]=r['min_activation_bytes']
    if set(peaks)!=set(VARIANTS):raise ValueError('Missing activation peak')
    samples={};operators={};blocks={};goldens={}
    for row in rows:
        event=row['event']
        if event=='sample':
            key=(row['variant'],row['mode'],row['round'],row['frame'],row['iteration'])
            if key in samples:raise ValueError('Duplicate sample')
            samples[key]=row
            if not row['exact']:raise ValueError('Activation mismatch')
            if (row['conv_calls'],row['depthwise_calls'])!=(6,3):raise ValueError('Optimized kernel calls missing')
            if row['fast_pad_calls']!=0:raise ValueError('PAD executed')
            if (row['strip_rows'],row['strips'])!=VARIANTS[row['variant']][1:]:raise ValueError('Wrong strip geometry')
        if event=='operator':
            key=(row['variant'],row['round'],row['frame'],row['iteration'],row['index'])
            if key in operators:raise ValueError('Duplicate operator')
            operators[key]=row
        if event=='block':
            key=(row['phase'],row['variant'],row['mode'],row['round'])
            if key in blocks:raise ValueError('Duplicate block')
            blocks[key]=row
            if row['phase']=='measure' and (row['model'],row['memory'],row['activations_internal'])!=('nopad','internal',True):
                raise ValueError('Measured block not PAD-free in internal RAM')
        if event=='golden':
            if row['frame'] in goldens:raise ValueError('Duplicate golden')
            goldens[row['frame']]=row
    expected={(v,mode,r,f,i) for v in VARIANTS for mode in MODES for r in ROUNDS for f in FRAMES for i in range(30)}
    if set(samples)!=expected:raise ValueError('Incomplete sample matrix')
    expected_ops={(v,r,f,i,n['index']) for v in VARIANTS for r in ROUNDS for f in FRAMES for i in range(30) for n in nodes_expected}
    if set(operators)!=expected_ops:raise ValueError('Incomplete operator matrix')
    measure={('measure',v,mode,r) for v in VARIANTS for mode in MODES for r in ROUNDS}
    if set(blocks)!=measure|{('reference','reference','plain',0)}:raise ValueError('Incomplete blocks')
    reference=blocks[('reference','reference','plain',0)]
    if (reference['model'],reference['memory'])!=('pad','psram'):raise ValueError('Reference is not the original model in PSRAM')
    if set(goldens)!=set(FRAMES):raise ValueError('Missing golden activations')
    if len({b['persistent_address'] for b in blocks.values()})!=1:raise ValueError('Persistent arena moved')
    if len({b['activation_address'] for k,b in blocks.items() if k[0]=='measure'})!=1:raise ValueError('Activation arena moved')
    for v in VARIANTS:
        if len({b['arena_used'] for k,b in blocks.items() if k[1]==v})!=1:raise ValueError('Arena allocation changed')
    done=[r for r in rows if r['event']=='done']
    if len(done)!=1 or done[0]['samples']!=2160 or done[0]['operator_records']!=10800 or not done[0]['all_activations_exact']:
        raise ValueError('Run not completed')
    if Counter(('measure',r['variant'],r['mode'],r['round']) for r in rows if r['event']=='block_done')!=Counter(measure):
        raise ValueError('Missing completed block')
    for (v,mode,r,f,i),sample in samples.items():
        if mode=='plain':
            if sample['operator_sum_us'] or sample['esp_nn_us']:raise ValueError('Plain instrumentation enabled')
            continue
        selected=[operators[(v,r,f,i,n['index'])] for n in nodes_expected]
        for node,op in zip(nodes_expected,selected):
            if op['op']!=node['op']:raise ValueError('Operator tag mismatch')
            if (op['conv_calls'],op['depthwise_calls'])!=(int(node['op']=='CONV_2D'),int(node['op']=='DEPTHWISE_CONV_2D')):
                raise ValueError('Wrong kernel attribution')
            if not 0<=op['esp_nn_us']<=op['elapsed_us']:raise ValueError('Kernel outside operator time')
        total=sum(op['elapsed_us'] for op in selected);esp=sum(op['esp_nn_us'] for op in selected)
        if total!=sample['operator_sum_us'] or esp!=sample['esp_nn_us']:raise ValueError('Timing totals differ')
        if not 0<=esp<=total<=sample['invoke_us']:raise ValueError('Overlapping timing budget')

    def p50(values):return percentile(values,50)
    rounds={v:{mode:[dict(round=r,invoke_us=metrics([s['invoke_us'] for k,s in samples.items() if k[:3]==(v,mode,r)]))
                      for r in ROUNDS] for mode in MODES} for v in VARIANTS}
    invoke={v:{mode:median(x['invoke_us']['p50'] for x in rounds[v][mode]) for mode in MODES} for v in VARIANTS}
    nodes={v:[dict(index=n['index'],op=n['op'],
                   median_of_round_p50_us=median(p50([o['elapsed_us'] for k,o in operators.items() if k[:2]==(v,r) and k[-1]==n['index']])
                                                 for r in ROUNDS)) for n in nodes_expected] for v in VARIANTS}
    plain={v:invoke[v]['plain'] for v in VARIANTS}
    depthwise={v:nodes[v][DEPTHWISE_INDEX]['median_of_round_p50_us'] for v in VARIANTS}
    # Every non-baseline variant against the baseline, per round and frame (plain p50).
    def cell(v,r,f):return p50([s['invoke_us'] for k,s in samples.items() if k[:4]==(v,'plain',r,f)])
    slower_every_cell={v:all(cell(v,r,f)>cell(BASELINE,r,f) for r in ROUNDS for f in FRAMES) for v in VARIANTS if v!=BASELINE}
    chosen=choose(peaks,plain)
    heaps={r['stage']:{k:v for k,v in r.items() if k not in ('event','stage')} for r in rows if r['event']=='heap'}
    return dict(measured_invocations=len(samples),warmup_invocations=360,operator_records=len(operators),
                activation_peak_bytes=peaks,arena_used={v:next(b['arena_used'] for k,b in blocks.items() if k[1]==v) for v in VARIANTS},
                heap=heaps,invoke_median_of_round_p50_us=invoke,rounds=rounds,
                instrumentation_difference_pct={v:(x['profiled']/x['plain']-1)*100 for v,x in invoke.items()},
                plain_cost_vs_baseline_us={v:plain[v]-plain[BASELINE] for v in VARIANTS},
                depthwise_us=depthwise,depthwise_cost_vs_baseline_us={v:depthwise[v]-depthwise[BASELINE] for v in VARIANTS},
                slower_than_baseline_every_round_and_frame=slower_every_cell,
                baseline_vs_nopad_benchmark=dict(reference=NOPAD_BENCHMARK,
                    invoke_pct=(plain[BASELINE]/NOPAD_BENCHMARK['invoke_plain_us']-1)*100,
                    depthwise_pct=(depthwise[BASELINE]/NOPAD_BENCHMARK['depthwise_us']-1)*100,
                    activation_peak_equal=peaks[BASELINE]==NOPAD_BENCHMARK['activation_peak']),
                nodes=nodes,
                fit=dict(client_internal_min_free=CLIENT_INTERNAL_MIN_FREE,reserve=CLIENT_RESERVE,limit=FIT_LIMIT,
                         margin_bytes={v:FIT_LIMIT-peaks[v] for v in VARIANTS},
                         fits_with_reserve={v:peaks[v]<=FIT_LIMIT for v in VARIANTS},
                         chosen=chosen,next_step='client_fit_test' if chosen else 'free_client_internal_ram')),goldens

def audit(run):
    completion=json.loads((run/'completion.json').read_text())
    if not completion['measurements_complete'] or completion['error'] or completion['restore_error'] or not completion['original_boot_confirmed']:
        raise ValueError('Run or recovery incomplete')
    hardware=json.loads((run/'board/hardware.json').read_text())
    if not hardware['restored'] or not hardware['restored_digest_verified_before_boot']:
        raise ValueError('Flash restoration unverified')
    if hashlib.sha256((run/'board/original-flash.bin').read_bytes()).hexdigest()!=hardware['backup_sha256']:
        raise ValueError('Backup changed')
    if b'sciot_esp32_client' not in (run/'board/restored-boot.log').read_bytes():raise ValueError('Original boot unconfirmed')
    raw=(run/'board/serial.log').read_bytes()
    if any(v in raw for v in (b'task_wdt:',b'Guru Meditation Error',b'Brownout detector')):raise ValueError('Invalid serial output')
    rows=[json.loads(s)['row'] for s in (run/'board/events.jsonl').read_text().splitlines()]
    original_map=json.loads((run/'model-map.json').read_text());nopad_map=json.loads((run/'model-map-nopad.json').read_text())
    result,goldens=summarize(rows,nopad_map)
    boot=[r for r in rows if r['event']=='boot']
    if len(boot)!=1 or boot[0]['model_sha256']!=original_map['model_sha256'] or boot[0]['nopad_model_sha256']!=nopad_map['model_sha256'] \
       or boot[0]['wifi'] or boot[0]['camera'] or boot[0]['http'] or boot[0]['dual_core']:
        raise ValueError('Unexpected runtime configuration')
    original=ROOT/'experiments/esp32_representation_benchmark/artifacts/int8-prefix.tflite'
    rewritten=ROOT/'experiments/esp32_nopad_benchmark/artifacts/int8-prefix-nopad.tflite'
    if hashlib.sha256(original.read_bytes()).hexdigest()!=original_map['model_sha256']:raise ValueError('Model changed')
    if hashlib.sha256(rewritten.read_bytes()).hexdigest()!=nopad_map['model_sha256']:raise ValueError('Rewritten model changed')
    result.update(model_sha256=original_map['model_sha256'],nopad_model_sha256=nopad_map['model_sha256'],
                  golden_activation_sha256={f:hashlib.sha256(bytes.fromhex(g['activation_hex'])).hexdigest() for f,g in sorted(goldens.items())},
                  all_activations_match_original_model=True,original_flash_and_boot_verified=True,
                  board=completion['board'],mac=hardware['mac'])
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    a.output.write_text(json.dumps(audit(a.run),indent=2)+'\n')
