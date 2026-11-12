"""Audit the PAD-free prefix comparison and evaluate the criteria in README.md."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import median
import struct
import zlib

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
FRAMES=(48,96,145)
MODELS=('pad','nopad')
MEMORIES=('psram','internal')
MODES=('plain','profiled')
ROUNDS=(1,2,3)
VARIANTS=[(m,mem) for m in MODELS for mem in MEMORIES]
# Fit indicator declared before the measurement (README.md): worst board
# internal minimum free in the 9 November client campaign, minus a reserve.
CLIENT_INTERNAL_MIN_FREE=194091
CLIENT_RESERVE=32768
FIT_LIMIT=CLIENT_INTERNAL_MIN_FREE-CLIENT_RESERVE
MEMORY_BENCHMARK_US={('pad','psram'):84723,('pad','internal'):62289}  # 11 November

def percentile(values,p):
    xs=sorted(values);x=(len(xs)-1)*p/100;lo=int(x);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(x-lo)

def metrics(values):
    return dict(p50=percentile(values,50),p95=percentile(values,95),
                mean=sum(values)/len(values),minimum=min(values),maximum=max(values))

def summarize(rows,maps):
    if any(r['event']=='error' for r in rows):raise ValueError('Device error')
    if any(r['event']=='internal_arena_unavailable' for r in rows):raise ValueError('Internal arena unavailable')
    if [n['op'] for n in maps['pad']['nodes'] if n['op']!='PAD']!=[n['op'] for n in maps['nopad']['nodes']]:
        raise ValueError('Model maps do not match')
    peaks={}
    for r in rows:
        if r['event']=='activation_peak':
            if r['model'] in peaks:raise ValueError('Duplicate activation peak')
            peaks[r['model']]=r
    if set(peaks)!=set(MODELS):raise ValueError('Missing activation peak')
    samples={};operators={};blocks={};goldens={}
    for row in rows:
        event=row['event']
        if event=='sample':
            key=(row['model'],row['memory'],row['mode'],row['round'],row['frame'],row['iteration'])
            if key in samples:raise ValueError('Duplicate sample')
            samples[key]=row
            if not row['exact']:raise ValueError('Activation mismatch')
            if (row['conv_calls'],row['depthwise_calls'])!=(6,3):raise ValueError('Optimized kernel calls missing')
            if row['fast_pad_calls']!=int(row['model']=='pad'):raise ValueError('Wrong PAD execution')
        if event=='operator':
            key=(row['model'],row['memory'],row['round'],row['frame'],row['iteration'],row['index'])
            if key in operators:raise ValueError('Duplicate operator')
            operators[key]=row
        if event=='block':
            key=(row['phase'],row['model'],row['memory'],row['mode'],row['round'])
            if key in blocks:raise ValueError('Duplicate block')
            blocks[key]=row
            if row['activations_internal']!=(row['memory']=='internal'):raise ValueError('Activations in the wrong memory')
        if event=='golden':
            if row['frame'] in goldens:raise ValueError('Duplicate golden')
            goldens[row['frame']]=row
    expected={(m,mem,mode,r,f,i) for m,mem in VARIANTS for mode in MODES for r in ROUNDS for f in FRAMES for i in range(30)}
    if set(samples)!=expected:raise ValueError('Incomplete sample matrix')
    expected_ops={(m,mem,r,f,i,n['index']) for m,mem in VARIANTS for r in ROUNDS for f in FRAMES for i in range(30)
                  for n in maps[m]['nodes']}
    if set(operators)!=expected_ops:raise ValueError('Incomplete operator matrix')
    measure={('measure',m,mem,mode,r) for m,mem in VARIANTS for mode in MODES for r in ROUNDS}
    if set(blocks)!=measure|{('reference','pad','psram','plain',0)}:raise ValueError('Incomplete blocks')
    if set(goldens)!=set(FRAMES):raise ValueError('Missing golden activations')
    if len({b['persistent_address'] for b in blocks.values()})!=1:raise ValueError('Persistent arena moved')
    for mem in MEMORIES:
        if len({b['activation_address'] for b in blocks.values() if b['memory']==mem})!=1:raise ValueError('Activation arena moved')
    for m in MODELS:
        if len({b['arena_used'] for b in blocks.values() if b['model']==m})!=1:raise ValueError('Arena allocation changed')
    done=[r for r in rows if r['event']=='done']
    if len(done)!=1 or done[0]['samples']!=2160 or done[0]['operator_records']!=11340 or not done[0]['all_activations_exact']:
        raise ValueError('Run not completed')
    if Counter(('measure',r['model'],r['memory'],r['mode'],r['round']) for r in rows if r['event']=='block_done')!=Counter(measure):
        raise ValueError('Missing completed block')
    for (m,mem,mode,r,f,i),sample in samples.items():
        if mode=='plain':
            if sample['operator_sum_us'] or sample['esp_nn_us']:raise ValueError('Plain instrumentation enabled')
            continue
        selected=[operators[(m,mem,r,f,i,n['index'])] for n in maps[m]['nodes']]
        for node,op in zip(maps[m]['nodes'],selected):
            if op['op']!=node['op']:raise ValueError('Operator tag mismatch')
            if (op['conv_calls'],op['depthwise_calls'])!=(int(node['op']=='CONV_2D'),int(node['op']=='DEPTHWISE_CONV_2D')):
                raise ValueError('Wrong kernel attribution')
            if not 0<=op['esp_nn_us']<=op['elapsed_us']:raise ValueError('Kernel outside operator time')
        nodes=sum(op['elapsed_us'] for op in selected);esp=sum(op['esp_nn_us'] for op in selected)
        if nodes!=sample['operator_sum_us'] or esp!=sample['esp_nn_us']:raise ValueError('Timing totals differ')
        if not 0<=esp<=nodes<=sample['invoke_us']:raise ValueError('Overlapping timing budget')

    def p50(values):return percentile(values,50)
    def key(m,mem):return f'{m}-{mem}'
    rounds={key(m,mem):{mode:[dict(round=r,invoke_us=metrics([s['invoke_us'] for k,s in samples.items() if k[:4]==(m,mem,mode,r)]))
                              for r in ROUNDS] for mode in MODES} for m,mem in VARIANTS}
    invoke={k:{mode:median(x['invoke_us']['p50'] for x in v[mode]) for mode in MODES} for k,v in rounds.items()}
    nodes={}
    for m,mem in VARIANTS:
        nodes[key(m,mem)]=[dict(index=n['index'],op=n['op'],output_shape=n['outputs'][0]['shape'],
            median_of_round_p50_us=median(p50([o['elapsed_us'] for k,o in operators.items() if k[:3]==(m,mem,r) and k[-1]==n['index']]) for r in ROUNDS))
            for n in maps[m]['nodes']]
    # The PAD and the stride-2 depthwise (pad 4+5) become one depthwise (nopad 4).
    pad_index=next(n['index'] for n in maps['pad']['nodes'] if n['op']=='PAD')
    merged={}
    for mem in MEMORIES:
        before=nodes[key('pad',mem)];after=nodes[key('nopad',mem)]
        pad_pair=before[pad_index]['median_of_round_p50_us']+before[pad_index+1]['median_of_round_p50_us']
        merged[mem]=dict(pad_node_us=before[pad_index]['median_of_round_p50_us'],
                         pad_depthwise_us=before[pad_index+1]['median_of_round_p50_us'],
                         pad_pair_us=pad_pair,nopad_depthwise_us=after[pad_index]['median_of_round_p50_us'],
                         gain_us=pad_pair-after[pad_index]['median_of_round_p50_us'])
    plain={k:v['plain'] for k,v in invoke.items()}
    nopad_gain={mem:plain[key('pad',mem)]-plain[key('nopad',mem)] for mem in MEMORIES}
    faster_everywhere={mem:all(p50([s['invoke_us'] for k,s in samples.items() if k[:5]==('nopad',mem,'plain',r,f)])<
                               p50([s['invoke_us'] for k,s in samples.items() if k[:5]==('pad',mem,'plain',r,f)])
                               for r in ROUNDS for f in FRAMES) for mem in MEMORIES}
    peak={m:peaks[m]['min_activation_bytes'] for m in MODELS}
    fits=peak['nopad']<=FIT_LIMIT
    heaps={r['stage']:{k:v for k,v in r.items() if k not in ('event','stage')} for r in rows if r['event']=='heap'}
    return dict(measured_invocations=2160,warmup_invocations=360,operator_records=len(operators),
                activation_peak_bytes=peak,arena_used={m:next(b['arena_used'] for b in blocks.values() if b['model']==m) for m in MODELS},
                heap=heaps,invoke_median_of_round_p50_us=invoke,rounds=rounds,
                instrumentation_difference_pct={k:(v['profiled']/v['plain']-1)*100 for k,v in invoke.items()},
                versus_memory_benchmark_pct={key(*k):(plain[key(*k)]/v-1)*100 for k,v in MEMORY_BENCHMARK_US.items()},
                nopad_plain_gain_us=nopad_gain,nopad_faster_every_round_and_frame=faster_everywhere,
                internal_plain_gain_us={m:plain[key(m,'psram')]-plain[key(m,'internal')] for m in MODELS},
                pad_pair_vs_merged_depthwise=merged,nodes=nodes,
                fit=dict(client_internal_min_free=CLIENT_INTERNAL_MIN_FREE,reserve=CLIENT_RESERVE,limit=FIT_LIMIT,
                         nopad_activation_peak=peak['nopad'],fits_with_reserve=fits,
                         next_step='client_fit_test' if fits else 'free_client_internal_ram')),goldens

def legacy_check(legacy_archive,goldens,model_sha):
    manifest_path=legacy_archive.parent/'manifest.json'
    manifest=json.loads(manifest_path.read_text())
    if manifest['model']['models']['int8']['prefix']['sha256']!=model_sha:raise ValueError('Legacy prefix differs')
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
    return dict(archive=str(legacy_archive),activation_sha256=seen,
                manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),exact=True)

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
    maps={'pad':json.loads((run/'model-map.json').read_text()),'nopad':json.loads((run/'model-map-nopad.json').read_text())}
    result,goldens=summarize(rows,maps)
    boot=[r for r in rows if r['event']=='boot']
    if len(boot)!=1 or boot[0]['model_sha256']!=maps['pad']['model_sha256'] or \
       boot[0]['nopad_model_sha256']!=maps['nopad']['model_sha256'] or boot[0]['wifi'] or boot[0]['camera'] or boot[0]['http']:
        raise ValueError('Unexpected runtime configuration')
    original=ROOT/'experiments/esp32_representation_benchmark/artifacts/int8-prefix.tflite'
    rewritten=HERE/'artifacts/int8-prefix-nopad.tflite'
    if hashlib.sha256(original.read_bytes()).hexdigest()!=maps['pad']['model_sha256']:raise ValueError('Model changed')
    if hashlib.sha256(rewritten.read_bytes()).hexdigest()!=maps['nopad']['model_sha256']:raise ValueError('Rewritten model changed')
    legacy=legacy_check(legacy_archive,goldens,maps['pad']['model_sha256']) if legacy_archive else None
    result.update(model_sha256=maps['pad']['model_sha256'],nopad_model_sha256=maps['nopad']['model_sha256'],
                  legacy_device_comparison=legacy,all_activations_match_original_model=True,
                  original_flash_and_boot_verified=True,board=completion['board'],mac=hardware['mac'])
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--legacy-archive',type=Path,help='prior ESP32 HTTP archive: canonical activations must match byte for byte')
    a=p.parse_args()
    a.output.write_text(json.dumps(audit(a.run,a.legacy_archive),indent=2)+'\n')
