"""Strict audit of the local-only diagnostic, distinct from HTTP validation."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
from analyze import summarize, choose

def verify(run):
    completion=json.loads((run/'completion.json').read_text())
    if not completion['measurements_complete'] or completion['restore_failures']: raise ValueError('Incomplete run or restoration')
    raw=(run/'A/serial.log').read_bytes()
    if b'task_wdt:' in raw: raise ValueError('Watchdog warning invalidates run')
    for line in raw.splitlines():
        if b'"event":' in line:
            try: json.loads(line)
            except ValueError: raise ValueError('Corrupted event in serial log')
    entries=[json.loads(l)['row'] for l in (run/'A/events.jsonl').read_text().splitlines()]
    if any(r['event'] in ('error','rejected','serial_failure') for r in entries): raise ValueError('Device/recorder failure')
    exhaustive=[r for r in entries if r['event']=='exhaustive_validation']
    if len(exhaustive)!=1 or exhaustive[0]['colors']!=65536 or exhaustive[0]['mismatches']!=0: raise ValueError('Exhaustive validation missing')
    paired=[r for r in entries if r['event']=='paired_validation']
    if len(paired)!=100 or not all(r['exact'] for r in paired): raise ValueError('Frame validation failed')
    rows=[r for r in entries if r['event']=='sample']
    if len(rows)!=13*260: raise ValueError('Incomplete samples')
    if any(r['request_response_us'] or r['request_body_bytes'] or r['response_body_bytes'] for r in rows): raise ValueError('HTTP bytes/times in local run')
    if (run/'server/inference.bin').stat().st_size: raise ValueError('Unexpected server inference')
    metadata=[r for r in entries if r['event']=='measurement_transport']
    if len(metadata)!=len(rows) or any(r['transport']!='local_no_http' for r in metadata): raise ValueError('Missing transport metadata')
    data=json.loads((run/'A/hardware.json').read_text())
    if not data['restored'] or not data['restored_digest_verified_before_boot']: raise ValueError('Restore unverified')
    if hashlib.sha256((run/'A/original-flash.bin').read_bytes()).hexdigest()!=data['backup_sha256']: raise ValueError('Backup digest differs')
    if 'sciot_esp32_client' not in (run/'A/restored-boot.log').read_text(errors='replace'): raise ValueError('Original boot not confirmed')
    if 'sciot_esp32_client' not in (run/'B/unchanged-boot.log').read_text(errors='replace'): raise ValueError('Unmodified B boot not confirmed')
    manifest=json.loads((run/'experiment-sha256.json').read_text())
    recorded=manifest['experiments/esp32_input_camera_benchmark/idf/.pio/build/espnn/firmware.bin']
    if hashlib.sha256((run/'firmware.bin').read_bytes()).hexdigest()!=recorded: raise ValueError('Firmware snapshot differs')
    stats=summarize(run)
    names=['reference_hold','lut_hold','reference_early','lut_early']
    expected={f'single_r{r}_{name}' for r in (1,2,3) for name in names}|{'gray_exploratory'}
    if set(stats)!=expected: raise ValueError('Unexpected/missing stages')
    aggregate={}
    for name in names:
        values=[stats[f'single_r{r}_{name}']['A'] for r in (1,2,3)]
        aggregate[name]=dict(fps=median(v['fps'] for v in values),
            metrics_ms={field:{p:median(v['metrics_ms'][field][p] for v in values) for p in ('p50','p95','p99')} for field in values[0]['metrics_ms']},
            memory_stable=all(v['memory_stable'] for v in values),
            fps_range=[min(v['fps'] for v in values),max(v['fps'] for v in values)])
    return dict(scope='One ESP32, local prefix/packing only; no HTTP, suffix or prediction-quality evaluation.',
        camera_frames=2600,embedded_samples=780,paired_validation_frames=100,all_rgb565_colors_exact=True,
        watchdog_warnings=0,corrupt_events=0,server_inferences=0,original_A_restored=True,B_not_flashed=True,
        firmware_sha256=recorded,audit_tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),original_B_boot_confirmed=True,local_candidate=choose(stats),aggregate=aggregate,stages=stats)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.write_text(json.dumps(verify(a.run),indent=2)+'\n')
