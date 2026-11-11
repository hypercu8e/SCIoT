"""Audit the activation-memory comparison and apply the decision rule in README.md."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import median
import struct
import zlib

ROOT=Path(__file__).resolve().parents[2]
FRAMES=(48,96,145)
VARIANTS=('psram','internal')
MODES=('plain','profiled')
ROUNDS=(1,2,3)
# Decision rule declared before the measurement (README.md).
NON_PAD_GAIN_THRESHOLD_US=5000
PAD_BENCHMARK_FAST_INVOKE_US=84482  # 11 November, single PSRAM arena, fast PAD

def percentile(values,p):
    xs=sorted(values);x=(len(xs)-1)*p/100;lo=int(x);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(x-lo)

def metrics(values):
    return dict(p50=percentile(values,50),p95=percentile(values,95),
                mean=sum(values)/len(values),minimum=min(values),maximum=max(values))

def summarize(rows,model):
    if any(r['event']=='error' for r in rows):raise ValueError('Device error')
    if any(r['event']=='internal_arena_unavailable' for r in rows):raise ValueError('Internal arena unavailable')
    pad_nodes=[n['index'] for n in model['nodes'] if n['op']=='PAD']
    if len(pad_nodes)!=1:raise ValueError('Expected one PAD node')
    pad=pad_nodes[0]
    samples={};operators={};blocks={};goldens={}
    for row in rows:
        event=row['event']
        if event=='sample':
            key=(row['variant'],row['mode'],row['round'],row['frame'],row['iteration'])
            if key in samples:raise ValueError('Duplicate sample')
            samples[key]=row
            if not row['exact']:raise ValueError('Activation mismatch')
            if (row['conv_calls'],row['depthwise_calls'])!=(6,3):raise ValueError('Optimized kernel calls missing')
            if row['fast_pad_calls']!=1:raise ValueError('Fast PAD not used')
        if event=='operator':
            key=(row['variant'],row['round'],row['frame'],row['iteration'],row['index'])
            if key in operators:raise ValueError('Duplicate operator')
            operators[key]=row
        if event=='block':
            key=(row['variant'],row['mode'],row['round'])
            if key in blocks:raise ValueError('Duplicate block')
            blocks[key]=row
            if row['activations_internal']!=(row['variant']=='internal'):raise ValueError('Activations in the wrong memory')
        if event=='golden':
            if row['frame'] in goldens:raise ValueError('Duplicate golden')
            goldens[row['frame']]=row
    expected={(v,m,r,f,i) for v in VARIANTS for m in MODES for r in ROUNDS for f in FRAMES for i in range(30)}
    if set(samples)!=expected:raise ValueError('Incomplete sample matrix')
    expected_ops={(v,r,f,i,n['index']) for v in VARIANTS for r in ROUNDS for f in FRAMES for i in range(30) for n in model['nodes']}
    if set(operators)!=expected_ops:raise ValueError('Incomplete operator matrix')
    all_blocks={(v,m,r) for v in VARIANTS for m in MODES for r in ROUNDS}
    if set(blocks)!=all_blocks:raise ValueError('Incomplete blocks')
    if set(goldens)!=set(FRAMES):raise ValueError('Missing golden activations')
    if len({b['persistent_address'] for b in blocks.values()})!=1:raise ValueError('Persistent arena moved')
    for v in VARIANTS:
        if len({b['activation_address'] for b in blocks.values() if b['variant']==v})!=1:raise ValueError('Activation arena moved')
    if len({b['arena_used'] for b in blocks.values()})!=1:raise ValueError('Arena allocation changed')
    done=[r for r in rows if r['event']=='done']
    if len(done)!=1 or done[0]['samples']!=1080 or done[0]['operator_records']!=5940 or not done[0]['all_activations_exact']:
        raise ValueError('Run not completed')
    if Counter((r['variant'],r['mode'],r['round']) for r in rows if r['event']=='block_done')!=Counter(all_blocks):
        raise ValueError('Missing completed block')
    for (v,m,r,f,i),sample in samples.items():
        if m=='plain':
            if sample['operator_sum_us'] or sample['esp_nn_us']:raise ValueError('Plain instrumentation enabled')
            continue
        selected=[operators[(v,r,f,i,n['index'])] for n in model['nodes']]
        for node,op in zip(model['nodes'],selected):
            if op['op']!=node['op']:raise ValueError('Operator tag mismatch')
            if (op['conv_calls'],op['depthwise_calls'])!=(int(node['op']=='CONV_2D'),int(node['op']=='DEPTHWISE_CONV_2D')):
                raise ValueError('Wrong kernel attribution')
            if not 0<=op['esp_nn_us']<=op['elapsed_us']:raise ValueError('Kernel outside operator time')
        nodes=sum(op['elapsed_us'] for op in selected);esp=sum(op['esp_nn_us'] for op in selected)
        if nodes!=sample['operator_sum_us'] or esp!=sample['esp_nn_us']:raise ValueError('Timing totals differ')
        if not 0<=esp<=nodes<=sample['invoke_us']:raise ValueError('Overlapping timing budget')

    def p50(values):return percentile(values,50)
    rounds={v:{m:[dict(round=r,invoke_us=metrics([s['invoke_us'] for (vv,mm,rr,f,i),s in samples.items() if (vv,mm,rr)==(v,m,r)]))
                    for r in ROUNDS] for m in MODES} for v in VARIANTS}
    invoke={v:{m:median(x['invoke_us']['p50'] for x in rounds[v][m]) for m in MODES} for v in VARIANTS}
    nodes={}
    for v in VARIANTS:
        nodes[v]=[]
        for node in model['nodes']:
            sel=[o for k,o in operators.items() if k[0]==v and k[-1]==node['index']]
            nodes[v].append(dict(index=node['index'],op=node['op'],output_shape=node['outputs'][0]['shape'],
                elapsed_us=metrics([o['elapsed_us'] for o in sel]),
                esp_nn_us=metrics([o['esp_nn_us'] for o in sel]),
                median_of_round_p50_us=median(p50([o['elapsed_us'] for k,o in operators.items() if k[0]==v and k[1]==r and k[-1]==node['index']]) for r in ROUNDS)))
    per_node=[dict(index=a['index'],op=a['op'],psram_us=a['median_of_round_p50_us'],internal_us=b['median_of_round_p50_us'],
                   gain_us=a['median_of_round_p50_us']-b['median_of_round_p50_us'],
                   gain_pct=(a['median_of_round_p50_us']-b['median_of_round_p50_us'])/a['median_of_round_p50_us']*100)
              for a,b in zip(nodes['psram'],nodes['internal'])]
    pad_gain=next(n['gain_us'] for n in per_node if n['index']==pad)
    non_pad_gain=sum(n['gain_us'] for n in per_node if n['index']!=pad)
    invoke_gain=invoke['psram']['plain']-invoke['internal']['plain']
    gain_everywhere={f'{r}/{f}':p50([s['invoke_us'] for k,s in samples.items() if k[:4]==('internal','plain',r,f)])<
                                 p50([s['invoke_us'] for k,s in samples.items() if k[:4]==('psram','plain',r,f)])
                     for r in ROUNDS for f in FRAMES}
    heaps={r['stage']:{k:v for k,v in r.items() if k not in ('event','stage')} for r in rows if r['event']=='heap'}
    memories=[r for r in rows if r['event']=='memory']
    decision='pursue_memory' if non_pad_gain>=NON_PAD_GAIN_THRESHOLD_US else 'port_to_client'
    return dict(measured_invocations=1080,warmup_invocations=180,operator_records=len(operators),
                arena_used=next(iter(blocks.values()))['arena_used'],
                persistent_capacity=next(iter(blocks.values()))['persistent_capacity'],
                activation_capacity=next(iter(blocks.values()))['activation_capacity'],
                heap=heaps,internal_min_bytes=min(r['internal_min'] for r in memories),
                invoke_median_of_round_p50_us=invoke,rounds=rounds,
                instrumentation_difference_pct={v:(invoke[v]['profiled']/invoke[v]['plain']-1)*100 for v in VARIANTS},
                psram_vs_pad_benchmark_pct=(invoke['psram']['plain']/PAD_BENCHMARK_FAST_INVOKE_US-1)*100,
                invoke_plain_gain_us=invoke_gain,invoke_plain_gain_pct=invoke_gain/invoke['psram']['plain']*100,
                internal_faster_every_round_and_frame=all(gain_everywhere.values()),
                pad_gain_us=pad_gain,non_pad_gain_us=non_pad_gain,per_node=per_node,nodes=nodes,
                decision_rule=dict(non_pad_gain_threshold_us=NON_PAD_GAIN_THRESHOLD_US,decision=decision)),goldens

def audit(run,legacy_archive=None):
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
    model=json.loads((run/'model-map.json').read_text())
    result,goldens=summarize(rows,model)
    boot=[r for r in rows if r['event']=='boot']
    if len(boot)!=1 or boot[0]['model_sha256']!=model['model_sha256'] or boot[0]['wifi'] or boot[0]['camera'] or boot[0]['http']:
        raise ValueError('Unexpected runtime configuration')
    path=ROOT/'experiments/esp32_representation_benchmark/artifacts/int8-prefix.tflite'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=model['model_sha256']:raise ValueError('Model changed')
    legacy=None
    if legacy_archive:
        manifest_path=legacy_archive.parent/'manifest.json'
        manifest=json.loads(manifest_path.read_text())
        if manifest['model']['models']['int8']['prefix']['sha256']!=model['model_sha256']:raise ValueError('Legacy prefix differs')
        seen={}
        with legacy_archive.open('rb') as f:
            while sizes:=f.read(8):
                if len(sizes)!=8:raise ValueError('Truncated legacy record')
                nb,nr=struct.unpack('<II',sizes);body=f.read(nb);reply=f.read(nr)
                if len(body)!=nb or len(reply)!=nr:raise ValueError('Truncated legacy archive')
                header=struct.unpack('<8I',body[:32]);frame=header[3]
                if frame in goldens and frame not in seen:
                    if header[2]!=1 or zlib.crc32(body[32:])!=header[7]:raise ValueError('Legacy activation invalid')
                    if body[32:]!=bytes.fromhex(goldens[frame]['activation_hex']):raise ValueError('Device differs from previous ESP32 runtime')
                    seen[frame]=hashlib.sha256(body[32:]).hexdigest()
                if len(seen)==3:break
        if set(seen)!=set(FRAMES):raise ValueError('Legacy frames missing')
        legacy=dict(archive=str(legacy_archive),activation_sha256=seen,
                    manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),exact=True)
    result.update(model_sha256=model['model_sha256'],legacy_device_comparison=legacy,
                  all_1260_activations_match_reference=True,
                  original_flash_and_boot_verified=True,board=completion['board'],mac=hardware['mac'])
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--legacy-archive',type=Path,help='prior ESP32 HTTP archive: canonical activations must match byte for byte')
    a=p.parse_args()
    a.output.write_text(json.dumps(audit(a.run,a.legacy_archive),indent=2)+'\n')
