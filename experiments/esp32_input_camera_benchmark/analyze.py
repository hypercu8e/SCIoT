"""Summarize completed stages; reject incomplete data when selecting a candidate."""
import json
from pathlib import Path
from statistics import median

def percentile(xs,p):
    xs=sorted(xs); x=(len(xs)-1)*p/100; lo=int(x);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(x-lo)

def summarize(run):
    run=Path(run)
    campaign=[json.loads(s) for s in (run/'campaign.jsonl').read_text().splitlines()]
    result={}
    for stage in (s for s in campaign if s['event']=='stage_completed'):
        lo,hi=stage['started'],stage['monotonic']; stats={}
        for board in stage['samples']:
            entries=[json.loads(s) for s in (run/board/'events.jsonl').read_text().splitlines()]
            rows=[e['row'] for e in entries if lo<=e['host_monotonic']<=hi]
            frames=[r for r in rows if r['event']=='sample' and r['source']=='camera']
            timings=[r for r in rows if r['event']=='frame_timing' and r['source']=='camera']
            expected=stage.get('expected_camera_frames',1000) if stage['stage']!='two_one_hour' else None
            if expected is not None and len(frames)!=expected: raise ValueError('Incomplete stage '+stage['stage'])
            if len(timings)!=len(frames): raise ValueError('Missing frame timing')
            if any(r['age_at_result_us']<0 or r['frame_start_us']<=0 for r in timings): raise ValueError('Invalid timestamp')
            if any(r['event'] in ('error','rejected') for r in rows): raise ValueError('Device failure')
            ms={}
            for field in ('acquisition_us','preprocessing_us','input_prepare_us','invoke_us','packing_us','request_response_us','observed_cycle_us'):
                ms[field]={f'p{p}':percentile([r[field]/1000 for r in frames],p) for p in (50,95,99)}
            for field in ('age_at_delivery_us','age_at_result_us'):
                ms[field]={f'p{p}':percentile([r[field]/1000 for r in timings],p) for p in (50,95,99)}
            ready=[r['result_us'] for r in timings]
            if any(b<=a for a,b in zip(ready,ready[1:])): raise ValueError('Non-monotonic results')
            timestamps=[r['frame_start_us'] for r in timings]
            if any(b<=a for a,b in zip(timestamps,timestamps[1:])): raise ValueError('Repeated/stale frame sequence')
            gaps=[(b-a)/1000 for a,b in zip(ready,ready[1:])]
            memory=[r for r in rows if r['event']=='memory']
            stable=True
            if len(memory)>=6:
                for key in ('internal_free','psram_free'):
                    if median(r[key] for r in memory[-3:])<median(r[key] for r in memory[:3])-4096: stable=False
            stats[board]=dict(frames=len(frames),metrics_ms=ms,fps=(len(ready)-1)*1e6/(ready[-1]-ready[0]),
                result_gap_p95_ms=percentile(gaps,95),max_result_gap_ms=max(gaps),memory_stable=stable,
                internal_min_free=min((r['internal_min_free'] for r in memory),default=None),
                psram_min_free=min((r['psram_min_free'] for r in memory),default=None))
        result[stage['stage']]=stats
    return result

def choose(stats,variants=(1,2,3)):
    names=['reference_hold','lut_hold','reference_early','lut_early']
    def aggregate(name,field,p):
        return median(stats[f'single_r{r}_{name}']['A']['metrics_ms'][field][p] for r in (1,2,3))
    base=aggregate(names[0],'observed_cycle_us','p50'); valid=[]
    for variant in variants:
        name=names[variant];value=aggregate(name,'observed_cycle_us','p50')
        if value>base*.95: continue
        if any(not stats[f'single_r{r}_{name}']['A']['memory_stable'] for r in (1,2,3)): continue
        if any(aggregate(name,f,'p95')>aggregate(names[0],f,'p95')*1.05 for f in ('observed_cycle_us','age_at_result_us')): continue
        valid.append((value,variant))
    return min(valid)[1] if valid else None

def confirm_two(stats,candidate):
    """Require the individual margins on each physical board before the hour."""
    names=['reference_hold','lut_hold','reference_early','lut_early']
    baseline=stats['two_reference_hold']; trial=stats['two_'+names[candidate]]
    result={}
    for board in ('A','B'):
        a,b=baseline[board],trial[board]
        checks=dict(complete=a['frames']==b['frames']==1000,
                    memory_stable=b['memory_stable'],
                    median_gain=b['metrics_ms']['observed_cycle_us']['p50']<=a['metrics_ms']['observed_cycle_us']['p50']*.95,
                    cycle_tail=b['metrics_ms']['observed_cycle_us']['p95']<=a['metrics_ms']['observed_cycle_us']['p95']*1.05,
                    frame_age=b['metrics_ms']['age_at_result_us']['p95']<=a['metrics_ms']['age_at_result_us']['p95']*1.05)
        result[board]=dict(passed=all(checks.values()),checks=checks)
    return result

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    stats=summarize(a.run);a.output.write_text(json.dumps(dict(stages=stats,candidate=choose(stats)),indent=2)+'\n')
