"""Audit complete profiling events and validate fixed activations on the PC."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import struct
import zlib

ROOT=Path(__file__).resolve().parents[2]
FRAMES=(48,96,145)

def percentile(values,p):
    xs=sorted(values);x=(len(xs)-1)*p/100;lo=int(x);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(x-lo)

def metrics(values):
    return dict(p50=percentile(values,50),p95=percentile(values,95),
                mean=sum(values)/len(values),minimum=min(values),maximum=max(values))

def summarize(rows,model):
    if any(r['event']=='error' for r in rows):raise ValueError('Device error')
    samples={};operators={};blocks={};goldens={}
    for row in rows:
        event=row['event']
        if event=='sample':
            key=(row['mode'],row['round'],row['frame'],row['iteration'])
            if key in samples:raise ValueError('Duplicate sample')
            samples[key]=row
            if not row['exact']:raise ValueError('Activation mismatch')
            if (row['conv_calls'],row['depthwise_calls'])!=(6,3):raise ValueError('Optimized kernel calls missing')
        if event=='operator':
            key=(row['round'],row['frame'],row['iteration'],row['index'])
            if key in operators:raise ValueError('Duplicate operator')
            operators[key]=row
        if event=='block':
            key=(row['mode'],row['round'])
            if key in blocks:raise ValueError('Duplicate block')
            blocks[key]=row
        if event=='golden':
            if row['frame'] in goldens:raise ValueError('Duplicate golden')
            goldens[row['frame']]=row
    expected={(mode,r,f,i) for mode in ('plain','profiled') for r in (1,2,3) for f in FRAMES for i in range(30)}
    if set(samples)!=expected:raise ValueError('Incomplete sample matrix')
    expected_ops={(r,f,i,node['index']) for r in (1,2,3) for f in FRAMES for i in range(30) for node in model['nodes']}
    if set(operators)!=expected_ops:raise ValueError('Incomplete operator matrix')
    if set(blocks)!={(mode,r) for mode in ('plain','profiled') for r in (1,2,3)}:raise ValueError('Incomplete blocks')
    if set(goldens)!=set(FRAMES):raise ValueError('Missing golden activations')
    if len({b['arena_address'] for b in blocks.values()})!=1:raise ValueError('Arena moved')
    if len({b['arena_used'] for b in blocks.values()})!=1:raise ValueError('Arena allocation changed')
    done=[r for r in rows if r['event']=='done']
    if len(done)!=1 or done[0]['samples']!=540 or done[0]['operator_records']!=2970 or not done[0]['all_activations_exact']:
        raise ValueError('Run not completed')
    block_done=[r for r in rows if r['event']=='block_done']
    if Counter((r['mode'],r['round']) for r in block_done)!=Counter(blocks.keys()):raise ValueError('Missing completed block')
    total_invoke=total_nodes=total_esp=0
    for (mode,r,f,i),sample in samples.items():
        if mode=='plain':
            if sample['operator_sum_us'] or sample['esp_nn_us']:raise ValueError('Plain instrumentation enabled')
            continue
        selected=[operators[(r,f,i,node['index'])] for node in model['nodes']]
        for node,op in zip(model['nodes'],selected):
            if op['op']!=node['op']:raise ValueError('Operator tag mismatch')
            if (op['conv_calls'],op['depthwise_calls'])!=(int(node['op']=='CONV_2D'),int(node['op']=='DEPTHWISE_CONV_2D')):
                raise ValueError('Wrong kernel attribution')
            if not 0<=op['esp_nn_us']<=op['elapsed_us']:raise ValueError('Kernel outside operator time')
        nodes=sum(op['elapsed_us'] for op in selected);esp=sum(op['esp_nn_us'] for op in selected)
        if nodes!=sample['operator_sum_us'] or esp!=sample['esp_nn_us']:raise ValueError('Timing totals differ')
        if not 0<=esp<=nodes<=sample['invoke_us']:raise ValueError('Overlapping timing budget')
        total_invoke+=sample['invoke_us'];total_nodes+=nodes;total_esp+=esp
    rounds={}
    for mode in ('plain','profiled'):
        rounds[mode]=[dict(round=r,invoke_us=metrics([s['invoke_us'] for (m,rr,f,i),s in samples.items() if m==mode and rr==r])) for r in (1,2,3)]
    plain=median(v['invoke_us']['p50'] for v in rounds['plain'])
    profiled=median(v['invoke_us']['p50'] for v in rounds['profiled'])
    nodes=[]
    for node in model['nodes']:
        selected=[v for key,v in operators.items() if key[-1]==node['index']]
        elapsed=sum(v['elapsed_us'] for v in selected);esp=sum(v['esp_nn_us'] for v in selected)
        nodes.append(dict(index=node['index'],op=node['op'],output_name=node['outputs'][0]['name'],
                          output_shape=node['outputs'][0]['shape'],output_bytes=node['outputs'][0]['bytes'],macs=node['macs'],
                          elapsed_us=metrics([v['elapsed_us'] for v in selected]),
                          esp_nn_us=metrics([v['esp_nn_us'] for v in selected]),
                          share_of_invoke_pct=elapsed/total_invoke*100,
                          esp_nn_share_of_operator_pct=esp/elapsed*100 if elapsed else 0,
                          per_frame_p50_us={str(f):median(v['elapsed_us'] for key,v in operators.items() if key[-1]==node['index'] and key[1]==f) for f in FRAMES}))
    return dict(measured_invocations=540,profiled_invocations=270,operator_records=len(operators),
                arena_used=next(iter(blocks.values()))['arena_used'],arena_capacity=next(iter(blocks.values()))['arena_capacity'],
                plain_median_of_p50_us=plain,profiled_median_of_p50_us=profiled,
                instrumentation_difference_pct=(profiled/plain-1)*100,
                operator_share_of_invoke_pct=total_nodes/total_invoke*100,
                esp_nn_share_of_invoke_pct=total_esp/total_invoke*100,
                outside_operator_share_pct=(total_invoke-total_nodes)/total_invoke*100,
                rounds=rounds,nodes=nodes),goldens

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
    import tensorflow as tf
    path=ROOT/'experiments/esp32_representation_benchmark/artifacts/int8-prefix.tflite'
    if hashlib.sha256(path.read_bytes()).hexdigest()!=model['model_sha256']:raise ValueError('Model changed')
    runtime=tf.lite.Interpreter(model_content=path.read_bytes(),num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    runtime.allocate_tensors();inp=runtime.get_input_details()[0];out=runtime.get_output_details()[0]
    data=np.load(ROOT/'experiments/esp32_representation_benchmark/artifacts/inputs.npz')
    differences={}
    for frame,values in zip(data['frame_ids'],data['frames']):
        values=np.rint(values.astype(np.float64)/inp['quantization'][0]+inp['quantization'][1]).clip(-128,127).astype(np.int8)
        row=goldens[int(frame)]
        if values.tobytes()!=bytes.fromhex(row['input_hex']):raise ValueError('Input quantization differs')
        runtime.set_tensor(inp['index'],values.reshape(inp['shape']));runtime.invoke()
        pc=runtime.get_tensor(out['index']).ravel().astype(np.int16)
        device=np.frombuffer(bytes.fromhex(row['activation_hex']),dtype=np.int8).astype(np.int16)
        delta=device-pc;values,counts=np.unique(delta,return_counts=True)
        differences[str(int(frame))]=dict(elements=len(delta),different=int(np.count_nonzero(delta)),
            max_abs=int(np.abs(delta).max()),mean_abs=float(np.abs(delta).mean()),
            delta_histogram={str(int(v)):int(c) for v,c in zip(values,counts)})
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
    result.update(model_sha256=model['model_sha256'],pc_input_exact=True,
                  pc_activation_exact=all(v['different']==0 for v in differences.values()),
                  pc_activation_differences=differences,legacy_device_comparison=legacy,
                  all_630_warmup_and_measured_activations_match_device_golden=True,
                  original_flash_and_boot_verified=True,board=completion['board'],mac=hardware['mac'])
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--legacy-archive',type=Path,help='optional prior ESP32 HTTP archive for full canonical activation comparison')
    a=p.parse_args()
    a.output.write_text(json.dumps(audit(a.run,a.legacy_archive),indent=2)+'\n')
