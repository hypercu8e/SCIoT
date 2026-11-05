"""Audit physical-device logs against server archives and an independent suffix replay."""
import argparse
from collections import Counter, defaultdict, deque
import hashlib
import json
from pathlib import Path
import struct
import zlib
import numpy as np


def fnv(data):
    h = 2166136261
    for b in data:
        h = ((h ^ b)*16777619) & 0xffffffff
    return h


def percentiles(values):
    return {f'p{n}': float(np.percentile(values, n)) for n in (50, 95, 99)} if values else {}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    run = a.run
    completion = json.loads((run/'completion.json').read_text())
    assert completion['measurements_complete'] and not completion['restore_failures']
    campaign = [json.loads(s) for s in (run/'campaign.jsonl').read_text().splitlines()]
    assert not any(r['event'] in ('campaign_error', 'restore_failed') for r in campaign)
    stages = {r['stage']: r for r in campaign if r['event']=='stage_completed'}
    assert set(stages)=={'single_A','single_B','A_plus_simulated','two_boards_1000','reboot_isolation','two_boards_one_hour'}
    import tensorflow as tf
    artifacts = Path('experiments/esp32_representation_benchmark/artifacts')
    manifest = json.loads((artifacts/'manifest.json').read_text())
    binary = (artifacts/'int8-suffix.tflite').read_bytes()
    assert hashlib.sha256(binary).hexdigest()==manifest['models']['int8']['suffix']['sha256']
    runtime = tf.lite.Interpreter(model_content=binary, num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    runtime.allocate_tensors()
    inp = runtime.get_input_details()[0]
    out = runtime.get_output_details()[0]
    matches = defaultdict(deque)
    archived = 0
    with (run/'server/inference.bin').open('rb') as f:
        while True:
            sizes = f.read(8)
            if not sizes:
                break
            assert len(sizes)==8
            nb,nr = struct.unpack('<II', sizes)
            assert (nb,nr)==(4640,1760)
            body,reply = f.read(nb),f.read(nr)
            assert len(body)==nb and len(reply)==nr
            h = struct.unpack('<8I',body[:32])
            rh = struct.unpack('<8I',reply[:32])
            assert h[:3]==(0x31424353,1,1) and h[5:7]==(0,4608)
            assert zlib.crc32(body[32:])==h[7]
            assert rh[:5]==(0x31524353,1,h[3],h[4],432)
            runtime.set_tensor(inp['index'],np.frombuffer(body[32:],dtype=np.int8).reshape(inp['shape']))
            runtime.invoke()
            scores=(runtime.get_tensor(out['index']).astype(np.float32)-out['quantization'][1])*out['quantization'][0]
            assert scores.astype('<f4').tobytes()==reply[32:], 'Suffix replay mismatch'
            key=(h[3],h[4],fnv(body[32:]),fnv(reply))
            matches[key].append(hashlib.sha256(body[32:]).hexdigest())
            archived += 1
            if archived%10000==0:
                print(json.dumps(dict(event='archive_audit_progress',verified=archived)),flush=True)
    terminals = {}
    server_rows = []
    for s in (run/'server/server.jsonl').read_text().splitlines():
        r=json.loads(s);server_rows.append(r)
        if r['event']=='terminal':
            key=(r['client_id'],r['session_id'],r['request_id'])
            assert key not in terminals, 'Duplicate terminal completion'
            terminals[key]=r
    result = dict(archived_requests=archived, suffix_replay_exact=True, boards={}, stages={},
                  scope='Two physical ESP32-S3-EYE, frozen INT8 block_2_add, raw HTTP v2; archive I/O included. No annotated accuracy evaluation.')
    embedded=defaultdict(set)
    board_rows={}
    for name in 'AB':
        hardware=json.loads((run/name/'hardware.json').read_text())
        assert hardware['restored'] and hardware['restored_digest_verified_before_boot']
        assert hashlib.sha256((run/name/'original-flash.bin').read_bytes()).hexdigest()==hardware['backup_sha256']
        assert 'sciot_esp32_client' in (run/name/'restored-boot.log').read_text(errors='replace'), 'Original application boot not confirmed'
        rows=[json.loads(s) for s in (run/name/'events.jsonl').read_text().splitlines()]
        board_rows[name]=rows
        counts=Counter(r['row']['event'] for r in rows)
        assert counts['error']==0 and counts['rejected']==0
        cid='eye-'+hardware['mac'].replace(':','')
        correlation=None;seen=set();matched=0
        for entry in rows:
            row=entry['row'];event=row['event']
            if event=='correlation':
                correlation=row
            if event=='sample':
                assert correlation and correlation['client_id']==cid
                assert (correlation['frame'],correlation['iteration'])==(row['frame'],row['iteration'])
                identity=(cid,correlation['session_id'],correlation['request_id'])
                assert identity not in seen and terminals[identity]['status']==200
                seen.add(identity)
                key=(row['frame'],row['iteration'],row['activation_fnv32'],row['response_fnv32'])
                assert matches[key], 'Device hashes not matched to archived request and response'
                digest=matches[key].popleft()
                if row['source']=='embedded':
                    embedded[row['frame']].add(digest)
                matched+=1;correlation=None
        assert matched==counts['sample']==counts['correlation']
        memories=[r['row'] for r in rows if r['row']['event']=='memory']
        result['boards'][name]=dict(client_id=cid, samples=matched, events=dict(counts),
            installed_sha256=hardware['installed_sha256'],restored=True,backup_sha256=hardware['backup_sha256'],
            internal_min_free=min(r['internal_min_free'] for r in memories),
            psram_min_free=min(r['psram_min_free'] for r in memories))
    assert len({r['installed_sha256'] for r in result['boards'].values()})==1
    assert len(embedded)==3 and all(len(v)==1 for v in embedded.values()), 'Embedded activations differ across boards or phases'
    result['embedded_activation_exact_across_boards_and_phases']=True
    result['device_archive_link']='FNV32 for activation and complete reply; CRC32 verified for requests; suffix scores replayed byte for byte. FNV32 is not a cryptographic equality proof.'
    for stage,event in stages.items():
        lo,hi=event['monotonic']-event['elapsed'],event['monotonic']
        stats={}
        for name,rows in board_rows.items():
            selected=[e for e in rows if lo<=e['host_monotonic']<=hi]
            samples=[e for e in selected if e['row']['event']=='sample']
            cameras=[e for e in samples if e['row']['source']=='camera']
            times=[e['host_monotonic'] for e in cameras]
            memory=[e['row'] for e in selected if e['row']['event']=='memory']
            stats[name]=dict(embedded=len(samples)-len(cameras),camera=len(cameras),
                camera_cycle_ms=percentiles([e['row']['observed_cycle_us']/1000 for e in cameras]),
                camera_network_ms=percentiles([e['row']['request_response_us']/1000 for e in cameras]),
                max_camera_gap_s=max(np.diff(times),default=0),
                rssi_dbm=percentiles([e['row']['rssi_dbm'] for e in cameras]),
                memory_first=memory[0] if memory else None,memory_last=memory[-1] if memory else None)
            if stage=='two_boards_one_hour':
                done=[e['row'] for e in selected if e['row']['event']=='done']
                assert len(done)==1 and done[0]['elapsed_us']>=3600000000
                assert done[0]['camera_attempted']==done[0]['camera_completed']==len(cameras)
                stats[name]['duration_s']=done[0]['elapsed_us']/1e6
                stats[name]['camera_fps']=len(cameras)/stats[name]['duration_s']
            if stage=='two_boards_1000':
                assert len(cameras)==1000, 'Missing successful camera requests'
        successful=[r for r in terminals.values() if r['status']==200 and lo<=r['monotonic']<=hi]
        stage_queues={}
        for name in 'AB':
            cid=result['boards'][name]['client_id']
            stage_queues[name]=percentiles([r['queue_us']/1000 for r in successful if r['client_id']==cid])
        result['stages'][stage]=dict(duration_s=event['elapsed'],boards=stats,server_queue_ms=stage_queues)
    reset=next(r for r in campaign if r['event']=='reset_A_while_B_runs')
    resumed=next(r for r in campaign if r['event']=='A_restarted')
    b_samples=[e['host_monotonic'] for e in board_rows['B'] if e['row']['event']=='sample' and
               reset['monotonic']<=e['host_monotonic']<=resumed['monotonic']]
    assert b_samples, 'B did not complete requests during A restart'
    result['B_requests_during_A_restart']=len(b_samples)
    resources=[r for r in server_rows if r['event']=='resources']
    result['server']=dict(terminal_statuses=dict(Counter(str(r['status']) for r in terminals.values())),
        max_sampled_queue=max(r['queue_depth'] for r in resources),rss_max_bytes=max(r['rss_bytes'] for r in resources),
        archive_io_included=True)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(event='audit_complete',samples={n:r['samples'] for n,r in result['boards'].items()},archived=archived)),flush=True)


if __name__=='__main__':
    main()
