"""Bounded real-socket WS replay, with fragmented messages and exact suffix checks."""
import argparse
import asyncio
import json
from pathlib import Path
import time
import zlib

import numpy as np
from websockets.asyncio.client import connect
from server.multiclient.engine import Suffix
from server.multiclient.protocol import HEADER, REQUEST_MAGIC
from server.multiclient.websocket import ENVELOPE, pack


async def run(args):
    artifacts=Path(args.artifacts)
    model=json.loads((artifacts/'manifest.json').read_text())['models']['int8']['prefix']['sha256']
    engine=Suffix(artifacts)
    # Explicit synthetic boundary activations; this tests transport and suffix, not prefix accuracy.
    packets=[];expected=[]
    for i in range(3):
        activation=bytes([i])*4608
        body=HEADER.pack(REQUEST_MAGIC,1,1,i,0,0,4608,zlib.crc32(activation))+activation
        packets.append(body);expected.append(engine(body)[32:])
    ready=asyncio.Event();registered=0;rows=[]
    async def client(index):
        nonlocal registered
        async with connect(args.url,compression=None,max_size=1776,max_queue=1) as ws:
            await ws.send(json.dumps(dict(version=1,client_id=f'ws-sim-{index}',model_sha256=model)))
            session=json.loads(await ws.recv())['session_id']
            registered+=1
            if registered==args.clients:ready.set()
            await asyncio.wait_for(ready.wait(),10)
            for seq in range(args.requests):
                body=pack(1,seq,packets[seq%3]);start=time.monotonic()
                # Real RFC fragmentation, not simply two application messages.
                await ws.send([body[:17],body[17:1000],body[1000:]])
                reply=await asyncio.wait_for(ws.recv(),15)
                correct=False;status=200
                if isinstance(reply,str):
                    error=json.loads(reply);status=error['status']
                    assert error['session_id']==session and error['request_id']==str(seq)
                    assert status==429,error
                    await asyncio.sleep(.25)
                else:
                    assert ENVELOPE.unpack_from(reply)==(b'SCW1',1,2,0,seq)
                    correct=reply[48:]==expected[seq%3]
                    assert correct,'Numerical mismatch'
                rows.append(dict(client=index,request=seq,status=status,correct=correct,latency_ms=(time.monotonic()-start)*1000))
    await asyncio.gather(*(client(i) for i in range(args.clients)))
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    (output/'requests.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    summary=dict(clients=args.clients,requests=len(rows),completed=sum(r['correct'] for r in rows),rejected=sum(r['status']==429 for r in rows),scope='Synthetic PC activations over real fragmented WebSocket messages')
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='ws://127.0.0.1:8000/api/v2/ws');p.add_argument('--artifacts',default='experiments/esp32_representation_benchmark/artifacts');p.add_argument('--clients',type=int,default=2);p.add_argument('--requests',type=int,default=100);p.add_argument('--output',required=True)
    a=p.parse_args()
    if not 1<=a.clients<=32 or a.requests<1:p.error('Invalid load limits')
    asyncio.run(run(a))
