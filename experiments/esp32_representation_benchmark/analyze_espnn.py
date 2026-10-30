"""Validate the optimized hardware run, byte accounting and annotated detections."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from analyze import records,fnv32,describe
from protocol import parse_request,RESPONSE,RESPONSE_MAGIC
from fomo_quality import decode,match,totals
from check_int8 import prepare_input,dequantize
from prepare_esp32_int8 import interpreter,invoke

HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True)
    args=p.parse_args();run=args.run
    events=records(run/'device.log')
    manifest=json.loads((HERE/'artifacts/manifest.json').read_text())
    quality=json.loads((HERE/'artifacts/quality-inputs.json').read_text())
    boots=[r for r in events if r['event']=='boot']
    if len(boots)!=1 or not boots[0]['esp_nn_enabled'] or boots[0]['experiment_sha256']!=manifest['experiment_sha256']:
        raise ValueError('Wrong firmware or runtime')
    if any(r['event']=='error' for r in events) or len([r for r in events if r['event']=='done'])!=1:
        raise ValueError('Incomplete or failed run')
    kernel_checks=[r for r in events if r['event']=='kernel_check']
    if len(kernel_checks)!=2 or any(not r['esp32s3_conv_calls'] or not r['esp32s3_depthwise_calls'] for r in kernel_checks if r['mode']=='int8'):
        raise ValueError('Optimized kernel execution evidence missing')
    quality_events=[r for r in events if r['event']=='quality_start']
    if len(quality_events)!=1 or quality_events[0]['input_sha256']!=quality['input_sha256']:
        raise ValueError('Wrong annotated inputs')
    samples=[r for r in events if r['event']=='sample']
    key=lambda r:(r['mode'],r['frame'],r['iteration'])
    modes=('float32','int8')
    expected={(m,f,i) for m in modes for f in manifest['frames'] for i in range(20)}
    expected|={(m,3000+i,0) for m in modes for i in range(quality['count'])}
    # Alternating live frames, then four continuous batches in AB/BA order.
    for i in range(20):
        for pos in range(2):expected.add((modes[(i+pos)%2],1000+2*i+pos,i))
    for round_ in range(2):
        for pos in range(2):
            for i in range(20):expected.add((modes[(round_+pos)%2],2000+round_*40+pos*20+i,round_))
    if len(samples)!=len(expected) or {key(r) for r in samples}!=expected:
        raise ValueError('Unexpected or missing sample set')
    servers=[json.loads(l) for l in (run/'server/server.jsonl').read_text().splitlines()]
    if len(servers)!=len(samples) or len({key(s) for s in servers})!=len(servers):
        raise ValueError('Server capture set mismatch')
    server_by_key={key(s):s for s in servers}
    predictions={};boundaries={};network={m:[] for m in modes}
    for sample in samples:
        row=server_by_key[key(sample)]
        prefix=run/'server'/row['request']
        request=Path(str(prefix)+'.request.bin').read_bytes();response=Path(str(prefix)+'.response.bin').read_bytes()
        req=parse_request(request);reply=RESPONSE.unpack_from(response)
        if req['image'] or sample['image_bytes'] or row['image_bytes']:raise ValueError('Diagnostic image traffic')
        if reply[:2]!=(RESPONSE_MAGIC,1) or reply[2:4]!=(sample['frame'],sample['iteration']) or len(response)!=1760:
            raise ValueError('Invalid response identity/length')
        if sample['response_fnv32']!=fnv32(response) or sample['activation_fnv32']!=fnv32(req['activation']):
            raise ValueError('Firmware/capture mismatch')
        if len(request)!=sample['request_body_bytes'] or row['body_bytes']!=len(request):raise ValueError('Byte count mismatch')
        values=np.frombuffer(response[32:],dtype='<f4').reshape(12,12,3).copy()
        if not np.isfinite(values).all():raise ValueError('Nonfinite final scores')
        if row['fomo_detections']!=decode(values):raise ValueError('Postprocessing mismatch')
        predictions[key(sample)]=values
        boundaries.setdefault((sample['mode'],sample['frame']),[]).append(req['activation'])
        network[sample['mode']].append({'activation_bytes':len(req['activation']),
            'request_body_bytes':len(request),'response_body_bytes':len(response),
            'http_total_bytes':len(request)+len(response)+row['request_http_header_bytes']+row['response_http_header_bytes']})
    stability=[]
    for mode in modes:
        for frame in manifest['frames']:
            values=boundaries[(mode,frame)]
            stability.append({'mode':mode,'frame':frame,'exact_bytes_equal':all(v==values[0] for v in values),'repetitions':len(values)})
    if not all(s['exact_bytes_equal'] for s in stability):raise ValueError('Nonrepeatable fixed-input outputs')
    timing={}
    phases=('input_prepare_us','invoke_us','packing_us','request_response_us','observed_cycle_us','server_invoke_us','server_post_us')
    for source in ('embedded','camera_alternating'):
        timing[source]={}
        for mode in modes:
            rows=[s for s in samples if s['mode']==mode and
                  (s['source']=='embedded' if source=='embedded' else 1000<=s['frame']<2000)]
            timing[source][mode]={p:describe([s[p] for s in rows]) for p in phases}
    throughput=[r for r in events if r['event']=='throughput']
    if len(throughput)!=4:raise ValueError('Missing continuous batches')
    for row in throughput:row['frames_per_second']=row['frames']*1e6/row['elapsed_us']
    annotated=[]
    for item in quality['records']:
        row={'frame':item['frame'],'annotations':len(item['boxes'])}
        for mode in modes:
            detection=decode(predictions[(mode,item['frame'],0)])
            row[mode]=dict(match(detection,item['boxes']),detections=detection)
        f=set(row['float32']['matched_annotation_indices']);q=set(row['int8']['matched_annotation_indices'])
        row.update(lost_vs_float32=sorted(f-q),gained_vs_float32=sorted(q-f))
        annotated.append(row)
    quality_report={m:totals([r[m] for r in annotated]) for m in modes}
    quality_report.update(images=len(annotated),threshold=.5,
        matched_objects_lost_vs_float32=sum(len(r['lost_vs_float32']) for r in annotated),
        matched_objects_gained_vs_float32=sum(len(r['gained_vs_float32']) for r in annotated),
        metric='Class-agnostic, predicted center inside annotated box, maximum one-to-one matching',
        class_mapping_verified=False,frames=annotated)
    # Desktop references are evaluated after timing, on identical frozen inputs.
    input_frames=np.load(HERE/'artifacts/quality-inputs.npy',allow_pickle=False)
    fidelity={}
    for mode in modes:
        runtime=interpreter((HERE/f'artifacts/{mode}-full.tflite').read_bytes())
        errors=[];desktop_metrics=[]
        for i,item in enumerate(quality['records']):
            value,_=prepare_input(input_frames[i][None],runtime.get_input_details()[0])
            output=invoke(runtime,value)
            if mode=='int8':output=dequantize(output,runtime.get_output_details()[0])
            expected_output=output.reshape(12,12,3)
            errors.append(float(np.max(np.abs(expected_output-predictions[(mode,item['frame'],0)]))))
            desktop_metrics.append(match(decode(expected_output),item['boxes']))
        fidelity[mode]={'maximum_score_error_vs_desktop_full':max(errors),
                        'per_image_max_error':describe(errors),'desktop_class_agnostic_quality':totals(desktop_metrics)}
    network_report={m:{k:describe([r[k] for r in network[m]]) for k in network[m][0]} for m in modes}
    result={'boot':boots[0],'samples':len(samples),'timing':timing,'throughput':throughput,
            'network':network_report,'quality':quality_report,'stability':stability,
            'allocations':[e for e in events if e['event']=='allocated'],
            'kernel_evidence':kernel_checks,'desktop_fidelity':fidelity,
            'limitations':['One physical board, one Wi-Fi, fixed block_2_add cut, experimental HTTP endpoint',
              'Class-channel order unconfirmed: object matching ignores class',
              'Public test set relationship to exported H5 training set unverified',
              'Camera timing frames are different; identical inputs apply to embedded/annotated comparisons',
              'HTTP bytes include headers/body in both directions; TCP/IP, retransmissions and Wi-Fi airtime unmeasured',
              'Both model arenas resident in PSRAM; individual arena is not whole-application peak RAM',
              'Reply returns all 432 final scores for both modes; compact object replies not evaluated']}
    (run/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('samples','timing','throughput')}))
    print(json.dumps({m:quality_report[m] for m in modes}))

if __name__=='__main__':main()
