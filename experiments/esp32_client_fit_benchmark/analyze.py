"""Audit the client fit test (phases N/R/N/R) and evaluate the criteria in README.md."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

PHASES=('N','R','N','R')
RESERVE_BYTES=152*1024
EMBEDDED=60
CAMERA=1000
# Fixed before the measurement (README.md): headroom left with the block held,
# the same reserve used for the 161,323-byte limit.
MIN_FREE_FLOOR=32768
# Second test (README, 'Seconda prova'): Wi-Fi/lwIP in PSRAM, fixed before that measurement.
# At most 1% of camera frames lost to transient HTTP errors in any phase (phase 3 of the
# first run lost 3), and the reserve must not slow the camera cycle by more than 10%.
TOLERANT=dict(max_errors=10,allowed_error_statuses={408,410},max_cycle_ratio=1.10)
FATAL_TEXT=(b'task_wdt:',b'Guru Meditation Error',b'Brownout detector',b'abort() was called')

def percentile(values,p):
    xs=sorted(values);x=(len(xs)-1)*p/100;lo=int(x);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(x-lo)

def summarize_phase(index,mode,rows,terminals,tolerant=False):
    by=lambda e:[r for r in rows if r['event']==e]
    reserve=by('reserve')
    if len(reserve)!=1:raise ValueError(f'phase {index}: expected one reserve event')
    reserve=reserve[0]
    if reserve['mode']!=mode or reserve['held']!=(mode=='R') or reserve['requested']!=(RESERVE_BYTES if mode=='R' else 0):
        raise ValueError(f'phase {index}: wrong reserve state')
    samples=by('sample');embedded=[s for s in samples if s['source']=='embedded'];camera=[s for s in samples if s['source']=='camera']
    done=by('done');memory=by('memory');errors=by('error');rejected=by('rejected')
    registrations=by('registration');camera_init=by('camera_init');wifi=by('wifi_disconnected')
    held=[m for m in memory if m['reserve_held']!=(mode=='R')]
    if held:raise ValueError(f'phase {index}: memory sample with wrong reserve state')
    statuses=Counter(t['status'] for t in terminals)
    cycles=[s['observed_cycle_us'] for s in camera];network=[s['request_response_us'] for s in camera]
    result=dict(phase=index,mode=mode,reserve=reserve,
        embedded_completed=len(embedded),camera_completed=len(camera),
        done=done[0] if len(done)==1 else None,
        errors=errors,rejected=len(rejected),registrations=[r['success'] for r in registrations],
        camera_init_status=[c['status'] for c in camera_init],wifi_disconnections=len(wifi),
        internal_min_free=min(m['internal_min_free'] for m in memory) if memory else None,
        internal_largest_block_min=min(m['internal_largest_block'] for m in memory) if memory else None,
        internal_free_min_sampled=min(m['internal_free'] for m in memory) if memory else None,
        memory_samples=len(memory),
        server_statuses=dict(statuses),server_requests=sum(statuses.values()),
        camera_cycle_us=dict(p50=percentile(cycles,50),p95=percentile(cycles,95)) if cycles else None,
        camera_network_us=dict(p50=percentile(network,50),p95=percentile(network,95)) if network else None,
        invoke_us_p50=percentile([s['invoke_us'] for s in samples],50) if samples else None)
    ok=(len(embedded)==EMBEDDED and len(camera)==CAMERA and len(done)==1 and done[0]['camera_completed']==CAMERA
        and done[0]['camera_attempted']==CAMERA and not errors and not rejected and all(result['registrations'])
        and result['camera_init_status']==[0] and set(statuses)=={200} and result['server_requests']==EMBEDDED+CAMERA)
    if tolerant:
        failed=set(statuses)-{200}
        ok=(len(embedded)==EMBEDDED and len(done)==1 and done[0]['camera_attempted']==CAMERA
            and done[0]['camera_completed']==len(camera)>=CAMERA-TOLERANT['max_errors']
            and len(errors)<=TOLERANT['max_errors'] and all(e.get('reason')=='http_response' for e in errors)
            and not rejected and result['registrations'] and all(result['registrations'])
            and result['camera_init_status']==[0] and failed<=TOLERANT['allowed_error_statuses']
            and statuses[200]==EMBEDDED+len(camera))
    result['functional_ok']=ok
    if mode=='R':result['headroom_ok']=result['internal_min_free'] is not None and result['internal_min_free']>=MIN_FREE_FLOOR
    return result

def summarize(rows,terminals,outcomes,tolerant=False):
    """rows: events.jsonl records; terminals: server 'terminal' rows with monotonic time."""
    phases=[]
    # A phase owns the server records from its first device event to the first
    # event of the next phase (the reset), so late terminals are not lost.
    starts=[min(r['host_monotonic'] for r in rows if r['phase']==i) for i in range(1,len(PHASES)+1) if any(r['phase']==i for r in rows)]
    if len(starts)!=len(PHASES):raise ValueError('phase missing')
    for index,mode in enumerate(PHASES,1):
        selected=[r for r in rows if r['phase']==index]
        start=starts[index-1];end=starts[index] if index<len(PHASES) else float('inf')
        phase_terminals=[t for t in terminals if start<=t['monotonic']<end]
        result=summarize_phase(index,mode,[r['row'] for r in selected],phase_terminals,tolerant)
        result['runner_outcome']=outcomes[index-1]
        if not outcomes[index-1]['ok']:result['functional_ok']=False
        phases.append(result)
    if sum(p['server_requests'] for p in phases)!=len([t for t in terminals if t['monotonic']>=starts[0]]):raise ValueError('Server requests outside phases')
    if any(t['monotonic']<starts[0] for t in terminals):raise ValueError('Server requests outside phases')
    reserve=[p for p in phases if p['mode']=='R'];control=[p for p in phases if p['mode']=='N']
    fits=all(p['functional_ok'] and p['headroom_ok'] for p in reserve)
    controls_ok=all(p['functional_ok'] for p in control)
    cycle_ratio=None
    if tolerant:
        n=[p['camera_cycle_us']['p50'] for p in control if p['camera_cycle_us']]
        r=[p['camera_cycle_us']['p50'] for p in reserve if p['camera_cycle_us']]
        cycle_ratio=max(r)/(sum(n)/len(n)) if n and r else None
        fits=fits and cycle_ratio is not None and cycle_ratio<=TOLERANT['max_cycle_ratio']
    return dict(phases=phases,reserve_bytes=RESERVE_BYTES,min_free_floor=MIN_FREE_FLOOR,
        criteria='tolerant' if tolerant else 'strict',reserve_to_control_cycle_p50=cycle_ratio,
        controls_ok=controls_ok,reserve_phases_ok=fits,
        verdict='fits' if fits and controls_ok else ('environment_problem' if not controls_ok else 'does_not_fit'),
        internal_min_free={m:[p['internal_min_free'] for p in phases if p['mode']==m] for m in ('N','R')},
        internal_largest_block_min={m:[p['internal_largest_block_min'] for p in phases if p['mode']==m] for m in ('N','R')},
        camera_cycle_p50_us={m:[p['camera_cycle_us']['p50'] if p['camera_cycle_us'] else None for p in phases if p['mode']==m] for m in ('N','R')})

def audit(run,tolerant=False):
    completion=json.loads((run/'completion.json').read_text())
    if completion['restore_error'] or not completion['original_boot_confirmed']:raise ValueError('Recovery incomplete')
    hardware=json.loads((run/'board/hardware.json').read_text())
    if not hardware['restored'] or not hardware['restored_digest_verified_before_boot']:raise ValueError('Flash restoration unverified')
    if hashlib.sha256((run/'board/original-flash.bin').read_bytes()).hexdigest()!=hardware['backup_sha256']:raise ValueError('Backup changed')
    if b'sciot_esp32_client' not in (run/'board/restored-boot.log').read_bytes():raise ValueError('Original boot unconfirmed')
    raw=(run/'board/serial.log').read_bytes()
    panics=[v.decode() for v in FATAL_TEXT if v in raw]
    rows=[json.loads(s) for s in (run/'board/events.jsonl').read_text().splitlines()]
    server=[json.loads(s) for s in (run/'server/server.jsonl').read_text().splitlines()]
    terminals=[r for r in server if r['event']=='terminal']
    outcomes=completion['outcomes']
    if len(outcomes)!=len(PHASES):raise ValueError('Not all phases attempted')
    result=summarize(rows,terminals,outcomes,tolerant)
    if panics:result.update(verdict='invalid',panic_text=panics)
    result.update(run_error=completion['error'],board=completion['board'],env=completion.get('env','espnn'),mac=hardware['mac'],original_flash_and_boot_verified=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--criteria',choices=('strict','tolerant'),default='strict')
    a=p.parse_args();a.output.write_text(json.dumps(audit(a.run,a.criteria=='tolerant'),indent=2)+'\n')
