"""Real HTTP replay clients; one outstanding request per identity, no inference retries."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import zlib

import numpy as np
from server.multiclient.engine import Suffix
from server.multiclient.protocol import HEADER, REQUEST_MAGIC, RESPONSE_MAGIC


def request(url, body, headers):
    req=urllib.request.Request(url,body,headers,method='POST')
    try:
        with urllib.request.urlopen(req,timeout=15) as reply:
            return reply.status,reply.headers,reply.read()
    except urllib.error.HTTPError as error:
        return error.code,error.headers,error.read()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url',default='http://127.0.0.1:8000')
    p.add_argument('--artifacts',type=Path,default=Path('experiments/esp32_representation_benchmark/artifacts'))
    p.add_argument('--clients',type=int,default=2)
    p.add_argument('--requests',type=int,default=100)
    p.add_argument('--duration',type=float,default=0,help='Seconds per client; overrides request count')
    p.add_argument('--rate',type=float,default=0,help='Scheduled requests/sec/client; zero is response-limited')
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.clients<1 or args.requests<1 or args.duration<0 or args.rate<0:p.error('Invalid load configuration')
    args.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads((args.artifacts/'manifest.json').read_text())
    model_hash=manifest['models']['int8']['prefix']['sha256']
    import tensorflow as tf
    binary=(args.artifacts/'int8-prefix.tflite').read_bytes()
    if hashlib.sha256(binary).hexdigest()!=model_hash:raise ValueError('Prefix hash mismatch')
    prefix=tf.lite.Interpreter(model_content=binary,num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    prefix.allocate_tensors();spec=prefix.get_input_details()[0];out=prefix.get_output_details()[0]
    with np.load(args.artifacts/'inputs.npz') as frozen:
        frames=frozen['frames'];ids=frozen['frame_ids']
    engine=Suffix(args.artifacts);packets=[];expected=[]
    for fid,frame in zip(ids,frames):
        values=np.clip(np.rint(frame.astype(np.float64)/spec['quantization'][0]+spec['quantization'][1]),-128,127).astype(np.int8)
        prefix.set_tensor(spec['index'],values[None]);prefix.invoke()
        activation=prefix.get_tensor(out['index']).tobytes()
        body=HEADER.pack(REQUEST_MAGIC,1,1,int(fid),0,0,4608,zlib.crc32(activation))+activation
        packets.append(body);expected.append(engine(body)[32:])
    start=time.monotonic()
    def client(index):
        cid=f'sim-{index}';session=None;seq=0;rows=[];slot=0;missed=0
        with (args.output/f'{cid}.jsonl').open('x') as log:
            while (time.monotonic()-start<args.duration) if args.duration else (len(rows)<args.requests):
                if args.rate:
                    target=start+slot/args.rate
                    if target>time.monotonic():time.sleep(target-time.monotonic())
                    actual_slot=int((time.monotonic()-start)*args.rate)
                    missed+=max(0,actual_slot-slot);slot=max(slot,actual_slot)+1
                if session is None:
                    status,_,data=request(args.url+'/api/v2/registration',json.dumps({'client_id':cid,'model_sha256':model_hash}).encode(),{'Content-Type':'application/json'})
                    if status!=200:raise RuntimeError(f'Registration failed: {status}')
                    session=json.loads(data)['session_id'];seq=0
                sample=(index+len(rows))%len(packets)
                headers={'Content-Type':'application/octet-stream','X-Client-ID':cid,
                         'X-Session-ID':session,'X-Request-ID':str(seq),'X-Model-SHA256':model_hash}
                begun=time.monotonic()
                try:
                    status,reply,data=request(args.url+'/api/v2/infer',packets[sample],headers)
                    correct=(status==200 and reply.get('X-Client-ID')==cid and reply.get('X-Session-ID')==session
                             and reply.get('X-Request-ID')==str(seq) and len(data)==1760
                             and HEADER.unpack_from(data)[:5]==(RESPONSE_MAGIC,1,int(ids[sample]),0,432)
                             and data[32:]==expected[sample])
                except (TimeoutError,OSError,urllib.error.URLError):
                    status,correct=0,False
                row={'client_id':cid,'session_id':session,'request_id':seq,'status':status,
                     'correct':correct,'latency_ms':(time.monotonic()-begun)*1000}
                log.write(json.dumps(row)+'\n');log.flush();rows.append(row);seq+=1
                if status==200 and not correct:raise AssertionError('Cross-client or numerical mismatch')
                if status==429:time.sleep(.25+index%251/1000)
                if status in (0,410,504):session=None
        return {'client_id':cid,'attempted':len(rows),'completed':sum(r['correct'] for r in rows),
                'rejected':sum(r['status']==429 for r in rows),'failed':sum(r['status'] not in (200,429) for r in rows),
                'missed_scheduled_slots':missed,'latency_ms':{f'p{q}':float(np.percentile([r['latency_ms'] for r in rows if r['correct']],q))
                    for q in (50,95,99)} if any(r['correct'] for r in rows) else {}}
    with ThreadPoolExecutor(max_workers=args.clients) as pool:
        summaries=list(pool.map(client,range(args.clients)))
    elapsed=time.monotonic()-start
    result={'configuration':vars(args),'elapsed_s':elapsed,'clients':summaries,
            'completed_per_second':sum(s['completed'] for s in summaries)/elapsed,
            'scope':'PC HTTP replay, not ESP32/Wi-Fi validation'}
    (args.output/'summary.json').write_text(json.dumps(result,default=str,indent=2)+'\n')
    print(json.dumps(result,default=str))


if __name__=='__main__':main()
