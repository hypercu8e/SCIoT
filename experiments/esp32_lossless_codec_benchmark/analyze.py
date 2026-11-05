"""Audit a complete, restored physical run before emitting any conclusions."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from protocol import *
from serial_recovery import read_serial
HERE=Path(__file__).resolve().parent

def rows(path):
    result=[]
    for s in path.read_text(errors='replace').splitlines():
        try:r=json.loads(s)
        except ValueError:continue
        if isinstance(r,dict):result.append(r)
    return result

def require(ok,message):
    if not ok:raise ValueError(message)

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args();run=a.run
    meta=json.loads((run/'hardware.json').read_text());stage=meta['stage'];manifest=json.loads((HERE/'artifacts/manifest.json').read_text())
    require(meta.get('capture_complete') and meta['backup_verified_before_flash'] and meta['restored'] and meta['restored_digest_verified_before_boot'],'Incomplete capture or unverified backup/restore')
    proof=json.loads((run/'build-verification.json').read_text())
    require(meta['firmware_sha256']==proof['firmware_sha256'] and proof['experiment_sha256']==manifest['experiment_sha256'],'Measured build differs from verified build')
    require(hashlib.sha256((run/'original-flash.bin').read_bytes()).hexdigest()==meta['backup_sha256'],'Backup digest')
    require((run/'restored-boot.log').stat().st_size>0,'Missing restored boot log')
    require(stage in ('full','video','bandwidth','lossless-video'),'Not a complete comparison stage')
    configs=list(range(4 if stage in ('bandwidth','lossless-video') else 6));video_count=146*len(configs)*6;camera_count=360 if stage=='full' else 0
    serial,serial_recovery=read_serial(run);logs=rows(run/'server/server.jsonl')
    require(not any(r.get('event') in ('error','transport_error') for r in serial),'Device/transport error')
    boot=next(r for r in serial if r.get('event')=='boot');probe=next(r for r in serial if r.get('event')=='kernel_check')
    require(boot['experiment_sha256']==manifest['experiment_sha256'],'Wrong experiment')
    require(probe['model_sha256']==manifest['models']['int8']['prefix']['sha256'] and probe['conv']==6 and probe['depthwise']==3,'Wrong model/kernels')
    done=[r for r in serial if r.get('event')=='done'];require(len(done)==1,'Missing/duplicate completion')
    require(done[0]['measured_requests']==video_count+camera_count and done[0]['diagnostic_requests']==camera_count,'Wrong completion count')
    measured=[r for r in serial if r.get('event')=='sample'];starts=[r for r in serial if r.get('event')=='sequence_start'];throughput=[r for r in serial if r.get('event')=='throughput']
    require(len(measured)==video_count+camera_count and len(logs)==video_count+2*camera_count,'Incomplete samples')
    for source,rounds in [(0,6)]+([(1,2)] if camera_count else []):
        for round_id in range(rounds):
            found=[r['config'] for r in starts if r['source']==source and r['round']==round_id]
            require(found==configs[::1 if round_id%2==0 else -1],'Config order/count')
    expected_sequences=6*len(configs)+(12 if camera_count else 0)
    require(len(starts)==len(throughput)==expected_sequences,'Incomplete sequences')
    sessions={r['session']:r for r in starts};require(len(sessions)==len(starts),'Session collision')
    samples={(r['session'],r['seq']):r for r in measured};require(len(samples)==len(measured),'Duplicate samples')
    scale,zero=manifest['models']['int8']['prefix']['output']['scales'][0],manifest['models']['int8']['prefix']['output']['zero_points'][0]
    decoder=Decoder(scale,zero);entries={};diagnostics={};summaries=[]
    for log in logs:
        base=run/'server'/log['name'];body=Path(str(base)+'.request.bin').read_bytes();response=Path(str(base)+'.response.bin').read_bytes();r=decoder.decode(body)
        h=REPLY.unpack_from(response);require(len(response)==1776 and h[:7]==(REPLY_MAGIC,VERSION,r['device'],r['session'],r['config'],r['seq'],r['frame']),'Response identity/size')
        require(h[10]==r['state_crc'] and h[11]==crc(r['activation']),'Response CRC')
        key=r['session'],r['seq'];entry=dict(log=log,decoded=r,output=response[48:])
        if r['source']==2:
            require(key not in diagnostics,'Duplicate diagnostic');diagnostics[key]=entry;continue
        require(key in samples and key not in entries,'Unmatched/duplicate measured packet');entries[key]=entry;s=samples[key]
        for field in ('frame','source','config','original_crc','state_crc','input_crc','activation_crc'):
            require(s[field]==log[field],f'Log mismatch {field}')
        require(s['wire_bytes']==r['length'] and s['kind']==r['kind'],'Payload log mismatch')
        require(r['frame']==r['seq']+(1000 if r['source']==1 else 0),'Frame order')
        session=sessions[r['session']];require(session['source']==r['source'] and session['config']==r['config'],'Session metadata')
        row=dict(s,round=session['round'],mode=NAMES[r['config']],payload_bytes=r['length'],http_bytes=log['body_bytes']+log['response_body_bytes']+log['request_http_header_bytes']+log['response_http_header_bytes'])
        summaries.append(row)
    require(len(diagnostics)==camera_count,'Missing camera originals')
    inputs=np.load(HERE/'artifacts/video-inputs.npy',allow_pickle=False)
    inspec=manifest['models']['int8']['prefix']['input']
    expected_input_crc=[crc(np.clip(np.rint(x.astype(np.float64)/inspec['scales'][0]+inspec['zero_points'][0]),-128,127).astype(np.int8).tobytes()) for x in inputs]
    raw_by_frame={};lossy_by_frame={}
    for key,e in entries.items():
        r=e['decoded']
        if r['source']==0 and r['config']==0:
            require(r['input_crc']==expected_input_crc[r['frame']],'Input differs from canonical video')
            fingerprint=(r['input_crc'],r['activation'],e['output'])
            if r['frame'] in raw_by_frame:require(raw_by_frame[r['frame']]==fingerprint,'Raw video changed across rounds')
            raw_by_frame[r['frame']]=fingerprint
    require(len(raw_by_frame)==146,'Missing raw video frames')
    for key,e in entries.items():
        r=e['decoded'];c=r['config']
        if r['source']==0:
            ref=raw_by_frame[r['frame']];require(r['input_crc']==ref[0] and r['original_crc']==crc(ref[1]),'Different video input/activations')
        else:
            refentry=diagnostics[key];require(refentry['decoded']['original_crc']==r['original_crc'] and refentry['decoded']['input_crc']==r['input_crc'],'Camera diagnostic mismatch');ref=(r['input_crc'],refentry['decoded']['activation'],refentry['output'])
        if c<4:require(r['activation']==ref[1] and e['output']==ref[2],'Lossless fidelity failure')
        elif r['source']==0:
            f=(f32_bytes(r['state']),r['activation'],e['output']);k=r['frame']
            if k in lossy_by_frame:require(lossy_by_frame[k]==f,'Packing/zlib reconstruction differs')
            lossy_by_frame[k]=f
        e['changed_scores']=int(np.count_nonzero(np.frombuffer(e['output'],'<f4')!=np.frombuffer(ref[2],'<f4')))
    for s in summaries:s['changed_scores']=entries[s['session'],s['seq']]['changed_scores']
    groups=[]
    for source in (0,1):
        for round_id in range(6 if source==0 else 2):
            for c in configs:
                rr=[r for r in summaries if r['source']==source and r['round']==round_id and r['config']==c]
                if not rr:continue
                group=dict(source='video' if source==0 else 'camera',round=round_id,mode=NAMES[c],frames=len(rr),payload_mean=float(np.mean([r['payload_bytes'] for r in rr])),http_mean=float(np.mean([r['http_bytes'] for r in rr])),cycle_p50_ms=float(np.median([r['cycle_us'] for r in rr]))/1000,cycle_p95_ms=float(np.percentile([r['cycle_us'] for r in rr],95))/1000,changed_scores=sum(r['changed_scores'] for r in rr))
                t=next(t for t in throughput if t['session']==rr[0]['session']);group['fps']=len(rr)*1e6/t['elapsed_us']
                group['encode_p50_ms']=float(np.median([r['quantize_reconstruct_us']+r['compression_us'] for r in rr]))/1000
                group['packing_p50_ms']=float(np.median([r['packing_us'] for r in rr]))/1000
                group['network_p50_ms']=float(np.median([r['network_us'] for r in rr]))/1000
                group['server_decode_p50_ms']=float(np.median([r['server_decode_us'] for r in rr]))/1000
                groups.append(group)
    acceptance={}
    for c in (2,3):
        if c not in configs:continue
        pairs=[]
        for pair in range(3):
            values={m:[r['cycle_us'] for r in summaries if r['source']==0 and r['config']==m and r['round']//2==pair] for m in (0,c)}
            median_ratio=float(np.median(values[c])/np.median(values[0]));p95_ratio=float(np.percentile(values[c],95)/np.percentile(values[0],95))
            pairs.append(dict(pair=pair,median_ratio=median_ratio,p95_ratio=p95_ratio,passes=median_ratio<=.95 and p95_ratio<=1.05))
        acceptance[NAMES[c]]=dict(pairs=pairs,passes=all(x['passes'] for x in pairs))
    decoder_backends={log.get('rice_decoder_backend','python') for log in logs}
    require(len(decoder_backends)==1,'Mixed decoder backends')
    decoder_backend=next(iter(decoder_backends))
    backend_proof=None
    if (run/'backend-proof.json').exists():
        backend_proof=json.loads((run/'backend-proof.json').read_text())
        require(backend_proof['backend']==decoder_backend,'Backend provenance mismatch')
        for name,digest in backend_proof['source_sha256'].items():
            require(hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest,'Backend source changed')
    bandwidth=None
    if stage=='bandwidth':
        pacing=[r for r in rows(run/'proxy.jsonl') if r.get('event')=='paced']
        require(len(pacing)==len(logs),'Missing proxy pacing measurements')
        rates={r['kbps'] for r in pacing}
        require(len(rates)==1 and next(iter(rates)) in (128,512),'Wrong proxy rate')
        for paced,log in zip(pacing,logs):
            require(paced['bytes']==log['body_bytes'],'Proxy/body correspondence')
            require(paced['elapsed_s']>0 and paced['effective_kbps']<=paced['kbps']*1.05,'Pacing exceeded requested rate')
        bandwidth=dict(target_kbps=next(iter(rates)),effective_kbps_p50=float(np.median([r['effective_kbps'] for r in pacing])),effective_kbps_min=min(r['effective_kbps'] for r in pacing),requests=len(pacing))
    result=dict(serial_recovery=serial_recovery,decoder_backend=decoder_backend,backend_proof=backend_proof,bandwidth=bandwidth,stage=stage,measured=len(measured),diagnostics=len(diagnostics),lossless_exact=True,packing_exact_on_video=True if 4 in configs else None,restored_verified=True,groups=groups,acceptance=acceptance,memory=[r for r in serial if r.get('event')=='memory'])
    (run/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    with (run/'frames.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
    text='# Codec INT8 sulla ESP32\n\n'+f"{len(measured)} richieste misurate, {len(diagnostics)} diagnostiche; stato originale ripristinato e verificato. Percorsi lossless esatti.\n\n"
    if serial_recovery:text+=f"Recupero seriale dichiarato: {serial_recovery['recovered_records']} prefisso identificativo ricostruito dai pacchetti originali; tutti i tempi conservati dalla riga USB, nessun campione temporale stimato. Log originale invariato e manifest di recupero esportato.\n\n"
    text+=f"Decoder Rice sul server: {decoder_backend}. L'audit ricostruisce tutti i pacchetti con Python indipendente.\n\n"
    if stage=='bandwidth':text+=f"Proxy applicativo: target {bandwidth['target_kbps']} kbit/s, rate effettivo mediano {bandwidth['effective_kbps_p50']:.2f} kbit/s. Non simula contesa o perdita Wi-Fi.\n\n"
    text+='|Ingresso|Giro|Metodo|Payload B|HTTP B|Ciclo p50/p95 ms|FPS|\n|---|---:|---|---:|---:|---:|---:|\n'
    text+=''.join(f"|{g['source']}|{g['round']}|{g['mode']}|{g['payload_mean']:.1f}|{g['http_mean']:.1f}|{g['cycle_p50_ms']:.2f}/{g['cycle_p95_ms']:.2f}|{g['fps']:.2f}|\n" for g in groups)
    text+='\nCriterio operativo: mediana almeno 5% inferiore al raw e p95 non oltre +5%, in tutte e tre le coppie video.\n\n'
    text+=''.join(f"- {name}: {'soddisfatto' if value['passes'] else 'non soddisfatto'}.\n" for name,value in acceptance.items())
    text+='\nUna scheda, un video e questa rete. Byte HTTP applicativi: esclusi TCP/IP, ACK e ritrasmissioni. I tempi server sono già nel ciclo; minime heap cumulative e buffer comuni non misurano firmware separati. Le configurazioni D+DZ restano con perdita e non sono approvate per l’applicazione.\n'
    (run/'report.md').write_text(text);print(json.dumps(dict(measured=len(measured),acceptance=acceptance),indent=2))
if __name__=='__main__':main()
