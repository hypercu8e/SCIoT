"""Summarize server JSONL metrics by device, including queue and resource usage."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import numpy as np


def analyze(path):
    counts=defaultdict(Counter); timings=defaultdict(lambda:defaultdict(list)); resources=[]
    for line in path.open():
        row=json.loads(line);cid=row.get('client_id','server');event=row['event']
        counts[cid][event]+=1
        if event in ('terminal','rejected','registration_rejected'):
            counts[cid][f"status_{row['status']}"]+=1
        if event=='terminal' and row['status']==200:
            for name in ('queue_us','worker_us','elapsed_us'):
                timings[cid][name].append(row[name])
        if event=='resources':resources.append(row)
    return {'clients':{cid:{'counts':dict(values),'timings':{name:{f'p{q}':float(np.percentile(data,q)) for q in (50,95,99)}
                       for name,data in timings[cid].items()}} for cid,values in counts.items()},
            'resource_samples':len(resources),
            'rss_bytes':{'min':min(r['rss_bytes'] for r in resources if r['rss_bytes'] is not None),
                         'max':max(r['rss_bytes'] for r in resources if r['rss_bytes'] is not None),
                         'last':resources[-1]['rss_bytes']} if resources and any(r['rss_bytes'] is not None for r in resources) else {},
            'max_active_workers':max((r.get('active_workers', int(bool(r.get('running')))) for r in resources),default=0),
            'cpu_cores_mean':float(np.mean([r['cpu_cores'] for r in resources if 'cpu_cores' in r])) if any('cpu_cores' in r for r in resources) else None,
            'max_observed_queue':max((r['queue_depth'] for r in resources),default=0),
            'scope':'PC observations; not ESP32 hardware validation'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('metrics',type=Path);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();result=analyze(args.metrics)
    with args.output.open('x') as out:json.dump(result,out,indent=2);out.write('\n')
    print(json.dumps(result))
