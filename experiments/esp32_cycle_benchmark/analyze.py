"""Audit the cycle test (variants 0-3, ABBA) and evaluate the criteria in README.md."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

PHASES=('0','1','2','3','3','2','1','0')
EMBEDDED=60
CAMERA=500
MAX_LOST=10          # at most 2% of camera frames lost to transient HTTP errors per phase
LUT_CHECKED=8*9216   # every 16-bit pixel value through the baseline call shape
MIN_GAIN_US=5000     # a lever counts as faster if it saves >= 5 ms in each round
PARTS=('acquisition_us','preprocessing_us','input_prepare_us','invoke_us','packing_us',
       'open_us','write_us','wait_headers_us','read_us','request_response_us','observed_cycle_us')
FATAL_TEXT=(b'task_wdt:',b'Guru Meditation Error',b'Brownout detector',b'abort() was called')

def percentile(values,p):
    xs=sorted(values);x=(len(xs)-1)*p/100;lo=int(x);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(x-lo)

def summarize_phase(index,variant,rows,terminals):
    by=lambda e:[r for r in rows if r['event']==e]
    info=by('variant')
    if len(info)!=1 or info[0]['variant']!=int(variant):raise ValueError(f'phase {index}: wrong variant')
    info=info[0]
    if info['lut']!=bool(int(variant)&1) or info['keep_alive']!=bool(int(variant)&2):raise ValueError(f'phase {index}: wrong flags')
    samples=by('sample');embedded=[s for s in samples if s['source']=='embedded'];camera=[s for s in samples if s['source']=='camera']
    done=by('done');errors=by('error');rejected=by('rejected');registrations=[r['success'] for r in by('registration')]
    statuses=Counter(t['status'] for t in terminals)
    result=dict(phase=index,variant=int(variant),lut_build_us=info['lut_build_us'],lut_checked=info['lut_checked'],
        lut_mismatches=info['lut_mismatches'],lut_fnv32=info['lut_sha_fnv32'],
        embedded_completed=len(embedded),camera_completed=len(camera),done=done[0] if len(done)==1 else None,
        errors=[e.get('reason') for e in errors],rejected=len(rejected),registrations=registrations,
        wifi_disconnections=len(by('wifi_disconnected')),server_statuses=dict(statuses),
        reconnects=max([s['reconnects'] for s in samples],default=0),
        rssi_p50=percentile([s['rssi_dbm'] for s in camera],50) if camera else None,
        camera={k:dict(p50=percentile([s[k] for s in camera],50),p95=percentile([s[k] for s in camera],95)) for k in PARTS} if camera else None,
        embedded_activation={f"{s['frame']}":s['activation_fnv32'] for s in embedded},
        embedded_response={f"{s['frame']}":s['response_fnv32'] for s in embedded})
    if any(len({s['activation_fnv32'] for s in embedded if s['frame']==f})!=1 for f in {s['frame'] for s in embedded}):
        raise ValueError(f'phase {index}: embedded activations differ between repeats')
    ok=(len(embedded)==EMBEDDED and len(done)==1 and done[0]['camera_attempted']==CAMERA
        and done[0]['camera_completed']==len(camera)>=CAMERA-MAX_LOST and len(errors)<=MAX_LOST
        and all(e.get('reason')=='http_response' for e in errors) and not rejected
        and info['lut_checked']==LUT_CHECKED and info['lut_mismatches']==0
        and set(statuses)<={200,408,410} and statuses[200]==len(samples))
    result['functional_ok']=ok
    return result

def summarize(rows,terminals,outcomes):
    starts=[min(r['host_monotonic'] for r in rows if r['phase']==i) for i in range(1,len(PHASES)+1) if any(r['phase']==i for r in rows)]
    if len(starts)!=len(PHASES):raise ValueError('phase missing')
    phases=[]
    for index,variant in enumerate(PHASES,1):
        start=starts[index-1];end=starts[index] if index<len(PHASES) else float('inf')
        result=summarize_phase(index,variant,[r['row'] for r in rows if r['phase']==index],
                               [t for t in terminals if start<=t['monotonic']<end])
        result['runner_outcome']=outcomes[index-1]
        if not outcomes[index-1]['ok']:result['functional_ok']=False
        phases.append(result)
    if any(t['monotonic']<starts[0] for t in terminals):raise ValueError('Server requests outside phases')
    correct=(len({p['lut_fnv32'] for p in phases})==1 and len({json.dumps(p['embedded_activation'],sort_keys=True) for p in phases})==1
             and len({json.dumps(p['embedded_response'],sort_keys=True) for p in phases})==1)
    functional=all(p['functional_ok'] for p in phases)
    rounds=[{p['variant']:p for p in phases[:4]},{p['variant']:p for p in phases[4:]}]
    levers={}
    for v,name in ((1,'lut'),(2,'keep_alive'),(3,'both')):
        deltas={k:[r[v]['camera'][k]['p50']-r[0]['camera'][k]['p50'] if r[v]['camera'] and r[0]['camera'] else None for r in rounds] for k in PARTS}
        cycle=deltas['observed_cycle_us']
        faster=None not in cycle and all(d<=-MIN_GAIN_US for d in cycle)
        levers[name]=dict(p50_delta_us=deltas,cycle_delta_mean_us=sum(cycle)/2 if None not in cycle else None,
                          verdict=('invalid' if not correct else 'environment_problem' if not functional else 'faster' if faster else 'not_confirmed'))
    return dict(phases=phases,outputs_identical=correct,all_phases_functional=functional,levers=levers,
        cycle_p50_us={f"{p['phase']}:{p['variant']}":p['camera']['observed_cycle_us']['p50'] if p['camera'] else None for p in phases})

def audit(run):
    completion=json.loads((run/'completion.json').read_text())
    if completion['restore_error'] or not completion['original_boot_confirmed']:raise ValueError('Recovery incomplete')
    hardware=json.loads((run/'board/hardware.json').read_text())
    if not hardware['restored'] or not hardware['restored_digest_verified_before_boot']:raise ValueError('Flash restoration unverified')
    if hashlib.sha256((run/'board/original-flash.bin').read_bytes()).hexdigest()!=hardware['backup_sha256']:raise ValueError('Backup changed')
    if b'sciot_esp32_client' not in (run/'board/restored-boot.log').read_bytes():raise ValueError('Original boot unconfirmed')
    raw=(run/'board/serial.log').read_bytes()
    panics=[v.decode() for v in FATAL_TEXT if v in raw]
    rows=[json.loads(s) for s in (run/'board/events.jsonl').read_text().splitlines()]
    terminals=[r for r in (json.loads(s) for s in (run/'server/server.jsonl').read_text().splitlines()) if r['event']=='terminal']
    if len(completion['outcomes'])!=len(PHASES):raise ValueError('Not all phases attempted')
    result=summarize(rows,terminals,completion['outcomes'])
    if panics:
        result['panic_text']=panics
        for lever in result['levers'].values():lever['verdict']='invalid'
    result.update(run_error=completion['error'],board=completion['board'],mac=hardware['mac'],original_flash_and_boot_verified=True)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.write_text(json.dumps(audit(a.run),indent=2)+'\n')
