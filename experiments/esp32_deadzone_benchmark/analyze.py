"""Reject incomplete physical runs; audit packets, states, fidelity and timing."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from protocol import Decoder, NAMES, REPLY, REPLY_MAGIC, crc, dequantize, requantize

HERE = Path(__file__).resolve().parent


def read_rows(path):
    result = []
    for line in path.read_text(errors='replace').splitlines():
        try:
            row = json.loads(line)
            if isinstance(row, dict): result.append(row)
        except ValueError:
            pass
    return result


def percentile(values, p):
    return float(np.percentile(values, p))


def boxes(detections):
    return sorted(tuple(d[k] for k in ('channel','x','y','width','height')) for d in detections)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--video-only',action='store_true',help='Audit an explicitly selected, complete video-only hardware campaign')
    args = p.parse_args()
    run = args.run
    measured_count=3504 if args.video_only else 4224
    diagnostic_count=0 if args.video_only else 720
    sequence_count=24 if args.video_only else 48
    manifest = json.loads((HERE/'artifacts/manifest.json').read_text())
    model = manifest['models']['int8']
    scale, zero = model['prefix']['output']['scales'][0], model['prefix']['output']['zero_points'][0]
    serial = read_rows(run/'device.log')
    boot=next((r for r in serial if r.get('event')=='boot'),{})
    assert not any(r.get('event') == 'error' for r in serial), 'Device reported failure'
    assert any(r.get('event') == 'boot' and r.get('experiment_sha256') == manifest['experiment_sha256'] for r in serial), 'Wrong/missing boot'
    assert any(r.get('event') == 'kernel_check' and r['conv'] == 6 and r['depthwise'] == 3 and
               r['model_sha256'] == model['prefix']['sha256'] for r in serial), 'Wrong ESP-NN/model'
    done = [r for r in serial if r.get('event') == 'done']
    assert len(done) == 1 and done[0]['measured_requests'] == measured_count and done[0]['diagnostic_requests'] == diagnostic_count
    assert bool(done[0].get('video_only'))==args.video_only, 'Wrong run stage'
    measured = [r for r in serial if r.get('event') == 'sample']
    assert len(measured) == measured_count, 'Incomplete device samples'
    starts = [r for r in serial if r.get('event') == 'sequence_start']
    throughput = [r for r in serial if r.get('event') == 'throughput']
    assert len(starts) == len(throughput) == sequence_count, 'Missing sequences'
    sessions = {r['session']:r for r in starts}
    assert len(sessions) == sequence_count, 'Session collision'
    for source in ((0,) if args.video_only else (0,1)):
        for round_id in (0,1):
            ordered = [r['config'] for r in starts if r['source']==source and r['round']==round_id]
            assert ordered == list(range(12))[::1 if round_id==0 else -1], 'Wrong mode order'
    logs = read_rows(run/'server/server.jsonl')
    assert len(logs) == measured_count+diagnostic_count, 'Incomplete server samples'
    decoder = Decoder(scale, zero)
    records, original_video, original_camera = {}, {}, {}
    device_samples = {(r['session'],r['seq']):r for r in measured}
    assert len(device_samples)==measured_count
    for row in logs:
        base = run/'server'/row['name']
        body = Path(str(base)+'.request.bin').read_bytes()
        response = Path(str(base)+'.response.bin').read_bytes()
        decoded = decoder.decode(body)
        header = REPLY.unpack_from(response)
        assert len(response)==1776 and header[:7]==(REPLY_MAGIC,1,decoded['device'],decoded['session'],decoded['config'],decoded['seq'],decoded['frame'])
        assert header[10]==decoded['state_crc'] and header[11]==crc(decoded['activation'])
        key = decoded['session'],decoded['seq']
        entry = dict(row, decoded=decoded, output=np.frombuffer(response[48:],'<f4'))
        if row['source']==2:
            assert key not in original_camera, 'Duplicate diagnostic'
            original_camera[key]=entry
            continue
        assert key not in records, 'Duplicate measured request'
        records[key]=entry
        sample = device_samples[key]
        for name in ('frame','source','config','original_crc','state_crc','input_crc','activation_crc'):
            assert sample[name]==row[name], (name,key)
        assert sample['wire_bytes']==row['length']
        assert sample['kind']==row['kind']
        if row['source']==0 and row['config']==0:
            if row['frame'] in original_video:
                assert decoded['activation']==original_video[row['frame']]['decoded']['activation']
                assert np.array_equal(entry['output'],original_video[row['frame']]['output'])
            original_video[row['frame']]=entry
    assert len(original_video)==146 and len(original_camera)==diagnostic_count
    fingerprints={}
    for entry in records.values():
        row=entry['decoded']
        assert row['frame']==row['seq']+(1000 if row['source']==1 else 0), 'Frame order differs from frozen sequence'
        if row['source']==0:
            key=row['config'],row['frame']
            fingerprint=(row['input_crc'],row['original_crc'],row['state_crc'],row['activation'],entry['output'].tobytes())
            if key in fingerprints:assert fingerprints[key]==fingerprint, 'Video reconstruction/output not repeatable across rounds'
            fingerprints[key]=fingerprint
    input_frames=np.load(HERE/'artifacts/video-inputs.npy',allow_pickle=False)
    input_spec=model['prefix']['input']
    expected_inputs=np.clip(np.rint(input_frames.astype(np.float64)/input_spec['scales'][0]+input_spec['zero_points'][0]),-128,127).astype(np.int8)
    groups=defaultdict(list)
    for key,entry in records.items():
        row=entry['decoded'];sample=device_samples[key]
        original=original_video[row['frame']] if row['source']==0 else original_camera[key]
        raw=original['decoded']['activation']
        assert crc(raw)==row['original_crc']
        if row['source']==0:assert crc(expected_inputs[row['frame']].tobytes())==row['input_crc']
        else:assert original['input_crc']==row['input_crc']
        if row['config']<3:
            assert raw==row['activation'] and np.array_equal(entry['output'],original['output']), 'Lossless path changed data'
        target=dequantize(raw,scale,zero)
        state_error=row['state'].astype(np.float64)-target.astype(np.float64)
        effective=dequantize(row['activation'],scale,zero).astype(np.float64)-target.astype(np.float64)
        output_error=entry['output'].astype(np.float64)-original['output'].astype(np.float64)
        before=original['output'].reshape(12,12,3)[...,1:]
        after=entry['output'].reshape(12,12,3)[...,1:]
        before_labels=np.where(before.max(-1)>=.5,before.argmax(-1)+1,0)
        after_labels=np.where(after.max(-1)>=.5,after.argmax(-1)+1,0)
        indices=np.frombuffer(row['symbols'],np.int8)
        counts=np.bincount(indices.astype(np.int16)+128,minlength=256)
        probabilities=counts[counts>0]/len(indices)
        result=dict(sample,round=sessions[row['session']]['round'],mode=NAMES[row['config']],
            payload_bytes=row['length'],application_bytes=entry['body_bytes']+entry['response_body_bytes'],
            http_bytes=entry['body_bytes']+entry['response_body_bytes']+entry['request_http_header_bytes']+entry['response_http_header_bytes'],
            state_mae=float(np.abs(state_error).mean()),state_max=float(np.abs(state_error).max()),
            state_mse=float(np.mean(state_error**2)),effective_mae=float(np.abs(effective).mean()),
            effective_max=float(np.abs(effective).max()),output_mae=float(np.abs(output_error).mean()),
            output_max=float(np.abs(output_error).max()),changed_cells=int(np.count_nonzero(before_labels!=after_labels)),
            lost_cells=int(np.count_nonzero((before_labels!=0)&(after_labels==0))),
            introduced_cells=int(np.count_nonzero((before_labels==0)&(after_labels!=0))),
            reference_foreground_cells=int(np.count_nonzero(before_labels)),
            symbol_zero_fraction=float(np.mean(indices==0)),symbol_entropy_bpe=float(-np.sum(probabilities*np.log2(probabilities))),
            changed_class_cells=int(np.count_nonzero((before_labels!=0)&(after_labels!=0)&(before_labels!=after_labels))),
            reference_detections=len(original['fomo_detections']),reconstructed_detections=len(entry['fomo_detections']),
            detection_boxes_changed=int(boxes(original['fomo_detections'])!=boxes(entry['fomo_detections'])),
            diagnostic_http_bytes=0 if row['source']==0 else original['body_bytes']+original['response_body_bytes']+original['request_http_header_bytes']+original['response_http_header_bytes'])
        groups[(result['source'],result['round'],result['config'])].append(result)
    assert len(groups)==sequence_count
    summaries=[];all_frames=[]
    for (source,round_id,config),rows in sorted(groups.items()):
        assert len(rows)==(146 if source==0 else 30)
        assert sorted(r['seq'] for r in rows)==list(range(len(rows)))
        timing=next(r for r in throughput if r['session']==rows[0]['session'])
        assert timing['frames']==len(rows) and timing['elapsed_us']>=sum(r['cycle_us'] for r in rows)
        out=dict(source='video' if source==0 else 'camera',round=round_id,config=config,mode=NAMES[config],frames=len(rows),
            payload_bytes=sum(r['payload_bytes'] for r in rows),http_bytes=sum(r['http_bytes'] for r in rows),
            diagnostic_http_bytes=sum(r['diagnostic_http_bytes'] for r in rows),fps=len(rows)*1e6/timing['elapsed_us'],
            state_mae=float(np.mean([r['state_mae'] for r in rows])),state_rmse=float(np.sqrt(np.mean([r['state_mse'] for r in rows]))),
            state_max=max(r['state_max'] for r in rows),effective_mae=float(np.mean([r['effective_mae'] for r in rows])),
            effective_max=max(r['effective_max'] for r in rows),output_max=max(r['output_max'] for r in rows),
            output_mae=float(np.mean([r['output_mae'] for r in rows])),
            detection_boxes_changed_frames=sum(r['detection_boxes_changed'] for r in rows),
            changed_cells=sum(r['changed_cells'] for r in rows),lost_cells=sum(r['lost_cells'] for r in rows),
            reference_foreground_cells=sum(r['reference_foreground_cells'] for r in rows),
            mean_symbol_entropy_bpe=float(np.mean([r['symbol_entropy_bpe'] for r in rows])),
            pframe_zero_fraction=float(np.mean([r['symbol_zero_fraction'] for r in rows if r['kind']==1])) if any(r['kind']==1 for r in rows) else None,
            introduced_cells=sum(r['introduced_cells'] for r in rows),changed_class_cells=sum(r['changed_class_cells'] for r in rows),
            reference_detections=sum(r['reference_detections'] for r in rows),reconstructed_detections=sum(r['reconstructed_detections'] for r in rows))
        for field in ('cycle_us','quantize_reconstruct_us','compression_us','network_us','invoke_us','server_decode_us'):
            for percent in (50,95):out[f'{field}_p{percent}']=percentile([r[field] for r in rows],percent)
        summaries.append(out);all_frames+=rows
    result=dict(experiment=manifest['experiment_sha256'],verified=True,stage='video' if args.video_only else 'full',
                measured_requests=measured_count,diagnostic_requests=diagnostic_count,
                configurations=summaries,memory=[r for r in serial if r.get('event')=='memory'],
                health_checks=[r for r in serial if r.get('event')=='health'],
                camera_xclk_hz=boot.get('camera_xclk_hz'),
                wifi_disconnects=sum(r.get('event')=='wifi_disconnected' for r in serial),
                video_all_configurations_repeatable_across_rounds=True,
                device_log_sha256=hashlib.sha256((run/'device.log').read_bytes()).hexdigest())
    (run/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    with (run/'frames.csv').open('w') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(all_frames[0]));writer.writeheader();writer.writerows(all_frames)
    video=[r for r in summaries if r['source']=='video']
    by_config={c:[r for r in video if r['config']==c] for c in range(12)}
    average=lambda c,k:float(np.mean([r[k] for r in by_config[c]]))
    best=min(range(3,12),key=lambda c:average(c,'payload_bytes'))
    saving=100*(1-average(best,'payload_bytes')/average(0,'payload_bytes'))
    slower=all(r['cycle_us_p50']>next(a['cycle_us_p50'] for a in by_config[0] if a['round']==r['round'])
               for r in video if r['config']>=3)
    finding=(f'Nel video, {NAMES[best]} ha il payload minimo: {average(best,"payload_bytes")/146:.1f} B/frame, '
             f'{saving:.2f}% sotto INT8 raw. Cambia complessivamente '
             f'{sum(r["changed_cells"] for r in by_config[best])} celle nei due giri; '
             'non è una configurazione approvata per l’applicazione. ')
    if slower:finding+='Tutti i nuovi codec con quantizzazione hanno un ciclo mediano maggiore del raw in entrambi i giri. '
    finding+='Le modalità zlib senza perdita conservano esattamente attivazioni e punteggi.'
    scope=('**Campagna video completa sulla ESP32. La camera dal vivo non è validata da questo rapporto.**'
           if args.video_only else '**Campagna completa: video e camera sulla ESP32.**')
    lines=['# FOMO INT8: DPCM e dead-zone sulla ESP32','',scope,'',finding,'',
        f'{measured_count} richieste misurate e {diagnostic_count} diagnostiche, due giri in ordine invertito. '
        'Video: 146 ingressi identici, campionamento 5 fps e replay senza attese. '
        +('Camera: sequenze diverse; qualità confrontata con il raw sugli stessi frame tramite diagnostica fuori misura.' if not args.video_only else
          'I tentativi preliminari camera hanno avuto timeout HTTP, anche in modalità raw. Non sono inclusi nelle prestazioni del video.'),'',
        '| Input | Giro | Metodo | Payload B/frame | HTTP B/frame | Ciclo p50/p95 ms | FPS | Celle cambiate | Max errore punteggio |',
        '|---|---:|---|---:|---:|---:|---:|---:|---:|']
    for r in summaries:
        lines.append(f'| {r["source"]} | {r["round"]+1} | {r["mode"]} | {r["payload_bytes"]/r["frames"]:.1f} | {r["http_bytes"]/r["frames"]:.1f} | '
            f'{r["cycle_us_p50"]/1000:.2f}/{r["cycle_us_p95"]/1000:.2f} | {r["fps"]:.2f} | {r["changed_cells"]} | {r["output_max"]:.6f} |')
    lines+=['','## Interpretazione e limiti','',
        'Il ciclo include ingresso, inferenza ESP-NN, quantizzazione/ricostruzione locale, compressione, checksum, '
        'HTTP fino alla risposta completa e cleanup. I tempi del server sono già dentro HTTP. '
        'L’allocazione e il cambio livello del compressore sono fuori misura; il reset per frame è incluso. '
        'Le copie diagnostiche camera sono incluse nel throughput ma fuori dal timer del singolo frame. '
        'Stampe seriali e upload diagnostico avvengono dopo la sequenza. '
        'Il server salva i pacchetti prima della risposta: questo costo comune è dentro il tempo di rete.',
        '', 'Camera XCLK 20 MHz, contro i 16 MHz della baseline precedente; tutte le modalità della campagna '
        'usano la medesima configurazione. Non si attribuiscono al solo codec le differenze rispetto ai vecchi firmware. '
        'Il limite HTTP è 60 secondi, identico per tutti i metodi. Le sonde RSSI/canale sono fuori misura '
        'e disponibili nel JSON; non sono una registrazione continua della qualità radio.',
        '', 'HTTP include le intestazioni ricostruite e la risposta; esclude TCP/IP, ACK, ritrasmissioni e traffico diagnostico, '
        'che è riportato separatamente. Rinnovi ogni 30 frame, nessun fallback adattivo. '
        'Il codec usa miniz 3.0.2, non garantisce byte identici a zlib livello 6 del paper.',
        '', 'Le metriche di fedeltà confrontano lo stesso suffisso desktop sugli INT8 originali prodotti dalla scheda. '
        'Non sono accuratezza su annotazioni; le classi restano canali anonimi. '
        'Nessuna tolleranza applicativa è stata approvata. Il clipping P99 può lasciare errore anche a 8 bit: '
        'aumentare i bit non elimina le saturazioni degli estremi. Il riferimento DPCM sincronizzato '
        'evita la divergenza fra encoder e decoder, non garantisce predizioni identiche al raw. '
        'Il benchmark non prova altri video, reti, schede o client concorrenti.',
        '', 'La memoria libera minima è cumulativa dalla partenza e tutte le configurazioni condividono i buffer del benchmark; '
        'non è il picco di firmware separati. La riserva diagnostica e la tensor arena vanno distinte dal costo del codec.']
    (run/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'verified':True,'measured_requests':measured_count,'diagnostic_requests':diagnostic_count,'report':str(run/'report.md')}))


if __name__=='__main__':main()
