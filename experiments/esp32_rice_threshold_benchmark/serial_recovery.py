"""Explicit recovery of first-sample identity prefixes; never reconstruct timings."""
import hashlib
import json
from protocol import HEADER,REPLY,MAGIC,VERSION,crc

TIMERS=('acquisition_us','preprocess_us','prepare_us','invoke_us','quantize_reconstruct_us','compression_us','packing_us','network_us','cycle_us','server_decode_us','server_invoke_us','server_post_us')
FIELDS={'source','config','original_crc','state_crc','input_crc','activation_crc','wire_bytes','kind',*TIMERS}

def sha(data):return hashlib.sha256(data).hexdigest()
def check(ok,message):
    if not ok:raise ValueError('Serial recovery: '+message)

def read_serial(run):
    raw=(run/'device.log').read_bytes();lines=raw.splitlines();path=run/'serial-recovery.json'
    info=None
    if path.exists():
        info=json.loads(path.read_text());check(info['device_log_sha256']==sha(raw),'original log changed')
        repaired=set()
        for item in info['records']:
            i=item['line']-1;check(0<i<len(lines)-1 and i not in repaired,'line index')
            fragment=lines[i];check(sha(fragment)==item['fragment_sha256'],'fragment changed')
            check(fragment.startswith(b':'),'only source-key prefix loss is recoverable')
            suffix=json.loads(b'{"source"'+fragment)
            check(set(suffix)==FIELDS,'timings or suffix fields missing')
            check(all(type(suffix[k]) is int and suffix[k]>=0 for k in TIMERS),'invalid timer')
            name=item['server_name'];check('/' not in name and '..' not in name,'packet name')
            body=(run/'server'/f'{name}.request.bin').read_bytes();reply=(run/'server'/f'{name}.response.bin').read_bytes()
            check(sha(body)==item['request_sha256'] and sha(reply)==item['response_sha256'],'packet changed')
            h=HEADER.unpack_from(body);r=REPLY.unpack_from(reply)
            check(h[:2]==(MAGIC,VERSION) and crc(body[:76])==h[19] and len(body)==80+h[14],'request header')
            check(h[5]==0 and h[9]==0 and len(reply)==1776,'only first video sample supported')
            check(r[2:7]==(h[2],h[3],h[4],h[5],h[8]),'response identity')
            for field,index in [('source',9),('config',4),('original_crc',15),('state_crc',16),('input_crc',17),('wire_bytes',14),('kind',7)]:check(suffix[field]==h[index],'request/suffix mismatch '+field)
            for field,index in [('server_decode_us',7),('server_invoke_us',8),('server_post_us',9),('activation_crc',11)]:check(suffix[field]==r[index],'response/suffix mismatch '+field)
            before=json.loads(lines[i-1]);after=json.loads(lines[i+1])
            check(before['event']=='sequence_start' and (before['session'],before['config'],before['source'])==(h[3],h[4],h[9]),'sequence context')
            check(after['event']=='sample' and (after['session'],after['seq'])==(h[3],1),'next sample context')
            prefix=f'{{"event":"sample","session":{h[3]},"seq":0,"frame":{h[8]},"source"'.encode()
            lines[i]=prefix+fragment;repaired.add(i)
        check(bool(repaired),'empty recovery manifest')
        info=dict(info,method='Only identity prefix restored from archived request and adjacent sequence records; all timers retained verbatim',recovered_records=len(repaired))
    result=[]
    for line in lines:
        try:r=json.loads(line)
        except (ValueError,UnicodeDecodeError):continue
        if isinstance(r,dict):result.append(r)
    return result,info
