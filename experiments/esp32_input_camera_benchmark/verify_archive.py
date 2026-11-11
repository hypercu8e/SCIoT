"""Independent replay plus request/response correlation; use repository .venv."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import zlib
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL','3');os.environ.setdefault('CUDA_VISIBLE_DEVICES','-1')
from server.multiclient.engine import Suffix

def fnv(data):
    value=2166136261
    for b in data: value=((value^b)*16777619)&0xffffffff
    return value

def verify(run):
    completion=json.loads((run/'completion.json').read_text())
    if completion['restore_failures']: raise ValueError('Restoration failed')
    engine=Suffix(ROOT/'experiments/esp32_representation_benchmark/artifacts',1)
    requests=Counter();count=0
    with (run/'server/inference.bin').open('rb') as f:
        while sizes:=f.read(8):
            if len(sizes)!=8: raise ValueError('Truncated header')
            nb,nr=struct.unpack('<II',sizes)
            if (nb,nr)!=(4640,1760): raise ValueError('Invalid record sizes')
            body,reply=f.read(nb),f.read(nr)
            if len(body)!=nb or len(reply)!=nr: raise ValueError('Truncated archive')
            header=struct.unpack('<8I',body[:32])
            if zlib.crc32(body[32:])!=header[7]: raise ValueError('CRC mismatch')
            replay=engine(body)
            if replay[32:]!=reply[32:]: raise ValueError('Score replay mismatch')
            key=(header[3],header[4],fnv(body[32:]),fnv(reply))
            requests[key]+=1;count+=1
    matched=0;validation={};restored={}
    for name in ('A','B'):
        hardware=json.loads((run/name/'hardware.json').read_text());restored[name]=hardware['restored']
        if hardware['restored']:
            if hashlib.sha256((run/name/'original-flash.bin').read_bytes()).hexdigest()!=hardware['backup_sha256']: raise ValueError('Backup modified')
            if 'sciot_esp32_client' not in (run/name/'restored-boot.log').read_text(errors='replace'): raise ValueError('Original boot unconfirmed')
        entries=[json.loads(s)['row'] for s in (run/name/'events.jsonl').read_text().splitlines()] if (run/name/'events.jsonl').exists() else []
        correlation=None;seen=set()
        for row in entries:
            if row['event']=='correlation':
                identity=(row['client_id'],row['session_id'],row['request_id'])
                if identity in seen: raise ValueError('Duplicate request identity')
                seen.add(identity);correlation=row
            if row['event']=='sample':
                if not correlation or (row['frame'],row['iteration'])!=(correlation['frame'],correlation['iteration']): raise ValueError('Missing correlation')
                key=(row['frame'],row['iteration'],row['activation_fnv32'],row['response_fnv32'])
                if requests[key]<=0: raise ValueError('Sample absent from archive')
                requests[key]-=1;matched+=1;correlation=None
        validation[name]=dict(exhaustive=[r for r in entries if r['event']=='exhaustive_validation'],paired=sum(r['event']=='paired_validation' and r['exact'] for r in entries))
    # Unmatched requests include warmup. Interrupted older campaigns can also
    # contain traffic after serial logging stopped; do not call all of it warmup.
    unmatched=sum(requests.values())
    warmup=sum(count for key,count in requests.items() if 500<=key[0]<520)
    return dict(archived=count,measured_samples_matched=matched,
                unmatched_archived_requests=unmatched,
                unmeasured_warmup_requests=warmup,
                unmatched_other_requests=unmatched-warmup,
                scores_exact=True,validation=validation,restored=restored,measurements_complete=completion['measurements_complete'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.write_text(json.dumps(verify(a.run),indent=2)+'\n')
