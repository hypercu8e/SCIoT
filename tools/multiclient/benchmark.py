"""Sequential CPU/HTTP campaign. Run from the repository root with PYTHONPATH=src."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time
import urllib.request
import zlib

CONFIGS = [(w, t) for w in (1, 2, 4, 8) for t in (1, 2, 4, 8) if w*t <= 8]



def environment():
    def read(path):
        try:return path.read_text().strip()
        except OSError:return None
    return {'power':{p.name:{k:read(p/k) for k in ('type','online','status','capacity')}
                     for p in Path('/sys/class/power_supply').glob('*')},
            'cpu':{p.parent.name:{k:read(p/k) for k in
                   ('scaling_governor','energy_performance_preference','scaling_cur_freq')}
                   for p in Path('/sys/devices/system/cpu').glob('cpu[0-9]*/cpufreq')},
            'temperature_millidegrees':{str(p):read(p) for p in Path('/sys/class/thermal').glob('thermal_zone*/temp')},
            'load_average':os.getloadavg()}


def check_power(snapshot, allow_battery=False):
    if not allow_battery and any(p.get('status')=='Discharging' for p in snapshot['power'].values()):
        raise RuntimeError('Campaign requires external power; battery is discharging. Connect the charger. Use --allow-battery only for explicitly battery-scoped trials.')


def check_profile(before, after):
    def profile(snapshot):
        return {cpu:{k:values.get(k) for k in ('scaling_governor','energy_performance_preference')}
                for cpu,values in snapshot['cpu'].items()}
    if profile(before)!=profile(after):
        raise RuntimeError('CPU energy profile changed during the campaign; restart under stable conditions')


def energy_scope(before, after):
    def key(snapshot):
        battery=any(p.get('status')=='Discharging' for p in snapshot['power'].values())
        profiles=sorted({(p.get('scaling_governor'),p.get('energy_performance_preference'))
                         for p in snapshot['cpu'].values()})
        return ('battery' if battery else 'ac')+':'+str(profiles)
    return key(before) if key(before)==key(after) else 'transition'


def engine_trial(args):
    import numpy as np
    from server.multiclient.engine import Suffix
    from server.multiclient.protocol import HEADER, REQUEST_MAGIC
    packets = []
    for value in (-128, 0, 127):
        data = np.full((1,24,24,8), value, dtype=np.int8).tobytes()
        packets.append(HEADER.pack(REQUEST_MAGIC,1,1,0,0,0,4608,zlib.crc32(data))+data)
    # Real frozen-frame activations, plus signed endpoint tensors.
    import tensorflow as tf
    prefix=tf.lite.Interpreter(model_path=str(args.artifacts/'int8-prefix.tflite'),num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    prefix.allocate_tensors()
    spec=prefix.get_input_details()[0];out=prefix.get_output_details()[0]
    with np.load(args.artifacts/'inputs.npz') as frozen:
        for frame in frozen['frames']:
            values=np.clip(np.rint(frame.astype(np.float64)/spec['quantization'][0]+spec['quantization'][1]),-128,127).astype(np.int8)
            prefix.set_tensor(spec['index'],values[None]);prefix.invoke()
            data=prefix.get_tensor(out['index']).tobytes()
            packets.append(HEADER.pack(REQUEST_MAGIC,1,1,0,0,0,4608,zlib.crc32(data))+data)
    reference = Suffix(args.artifacts)
    expected = [reference(body)[32:] for body in packets]
    pools = [ThreadPoolExecutor(max_workers=1) for _ in range(args.workers)]
    try:
        engines = [pool.submit(Suffix,args.artifacts,args.threads).result() for pool in pools]
        start = time.monotonic()+args.warmup
        end = start+args.duration
        def loop(engine):
            count = index = 0
            while time.monotonic()<end:
                before=time.monotonic()
                result=engine(packets[index%len(packets)])
                if result[32:] != expected[index%len(packets)]:
                    raise AssertionError('Numerical mismatch')
                count += before>=start
                index+=1
            return count
        cpu=time.process_time()
        counts=[f.result() for f in [p.submit(loop,e) for p,e in zip(pools,engines)]]
        elapsed=time.monotonic()-start
        return {'workers':args.workers,'threads':args.threads,'counts':counts,
                'throughput':sum(counts)/elapsed,'elapsed_s':elapsed,
                'cpu_cores':(time.process_time()-cpu)/(elapsed+args.warmup),'exact':True}
    finally:
        for pool in pools: pool.shutdown()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--artifacts',type=Path,default=Path('experiments/esp32_representation_benchmark/artifacts'))
    p.add_argument('--duration',type=float,default=30)
    p.add_argument('--warmup',type=float,default=5)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--clients',type=int,nargs='+',default=[1,2,8,32])
    p.add_argument('--allow-battery',action='store_true')
    p.add_argument('--allow-energy-changes',action='store_true')
    p.add_argument('--resume',action='store_true')
    p.add_argument('--engine',action='store_true')
    p.add_argument('--workers',type=int,default=1)
    p.add_argument('--threads',type=int,default=1)
    args=p.parse_args()
    if args.duration<=0 or args.warmup<0 or args.repeats<1 or min(args.clients)<1 or max(args.clients)>32 or min(args.workers,args.threads)<1:
        p.error('Invalid campaign limits')
    initial_environment=environment()
    check_power(initial_environment,args.allow_battery)
    args.output.mkdir(parents=True,exist_ok=args.resume)
    if args.engine:
        result=engine_trial(args)
        after_environment=environment()
        (args.output/'environment.json').write_text(json.dumps({'before':initial_environment,'after':after_environment},indent=2))
        check_power(after_environment,args.allow_battery)
        if not args.allow_energy_changes:check_profile(initial_environment,after_environment)
        (args.output/'summary.json').write_text(json.dumps(result,indent=2))
        return
    env=dict(os.environ, PYTHONPATH='src', CUDA_VISIBLE_DEVICES='-1', TF_CPP_MIN_LOG_LEVEL='3',
             TF_NUM_INTRAOP_THREADS='1', TF_NUM_INTEROP_THREADS='1', OMP_NUM_THREADS='1')
    meta={'environment':initial_environment,'arguments':vars(args),'platform':platform.platform(),'cpu_count':os.cpu_count(),
          'lscpu':subprocess.check_output(['lscpu'],text=True),
          'packages':subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True),
          'source_sha256':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [*Path('src/server/multiclient').glob('*.py'),*Path('tools/multiclient').glob('*.py')]},
          'model_manifest':json.loads((args.artifacts/'manifest.json').read_text())}
    manifest_name=f'resume-{time.time_ns()}.json' if args.resume else 'manifest.json'
    (args.output/manifest_name).write_text(json.dumps(meta,default=str,indent=2))
    rows=[json.loads(line) for line in (args.output/'results.jsonl').read_text().splitlines()] if args.resume and (args.output/'results.jsonl').exists() else []
    def child(command, log):
        check_power(environment(),args.allow_battery)
        if '--engine' in command:
            if args.allow_battery:command.append('--allow-battery')
            if args.allow_energy_changes:command.append('--allow-energy-changes')
        with log.open('w') as out:subprocess.run([sys.executable,*command],env=env,stdout=out,stderr=subprocess.STDOUT,check=True)
    def http_trial(w,t,n,rep,rate=0,tag='matrix'):
        name=f'{tag}-w{w}-t{t}-n{n}-r{rep}'
        if any((r['kind'],r['workers'],r['threads'],r['clients'],r['repeat'])==(tag,w,t,n,rep) for r in rows):
            return
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        before_environment=environment()
        check_power(before_environment,args.allow_battery)
        if not args.allow_energy_changes:check_profile(initial_environment,before_environment)
        base=args.output/name
        if base.exists():
            failed=args.output/'failed_trials'
            failed.mkdir(exist_ok=True)
            base.rename(failed/f'{name}-{time.time_ns()}')
            previous_log=args.output/(name+'.log')
            if previous_log.exists():previous_log.rename(failed/f'{name}-{time.time_ns()}.log')
        with (args.output/(name+'.log')).open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','server.multiclient.run','--host','127.0.0.1','--port',str(port),
                '--output',str(base/'server'),'--artifacts',str(args.artifacts),'--inference-workers',str(w),
                '--inference-threads',str(t)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+60
                while True:
                    if server.poll() is not None:raise RuntimeError(f'Server exited: {name}')
                    try:
                        urllib.request.urlopen(f'http://127.0.0.1:{port}/openapi.json',timeout=.5).close();break
                    except OSError:
                        if time.monotonic()>deadline:raise TimeoutError(name)
                        time.sleep(.1)
                child(['tools/multiclient/load.py','--url',f'http://127.0.0.1:{port}','--output',str(base/'client'),
                       '--artifacts',str(args.artifacts),'--clients',str(n),'--duration',str(args.duration),
                       '--warmup',str(args.warmup),'--rate',str(rate/n)],base/'load.log')
            finally:
                server.terminate()
                try:server.wait(timeout=30)
                except subprocess.TimeoutExpired:server.kill();server.wait();raise
        after_environment=environment()
        (base/'environment.json').write_text(json.dumps({'before':before_environment,'after':after_environment},indent=2))
        check_power(after_environment,args.allow_battery)
        if not args.allow_energy_changes:check_profile(initial_environment,after_environment)
        result=json.loads((base/'client/summary.json').read_text())
        begin=result['measurement_start_monotonic'];end=begin+args.duration
        events=[json.loads(line) for line in (base/'server/server.jsonl').open()]
        resources=[r for r in events if r['event']=='resources' and begin<=r['monotonic']<=end]
        timings=[r for r in events if r['event']=='terminal' and r.get('status')==200 and begin<=r['monotonic']<=end]
        row={'energy_scope':energy_scope(before_environment,after_environment),'kind':tag,'workers':w,'threads':t,'clients':n,'repeat':rep,'offered_rate':rate,'result':result,
             'resources':resources,'server_timings':{key:[r[key] for r in timings] for key in ('queue_us','worker_us','elapsed_us')}}
        if any(c['failed'] for c in result['clients']):raise AssertionError(f'Failed requests: {name}')
        rows.append(row)
        with (args.output/'results.jsonl').open('a') as out:out.write(json.dumps(row)+'\n')
        print(name, round(result['completed_per_second'],2),flush=True)
    for rep in range(args.repeats):
        configs=CONFIGS if rep%2==0 else CONFIGS[::-1]
        for w,t in configs:
            name=f'engine-w{w}-t{t}-r{rep}'
            if not (args.output/name/'summary.json').exists():
                child(['tools/multiclient/benchmark.py','--engine','--output',str(args.output/name),'--artifacts',str(args.artifacts),
                       '--workers',str(w),'--threads',str(t),'--duration',str(args.duration),'--warmup',str(args.warmup)],args.output/(name+'.log'))
            for n in (args.clients if rep%2==0 else args.clients[::-1]):http_trial(w,t,n,rep)
    import statistics
    original=json.loads((args.output/'manifest.json').read_text())['environment']
    selection_scope=energy_scope(original,original)
    def scope(row):
        if 'energy_scope' in row:return row['energy_scope']
        path=args.output/f"{row['kind']}-w{row['workers']}-t{row['threads']}-n{row['clients']}-r{row['repeat']}"/'environment.json'
        snap=json.loads(path.read_text())
        return energy_scope(snap['before'],snap['after'])
    capacity={}
    for w,t in CONFIGS:
        values=[r['result']['completed_per_second'] for r in rows if r['kind']=='matrix' and r['clients']==max(args.clients) and (r['workers'],r['threads'])==(w,t) and scope(r)==selection_scope]
        if values:capacity[w,t]=statistics.median(values)
    best=max(capacity,key=capacity.get)
    for rep in range(args.repeats):
        for ratio in (.5,.8,1.,1.2):
            for w,t in dict.fromkeys([(1,1),best]):
                http_trial(w,t,max(args.clients),rep,ratio*capacity[1,1],tag=f'rate-{ratio}')
    (args.output/'selection.json').write_text(json.dumps({'selection_energy_scope':selection_scope,'mixed_energy_authorized':args.allow_energy_changes,'best':best,'capacity':{str(k):v for k,v in capacity.items()}},indent=2))
    print('Campaign complete',flush=True)


if __name__=='__main__':main()
