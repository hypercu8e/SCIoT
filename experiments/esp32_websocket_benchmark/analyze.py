"""Audit complete or failed runs; never promote an incomplete campaign."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def percentile(values, q):
    values=sorted(values);position=(len(values)-1)*q/100
    lo=int(position);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(position-lo)


def verify_recovery(run):
    run=Path(run);completion=json.loads((run/'completion.json').read_text())
    meta=json.loads((run/'board/hardware.json').read_text())
    if not (completion['original_boot_confirmed'] and completion['restore_error'] is None and meta['backup_verified'] and meta['restored'] and sha(run/'board/original-flash.bin')==meta['backup_sha256']):
        raise ValueError('Original firmware recovery not verified')
    snapshots=json.loads((run/'source-sha256.json').read_text())
    for name,digest in snapshots.items():
        source=Path(name)
        if source.is_absolute() or source.parts[0]=='firmware':
            path=run/'firmware'/source.name
            if not path.is_file():raise ValueError('Firmware snapshot missing')
        else:
            path=run/'sources'/source
        if path.exists() and sha(path)!=digest:raise ValueError('Source snapshot mismatch')
    if sha(run/'firmware/firmware.bin')!=meta['installed_sha256']:raise ValueError('Installed binary mismatch')
    return completion


def audit(run):
    run=Path(run);completion=verify_recovery(run)
    boots=[]
    for path in sorted((run/'board').glob('round-*.events.jsonl')):
        rows=[json.loads(line)['row'] for line in path.read_text().splitlines()]
        exchanges=[r for r in rows if r['event']=='exchange'];passed=[r for r in exchanges if r['ok']]
        done=[r for r in rows if r['event']=='done'];errors=[r for r in rows if r['event']=='error']
        memory=[r['internal_min_free'] for r in rows if 'internal_min_free' in r]
        phases={}
        for name,selected in [('deterministic',[r for r in passed if 100<=r['iteration']<1100 and r['frame']<3]),('camera',[r for r in passed if r['frame']>=1000])]:
            phases[name]={'completed':len(selected),'request_response_ms':{f'p{q}':percentile([r['request_response_us']/1000 for r in selected],q) for q in (50,95,99)} if selected else {}}
        complete=bool(done) and not errors and len(exchanges)==2100 and len(passed)==2100 and min(memory)>=32768
        if complete:
            if [r['request_id'] for r in exchanges]!=list(range(2100)):raise ValueError('Missing/duplicate request')
            if len([r for r in rows if r['event']=='sample'])!=1000:raise ValueError('Missing camera frame')
            if len([r for r in rows if r['event']=='canonical_check'])!=10:raise ValueError('Missing canonical check')
        boots.append(dict(file=path.name,mode=exchanges[0]['mode'] if exchanges else None,complete=complete,attempted=len(exchanges),completed=len(passed),minimum_internal_free=min(memory) if memory else None,phases=phases,errors=errors))
    result=dict(restored=True,boots=boots,campaign_complete=completion['measurements_complete'] and len(boots)==9 and all(b['complete'] for b in boots),promotion_eligible=False,
        limitations=['Fault-recovery campaign and traffic capture are separate acceptance requirements.','Response CRCs do not establish full byte equality of camera scores.'],error=completion['error'])
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit(a.run);a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    text='# WebSocket v2: verifica fisica\n\n'
    text+='Flash originale ripristinata e boot verificato.\n\n'
    text+='Campagna completa: **'+str(result['campaign_complete'])+'**. Promozione operativa: **non autorizzata da questo report**.\n\n'
    for b in result['boots']:text+=f"- {b['file']}: {b['completed']}/{b['attempted']} richieste riuscite, minimo interno {b['minimum_internal_free']} byte, avvio completo {b['complete']}.\n"
    if result['error']:text+='\nErrore osservato: '+result['error']+'\n'
    text+='\nI risultati incompleti non dimostrano stabilita, prestazioni comparative o correttezza completa del servizio.\n'
    (a.output/'report.md').write_text(text);print(json.dumps(result))

if __name__=='__main__':main()
