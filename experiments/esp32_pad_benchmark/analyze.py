"""Audit the PAD comparison run and evaluate the criteria fixed in README.md."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import struct
import zlib

ROOT=Path(__file__).resolve().parents[2]
FRAMES=(48,96,145)
VARIANTS=('original','fast')
MODES=('plain','profiled')
ROUNDS=(1,2,3)
VERIFY_INPUTS=32
PAD_OUTPUT_BYTES=49*49*48
# Criteria declared before the measurement (README.md).
MIN_INVOKE_REDUCTION_US=2000
CONSISTENCY_ABS_US=1000
CONSISTENCY_REL=0.25
PROFILE_PAD_P50_US=14628  # 10 November profile, node 4

def percentile(values,p):
    xs=sorted(values);x=(len(xs)-1)*p/100;lo=int(x);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(x-lo)

def metrics(values):
    return dict(p50=percentile(values,50),p95=percentile(values,95),
                mean=sum(values)/len(values),minimum=min(values),maximum=max(values))

def check_verification(rows):
    verify={}
    for row in rows:
        if row['event']!='verify':continue
        if row['input'] in verify:raise ValueError('Duplicate verification')
        verify[row['input']]=row
        if row['pad_checks']!=1 or row['pad_compared_bytes']!=PAD_OUTPUT_BYTES:raise ValueError('PAD tensor not fully compared')
        if row['pad_mismatch_bytes']:raise ValueError('PAD tensor mismatch')
        if row['activation_mismatch_bytes'] or row['reference_fnv32']!=row['fast_fnv32']:raise ValueError('Verification activation mismatch')
    if set(verify)!=set(range(VERIFY_INPUTS)):raise ValueError('Incomplete verification')
    if [verify[i]['frame'] for i in range(3)]!=list(FRAMES):raise ValueError('Canonical inputs out of order')
    done=[r for r in rows if r['event']=='verify_done']
    if len(done)!=1 or not done[0]['all_exact'] or done[0]['pad_bytes_compared']!=VERIFY_INPUTS*PAD_OUTPUT_BYTES:
        raise ValueError('Verification not completed')
    return dict(inputs=VERIFY_INPUTS,canonical=3,random=VERIFY_INPUTS-3,
                pad_bytes_compared=VERIFY_INPUTS*PAD_OUTPUT_BYTES,activation_bytes_compared=VERIFY_INPUTS*4608,
                mismatching_bytes=0)

def check_calibration(rows):
    checks={r['location']:r for r in rows if r['event']=='calibration_check'}
    if 'psram' not in checks:raise ValueError('PSRAM calibration missing')
    if not all(r['fast_equals_reference'] for r in checks.values()):raise ValueError('Calibration outputs differ')
    samples={}
    for row in rows:
        if row['event']!='calibration':continue
        key=(row['location'],row['kernel'],row['iteration'])
        if key in samples:raise ValueError('Duplicate calibration sample')
        samples[key]=row['elapsed_us']
    result={}
    for location in checks:
        result[location]={}
        for kernel in ('memcpy','fast_pad','reference_pad'):
            values=[samples.get((location,kernel,i)) for i in range(30)]
            if None in values:raise ValueError('Incomplete calibration')
            result[location][kernel]=metrics(values)
    skipped=[r['location'] for r in rows if r['event']=='calibration_skipped']
    return dict(locations=result,skipped=skipped)

def summarize(rows,model):
    if any(r['event']=='error' for r in rows):raise ValueError('Device error')
    pad_nodes=[n['index'] for n in model['nodes'] if n['op']=='PAD']
    if len(pad_nodes)!=1:raise ValueError('Expected one PAD node')
    pad=pad_nodes[0]
    verification=check_verification(rows)
    samples={};operators={};blocks={};goldens={}
    for row in rows:
        event=row['event']
        if event=='sample':
            key=(row['variant'],row['mode'],row['round'],row['frame'],row['iteration'])
            if key in samples:raise ValueError('Duplicate sample')
            samples[key]=row
            if not row['exact']:raise ValueError('Activation mismatch')
            if (row['conv_calls'],row['depthwise_calls'])!=(6,3):raise ValueError('Optimized kernel calls missing')
            if row['fast_pad_calls']!=int(row['variant']=='fast'):raise ValueError('Wrong PAD kernel used')
        if event=='operator':
            key=(row['variant'],row['round'],row['frame'],row['iteration'],row['index'])
            if key in operators:raise ValueError('Duplicate operator')
            operators[key]=row
        if event=='block':
            key=(row['phase'],row['variant'],row['mode'],row['round'])
            if key in blocks:raise ValueError('Duplicate block')
            blocks[key]=row
        if event=='golden':
            if row['frame'] in goldens:raise ValueError('Duplicate golden')
            goldens[row['frame']]=row
    expected={(v,m,r,f,i) for v in VARIANTS for m in MODES for r in ROUNDS for f in FRAMES for i in range(30)}
    if set(samples)!=expected:raise ValueError('Incomplete sample matrix')
    expected_ops={(v,r,f,i,n['index']) for v in VARIANTS for r in ROUNDS for f in FRAMES for i in range(30) for n in model['nodes']}
    if set(operators)!=expected_ops:raise ValueError('Incomplete operator matrix')
    measure_blocks={('measure',v,m,r) for v in VARIANTS for m in MODES for r in ROUNDS}
    if set(blocks)!=measure_blocks|{('verify',v,'plain',0) for v in VARIANTS}:raise ValueError('Incomplete blocks')
    if set(goldens)!=set(FRAMES):raise ValueError('Missing golden activations')
    if len({b['arena_address'] for b in blocks.values()})!=1:raise ValueError('Arena moved')
    arena_used={b['variant']:b['arena_used'] for b in blocks.values()}
    if len({b['arena_used'] for b in blocks.values()})!=1:raise ValueError('Arena allocation changed')
    done=[r for r in rows if r['event']=='done']
    if len(done)!=1 or done[0]['samples']!=1080 or done[0]['operator_records']!=5940 or \
       done[0]['verify_inputs']!=VERIFY_INPUTS or not done[0]['all_activations_exact']:
        raise ValueError('Run not completed')
    block_done=Counter(('measure',r['variant'],r['mode'],r['round']) for r in rows if r['event']=='block_done')
    if block_done!=Counter(measure_blocks):raise ValueError('Missing completed block')
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
                median_of_round_p50_us=median(p50([o['elapsed_us'] for k,o in operators.items() if k[0]==v and k[1]==r and k[-1]==node['index']]) for r in ROUNDS)))
    pad_cells={}
    for r in ROUNDS:
        for f in FRAMES:
            cell={v:p50([o['elapsed_us'] for k,o in operators.items() if k[:3]==(v,r,f) and k[-1]==pad]) for v in VARIANTS}
            pad_cells[f'{r}/{f}']=cell
    pad_original=nodes['original'][pad]['median_of_round_p50_us'];pad_fast=nodes['fast'][pad]['median_of_round_p50_us']
    pad_reduction=pad_original-pad_fast
    invoke_reduction=invoke['original']['plain']-invoke['fast']['plain']
    tolerance=max(CONSISTENCY_ABS_US,CONSISTENCY_REL*pad_reduction)
    other_nodes=[dict(index=a['index'],op=a['op'],original_us=a['median_of_round_p50_us'],fast_us=b['median_of_round_p50_us'],
                      delta_us=b['median_of_round_p50_us']-a['median_of_round_p50_us'])
                 for a,b in zip(nodes['original'],nodes['fast']) if a['index']!=pad]
    memories=[r for r in rows if r['event']=='memory']
    memory={v:dict(internal_min_bytes=min(r['internal_min'] for r in memories if r['variant']==v),
                   internal_free_min_bytes=min(r['internal_free'] for r in memories if r['variant']==v)) for v in VARIANTS}
    criteria=dict(
        correctness=True,
        pad_faster_in_every_round_and_frame=all(c['fast']<c['original'] for c in pad_cells.values()),
        invoke_plain_reduction_at_least_2ms=invoke_reduction>=MIN_INVOKE_REDUCTION_US,
        invoke_reduction_consistent_with_pad=abs(invoke_reduction-pad_reduction)<=tolerance)
    verdict='beneficial' if all(criteria.values()) else 'not_beneficial'
    return dict(verification=verification,calibration=check_calibration(rows),
                measured_invocations=1080,warmup_invocations=180,operator_records=len(operators),
                arena_used=arena_used['original'],arena_capacity=next(iter(blocks.values()))['arena_capacity'],
                invoke_median_of_round_p50_us=invoke,rounds=rounds,
                instrumentation_difference_pct={v:(invoke[v]['profiled']/invoke[v]['plain']-1)*100 for v in VARIANTS},
                pad_node=dict(index=pad,original_us=pad_original,fast_us=pad_fast,reduction_us=pad_reduction,
                              reduction_pct=pad_reduction/pad_original*100,per_round_frame_p50_us=pad_cells,
                              original_vs_10_november_pct=(pad_original/PROFILE_PAD_P50_US-1)*100),
                invoke_plain_reduction_us=invoke_reduction,
                invoke_plain_reduction_pct=invoke_reduction/invoke['original']['plain']*100,
                consistency_tolerance_us=tolerance,other_nodes=other_nodes,memory=memory,nodes=nodes,
                criteria=criteria,verdict=verdict),goldens

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
    os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL','3');os.environ.setdefault('CUDA_VISIBLE_DEVICES','-1')
    import numpy as np
    path=ROOT/'experiments/esp32_representation_benchmark/artifacts/int8-prefix.tflite'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=model['model_sha256']:raise ValueError('Model changed')
    data=np.load(ROOT/'experiments/esp32_representation_benchmark/artifacts/inputs.npz')
    import tensorflow as tf
    runtime=tf.lite.Interpreter(model_content=path.read_bytes(),num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    runtime.allocate_tensors();inp=runtime.get_input_details()[0]
    for frame,values in zip(data['frame_ids'],data['frames']):
        values=np.rint(values.astype(np.float64)/inp['quantization'][0]+inp['quantization'][1]).clip(-128,127).astype(np.int8)
        if values.tobytes()!=bytes.fromhex(goldens[int(frame)]['input_hex']):raise ValueError('Input quantization differs')
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
    result.update(model_sha256=model['model_sha256'],pc_input_exact=True,legacy_device_comparison=legacy,
                  all_1260_measurement_activations_match_original_kernel=True,
                  original_flash_and_boot_verified=True,board=completion['board'],mac=hardware['mac'])
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--legacy-archive',type=Path,help='prior ESP32 HTTP archive: canonical activations must match byte for byte')
    a=p.parse_args()
    a.output.write_text(json.dumps(audit(a.run,a.legacy_archive),indent=2)+'\n')
