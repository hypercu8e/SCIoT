"""Validate every sample and exact raw/compressed parity; summarize physical runs."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
from protocol import parse_request,RESPONSE,RESPONSE_MAGIC,VERSION

HERE=Path(__file__).resolve().parent
sys.path.append(str(HERE.parent/'esp32_representation_benchmark'))
from fomo_quality import decode,match,totals
MODES=('raw','zlib')


def sha(data):return hashlib.sha256(data).hexdigest()
def fnv32(data):
    value=2166136261
    for byte in data:value=((value^byte)*16777619)&0xffffffff
    return value
def describe(values):
    a=np.asarray(values,dtype=np.float64)
    return dict(count=len(a),min=float(a.min()),p50=float(np.median(a)),p95=float(np.percentile(a,95)),max=float(a.max()))
def records(path):
    return [json.loads(line) for line in path.read_text(errors='replace').splitlines() if line.startswith('{"event":')]


def analyze(run):
    events=records(run/'device.log');manifest=json.loads((HERE/'artifacts/manifest.json').read_text())
    quality=json.loads((HERE/'artifacts/quality-inputs.json').read_text())
    boots=[r for r in events if r['event']=='boot']
    if len(boots)!=1 or not boots[0]['esp_nn_enabled'] or boots[0]['experiment_sha256']!=manifest['experiment_sha256']:
        raise ValueError('Missing/wrong firmware boot')
    if any(r['event']=='error' for r in events) or sum(r['event']=='done' for r in events)!=1:
        raise ValueError('Failed/incomplete session')
    kernels=[r for r in events if r['event']=='kernel_check']
    if {r['mode'] for r in kernels}!=set(MODES) or any(r['esp32s3_conv_calls']!=6 or r['esp32s3_depthwise_calls']!=3 for r in kernels):
        raise ValueError('Wrong optimized kernel calls')
    allocations=[r for r in events if r['event']=='allocated']
    if len(allocations)!=1 or allocations[0]['model_sha256']!=manifest['models']['int8']['prefix']['sha256']:
        raise ValueError('Expected one interpreter with frozen prefix')
    quality_start=[r for r in events if r['event']=='quality_start']
    if len(quality_start)!=1 or quality_start[0]['input_sha256']!=quality['input_sha256']:raise ValueError('Wrong quality inputs')
    expected={(m,f,i) for m in MODES for f in manifest['frames'] for i in range(20)}
    expected|={(m,item['frame'],0) for m in MODES for item in quality['records']}
    for i in range(20):
        for pos in range(2):expected.add((MODES[(i+pos)%2],1000+2*i+pos,i))
    for round_ in range(2):
        for pos in range(2):
            for i in range(20):expected.add((MODES[(round_+pos)%2],2000+round_*40+pos*20+i,round_))
    samples=[r for r in events if r['event']=='sample'];key=lambda r:(r['mode'],r['frame'],r['iteration'])
    if len(samples)!=len(expected) or {key(r) for r in samples}!=expected:raise ValueError('Wrong sample set')
    server_rows=[json.loads(line) for line in (run/'server/server.jsonl').read_text().splitlines()]
    if len(server_rows)!=len(samples) or len({key(r) for r in server_rows})!=len(samples):raise ValueError('Server sample set mismatch')
    by_key={key(r):r for r in server_rows};predictions={};activation_groups={};network=[]
    for sample in samples:
        row=by_key[key(sample)];base=run/'server'/row['request']
        body=Path(str(base)+'.request.bin').read_bytes();reply=Path(str(base)+'.response.bin').read_bytes()
        req=parse_request(body);header=RESPONSE.unpack_from(reply)
        if req['mode']!=sample['mode'] or (req['frame'],req['iteration'])!=(sample['frame'],sample['iteration']):raise ValueError('Request identity')
        if header[:2]!=(RESPONSE_MAGIC,VERSION) or header[2:4]!=(sample['frame'],sample['iteration']) or header[4]!=432 or len(reply)!=1760:raise ValueError('Response identity')
        if fnv32(req['activation'])!=sample['activation_fnv32'] or fnv32(reply)!=sample['response_fnv32']:raise ValueError('Device/server mismatch')
        if sha(req['activation'])!=row['activation_sha256'] or sample['request_body_bytes']!=len(body) or sample['wire_bytes']!=req['wire_bytes']:raise ValueError('Capture/size mismatch')
        output=np.frombuffer(reply[32:],dtype='<f4').reshape(12,12,3)
        if not np.isfinite(output).all() or decode(output)!=row['fomo_detections']:raise ValueError('Invalid scores/postprocessing')
        predictions[key(sample)]=reply[32:]
        activation_groups.setdefault((sample['mode'],sample['frame']),[]).append(req['activation'])
        network.append(dict(mode=sample['mode'],frame=sample['frame'],wire_bytes=req['wire_bytes'],
            request_body_bytes=len(body),http_total_bytes=len(body)+len(reply)+row['request_http_header_bytes']+row['response_http_header_bytes']))
    for mode in MODES:
        for frame in manifest['frames']:
            values=activation_groups[(mode,frame)]
            if any(v!=values[0] for v in values):raise ValueError('Fixed activation instability')
    parity=[]
    for frame in manifest['frames']+[r['frame'] for r in quality['records']]:
        left=activation_groups[('raw',frame)];right=activation_groups[('zlib',frame)]
        if any(value!=left[0] for value in right):raise ValueError('Lossless tensor parity failed')
        iterations=range(20) if frame in manifest['frames'] else (0,)
        for iteration in iterations:
            if predictions[('raw',frame,iteration)]!=predictions[('zlib',frame,iteration)]:raise ValueError('Final score parity failed')
        parity.append(frame)
    phases=('compression_us','input_prepare_us','invoke_us','packing_us','request_response_us','observed_cycle_us','server_decode_us','server_invoke_us','server_post_us')
    timing={};traffic={}
    selectors={'embedded':lambda f:f<1000,'annotated':lambda f:f>=3000,'camera_alternating':lambda f:1000<=f<2000,'camera_continuous':lambda f:2000<=f<3000}
    for source,selected in selectors.items():
        timing[source]={};traffic[source]={}
        for mode in MODES:
            chosen=[s for s in samples if s['mode']==mode and selected(s['frame'])]
            timing[source][mode]={p:describe([s[p] for s in chosen]) for p in phases}
            timing[source][mode]['server_decompression_and_validation_us']=describe([by_key[key(s)]['decompression_and_validation_us'] for s in chosen])
            chosen_network=[r for r in network if r['mode']==mode and selected(r['frame'])]
            traffic[source][mode]={p:describe([r[p] for r in chosen_network]) for p in ('wire_bytes','request_body_bytes','http_total_bytes')}
            traffic[source][mode]['expanded_frames']=sum(r['wire_bytes']>4608 for r in chosen_network)
    throughput=[r for r in events if r['event']=='throughput']
    if len(throughput)!=4 or {(r['mode'],r['round']) for r in throughput}!={(m,i) for m in MODES for i in range(2)}:raise ValueError('Missing throughput batches')
    for row in throughput:row['frames_per_second']=row['frames']*1e6/row['elapsed_us']
    metrics=[]
    for item in quality['records']:
        scores=np.frombuffer(predictions[('raw',item['frame'],0)],dtype='<f4')
        metrics.append(match(decode(scores),item['boxes']))
    summary=dict(samples=len(samples),boot=boots[0],allocations=allocations,kernel_checks=kernels,
        codec_memory=[r for r in events if r['event']=='codec_allocated'],timing=timing,traffic=traffic,throughput=throughput,
        exact_parity_frames=len(parity),exact_parity_requests=288,quality=dict(images=len(metrics),class_agnostic=totals(metrics)),
        wifi_rssi_dbm=describe([s['rssi_dbm'] for s in samples]),
        fixed_output_sha256={f'{m}:{f}:{i}':sha(b) for (m,f,i),b in predictions.items() if f<1000 or f>=3000})
    (run/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ('samples','exact_parity_frames','quality','throughput')}))
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    analyze(p.parse_args().run)
