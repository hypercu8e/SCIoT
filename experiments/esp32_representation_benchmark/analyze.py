"""Validate device/server captures, summarize latency and final-score fidelity."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('CUDA_VISIBLE_DEVICES','-1')
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL','3')
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'activation_compression'))
from check_int8 import prepare_input, dequantize
from compare_lossy import output_stats
from prepare_esp32_int8 import interpreter, invoke
from protocol import RESPONSE, RESPONSE_MAGIC, parse_request


def fnv32(data):
    value=2166136261
    for b in data:
        value=((value^b)*16777619)&0xffffffff
    return value


def describe(values):
    a=np.asarray(values,dtype=np.float64)
    return {'count':len(a),'min':float(a.min()),'p50':float(np.median(a)),
            'p95':float(np.percentile(a,95)),'max':float(a.max())}


def records(path):
    out=[]
    for l in path.read_text(errors='replace').splitlines():
        if l.startswith('{"event":'):
            out.append(json.loads(l))
    return out


def camera_input(image):
    p=np.frombuffer(image,dtype='>u2').astype(np.uint16)
    red=((p>>11)&31).astype(np.float32)/np.float32(31)
    green=((p>>5)&63).astype(np.float32)/np.float32(63)
    blue=(p&31).astype(np.float32)/np.float32(31)
    return (red*np.float32(.299)+green*np.float32(.587)+blue*np.float32(.114)).reshape(1,96,96,1)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    args=p.parse_args()
    run=args.run
    rows=records(run/'device.log')
    manifest=json.loads((HERE/'artifacts/manifest.json').read_text())
    boots=[r for r in rows if r['event']=='boot']
    if len(boots)!=1 or boots[0]['experiment_sha256']!=manifest['experiment_sha256']:
        raise ValueError('Missing/duplicate/wrong firmware boot')
    samples=[r for r in rows if r['event']=='sample']
    errors=[r for r in rows if r['event']=='error']
    if errors or not any(r['event']=='done' for r in rows):
        raise ValueError(f'Incomplete or failed run: {errors}')
    key=lambda r:(r['mode'],r['frame'],r['iteration'])
    if len({key(r) for r in samples})!=len(samples):
        raise ValueError('Duplicate samples')
    expected={(m,f,i) for m in ('float32','int8') for f in manifest['frames'] for i in range(6)}
    actual={key(r) for r in samples if r['source']=='embedded'}
    if actual!=expected:
        raise ValueError('Incomplete fixed-image comparison')
    server_rows=[json.loads(l) for l in (run/'server/server.jsonl').read_text().splitlines()]
    server_by_key={key(r):r for r in server_rows}
    boundaries={}
    predictions={}
    matched=[]
    for row in samples:
        s=server_by_key[key(row)]
        base=run/'server'/s['request']
        body=Path(str(base)+'.request.bin').read_bytes()
        response=Path(str(base)+'.response.bin').read_bytes()
        req=parse_request(body)
        header=RESPONSE.unpack_from(response)
        if (header[:2]!=(RESPONSE_MAGIC,1) or header[2:4]!=(row['frame'],row['iteration'])
                or len(response)!=1760 or row['response_fnv32']!=fnv32(response)
                or row['activation_fnv32']!=fnv32(req['activation'])
                or row['request_body_bytes']!=len(body)):
            raise ValueError('Device/server byte mismatch')
        pred=np.frombuffer(response[32:],dtype='<f4').reshape(1,12,12,3).copy()
        if not np.isfinite(pred).all():
            raise ValueError('Nonfinite final scores')
        boundaries.setdefault((row['mode'],row['frame']),[]).append(req['activation'])
        predictions[key(row)]=pred
        matched.append((row,req,pred))
    stability=[]
    for (mode,frame),values in boundaries.items():
        if frame>=1000:
            continue
        dtype='<f4' if mode=='float32' else 'i1'
        first=np.frombuffer(values[0],dtype=dtype).astype(np.float64)
        max_error=max(float(np.abs(np.frombuffer(v,dtype=dtype).astype(np.float64)-first).max()) for v in values)
        stability.append({'mode':mode,'frame':frame,'repetitions':len(values),
                          'exact_bytes_equal':all(v==values[0] for v in values),
                          'maximum_difference_vs_first':max_error})
    runtimes={m:interpreter((HERE/f'artifacts/{m}-full.tflite').read_bytes()) for m in ('float32','int8')}
    with np.load(HERE/'artifacts/inputs.npz',allow_pickle=False) as data:
        frames={int(i):x[None].copy() for i,x in zip(data['frame_ids'],data['frames'])}
    # Quality evaluation runs only AFTER the network measurement session.
    quality=[]
    reference_cache={}
    for row,req,pred in matched:
        if row['source']=='embedded' and row['iteration']!=0:
            continue
        values=frames[row['frame']] if row['source']=='embedded' else camera_input(req['image'])
        m=row['mode'];r=runtimes[m]
        cache_key=(m,row['frame'])
        if cache_key not in reference_cache:
            inp,_=prepare_input(values,r.get_input_details()[0])
            reference_cache[cache_key]=dequantize(invoke(r,inp),r.get_output_details()[0])
        ref=reference_cache[cache_key]
        quality.append({'mode':m,'frame':row['frame'],'source':row['source'],
                        'distributed_vs_desktop_same_representation':output_stats(ref,pred,[.5])})
    pairs=[]
    for frame in manifest['frames']:
        f=predictions[('float32',frame,0)];i=predictions[('int8',frame,0)]
        pairs.append({'frame':frame,'int8_vs_float32_final_scores':output_stats(f,i,[.5])})
    summary={'scope':'One physical ESP32-S3-EYE and PC HTTP suffix server over Wi-Fi; candidate FOMO, fixed graph cut',
             'boot':boots[0],'allocation':[r for r in rows if r['event']=='allocated'],
             'stability':stability,'quality_vs_desktop':quality,'fixed_image_final_comparison':pairs,
             'camera_samples':sum(r['source']=='camera' for r in samples),
             'sample_count':len(samples),'timing':{},
             'quality_limit':'Final grid-cell scores/labels at threshold 0.5, not annotated detection accuracy or a verified object decoder',
             'camera_limit':'Alternating fresh camera frames; identical inputs apply to embedded pairs only',
             'runtime_limit':'Pinned reference Micro kernels, ESP-NN disabled, arenas in PSRAM; not a best-possible ESP32 performance claim',
             'transport_limit':'Experimental one-request HTTP protocol, not the original SCIoT endpoint sequence; app body bytes exclude TCP/IP overhead',
             'throughput_limit':'Serial logging, warmups and diagnostics separate samples; inverse median latency is not measured sustained throughput'}
    for source in ('embedded','camera'):
        summary['timing'][source]={}
        for mode in ('float32','int8'):
            subset=[r for r in samples if r['source']==source and r['mode']==mode]
            if not subset:
                continue
            summary['timing'][source][mode]={field:describe([r[field] for r in subset]) for field in (
                'acquisition_us','preprocessing_us','input_prepare_us','invoke_us','packing_us',
                'request_response_us','phase_sum_us','observed_cycle_us','server_decode_us',
                'server_invoke_us','server_post_us','request_body_bytes','image_bytes','activation_bytes','rssi_dbm')}
        modes=summary['timing'][source]
        if 'float32' in modes and 'int8' in modes:
            f=modes['float32']['observed_cycle_us']['p50'];i=modes['int8']['observed_cycle_us']['p50']
            modes['float32_over_int8_latency_ratio']=f/i
            modes['int8_latency_reduction_percent']=100*(1-i/f)
    summary['capture_validation_passed']=True
    (run/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    lines=['# Float32 contro INT8 su ESP32-S3-EYE — 27 ottobre 2026','',
           'Una scheda, stesso taglio `block_2_add`, server HTTP sperimentale sul PC.',
           'Tre immagini incorporate × sei ripetizioni per rappresentazione; poi frame camera nuovi e alternati.','',
           '| Sorgente | Versione | Campioni | Prefisso p50, ms | HTTP completo p50, ms | Ciclo osservato p50, ms | Ciclo p95, ms | Corpo richiesta, byte |',
           '|---|---|---:|---:|---:|---:|---:|---:|']
    for source in ('embedded','camera'):
        for mode in ('float32','int8'):
            t=summary['timing'][source].get(mode)
            if t:
                lines.append(f'| {source} | {mode} | {t["invoke_us"]["count"]} | {t["invoke_us"]["p50"]/1000:.3f} | {t["request_response_us"]["p50"]/1000:.3f} | {t["observed_cycle_us"]["p50"]/1000:.3f} | {t["observed_cycle_us"]["p95"]/1000:.3f} | {t["request_body_bytes"]["p50"]:.0f} |')
    lines+=['','Il ciclo camera va dall\'inizio di `esp_camera_fb_get` alla ricezione completa della risposta.',
            'La camera non è inclusa nei campioni embedded. Il ciclo osservato include anche i controlli hash;',
            '`phase_sum_us` permette di leggere la somma delle sole fasi, esclusi tali controlli.',
            'Inizializzazione, connessione Wi-Fi, warmup e stampa seriale sono esclusi dai timer per campione.','',
            '## Memoria e ripetibilità','']
    for a in summary['allocation']:
        lines.append(f'- Arena effettiva {a["mode"]}: {a["arena_used_bytes"]:,} byte, capacità riservata 1 MiB.')
    lines+=['','I due interpreti restano residenti contemporaneamente: l\'arena individuale non è il picco RAM di un\'applicazione con un solo modello.',
            f'Confronto diretto dei byte ricevuti per i sei gruppi fissi: {sum(r["exact_bytes_equal"] for r in stability)}/6 gruppi identici.',
            f'Ingressi modificati da Invoke: {sum(r["input_changed_by_invoke"] for r in samples)}/{len(samples)}; l\'ingresso è ripristinato prima di ogni esecuzione.','',
            '## Qualità e limiti','',summary['quality_limit']+'.',summary['camera_limit']+'.',
            summary['runtime_limit']+'.',summary['transport_limit']+'.',summary['throughput_limit']+'.','',
            'Metriche complete per frame, scarti dei punteggi e celle perse/introdotte: [summary.json](summary.json).',
            'Input HTTP e risposte binarie originali: `server/`. Log seriale: `device.log`.']
    (run/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'samples':len(samples),'camera_samples':summary['camera_samples'],
                      'stable_groups':sum(r['exact_bytes_equal'] for r in stability),
                      'latency_ratios':{s:summary['timing'][s].get('float32_over_int8_latency_ratio') for s in ('embedded','camera')}}))


if __name__=='__main__':
    main()
