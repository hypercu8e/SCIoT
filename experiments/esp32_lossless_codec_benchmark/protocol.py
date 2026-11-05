"""SLC2: bounded decoder with INT8 lossless state and explicit wire coding."""
import importlib.util
from pathlib import Path
import struct
import sys
import zlib
import numpy as np
_spec=importlib.util.spec_from_file_location('_sciot_legacy_dz',Path(__file__).resolve().parent.parent/'esp32_deadzone_benchmark/protocol.py')
legacy=importlib.util.module_from_spec(_spec);sys.modules[_spec.name]=legacy;_spec.loader.exec_module(legacy)
N=4608;HEADER=struct.Struct('<20I');REPLY=struct.Struct('<12I')
MAGIC=int.from_bytes(b'SLC2','little');REPLY_MAGIC=int.from_bytes(b'SLR2','little');VERSION=2;NONE=0xffffffff
MAX_PAYLOAD=8192;MAX_BODY=80+MAX_PAYLOAD
CONFIGS=[(0,0,0),(1,0,1),(2,0,0),(3,0,0),(4,4,6),(5,4,0)]
NAMES=['raw','zlib1','rice_independent','rice_temporal','deadzone4_zlib','deadzone4_packed']
crc=legacy.crc;dequantize=legacy.dequantize;requantize=legacy.requantize
f32_bytes=legacy.f32_bytes

def rice_decode(data,previous,zero):
    if len(data)<8 or len(data)>=N or any(k>8 for k in data[:8]):raise ValueError('Rice size/parameters')
    pos=64;result=np.empty(N,np.int8)
    def bit():
        nonlocal pos
        if pos>=len(data)*8:raise ValueError('Truncated Rice')
        v=(data[pos//8]>>(7-pos%8))&1;pos+=1;return v
    for i in range(N):
        k=data[i%8];q=0
        while bit()==0:
            q+=1
            if q>510:raise ValueError('Rice quotient overflow')
        u=q<<k
        for b in range(k-1,-1,-1):u|=bit()<<b
        if u>510:raise ValueError('Rice residual overflow')
        d=-(u//2)-1 if u&1 else u//2
        x=d+(previous[i] if previous is not None else zero)
        if not -128<=x<=127:raise ValueError('INT8 overflow')
        result[i]=x
    if len(data)!=(pos+7)//8:raise ValueError('Trailing Rice bytes')
    while pos<len(data)*8:
        if bit():raise ValueError('Nonzero padding')
    return result.tobytes()

def inflate(payload,count):
    d=zlib.decompressobj()
    try:x=d.decompress(payload,count+1)
    except zlib.error as e:raise ValueError('Invalid zlib') from e
    if len(x)!=count or not d.eof or d.unused_data or d.unconsumed_tail:raise ValueError('Invalid zlib size/trailing data')
    return x

class Decoder:
    def __init__(self,scale,zero):self.scale=scale;self.zero=zero;self.states={};self.latest={}
    def decode(self,body):
        if not 80<=len(body)<=MAX_BODY:raise ValueError('Body size')
        keys=('magic','version','device','session','config','seq','ref','kind','frame','source','bits','level','radius_bits','count','length','original_crc','state_crc','input_crc','diagnostic_source','header_crc')
        r=dict(zip(keys,HEADER.unpack_from(body)))
        if (r['magic'],r['version'])!=(MAGIC,VERSION) or crc(body[:76])!=r['header_crc']:raise ValueError('Header')
        c=r['config'];source=r['source'];diag=source==2
        if not 0<=c<len(CONFIGS) or source not in (0,1,2) or r['diagnostic_source'] not in (0,1):raise ValueError('Config/source')
        mode,bits,level=CONFIGS[c]
        if diag:mode=bits=level=0
        if (r['bits'],r['level'])!=(bits,level) or r['count']!=N or r['length']!=len(body)-80 or not 0<r['length']<=MAX_PAYLOAD:raise ValueError('Parameters')
        if r['kind'] not in (0,1):raise ValueError('Kind')
        key=r['device'],r['session'],c,source
        prior=self.states.get(key)
        delta=bool(r['kind'])
        if diag:
            if delta or r['ref']!=NONE:raise ValueError('Diagnostic reference')
        else:
            if prior is not None and r['seq']!=prior[0]+1:raise ValueError('Sequence')
            if prior is None and r['seq']!=0:raise ValueError('Missing initial frame')
            if delta and (mode not in (3,4,5) or r['seq']%30==0 or prior is None or r['ref']!=prior[0]):raise ValueError('Reference')
            if not delta and r['ref']!=NONE:raise ValueError('Unexpected reference')
            if mode in (4,5) and delta != bool(r['seq']%30):raise ValueError('Lossy frame kind')
        payload=body[80:];previous=prior[1] if delta else None
        if mode<4:
            wire=r['radius_bits']
            if wire==0 and mode in (0,2,3):
                if len(payload)!=N or delta:raise ValueError('Raw payload')
                activation=payload
            elif wire==1 and mode==1 and not delta:activation=inflate(payload,N)
            elif wire==2 and mode in (2,3):
                if mode==3 and not delta and r['seq']%30:raise ValueError('Unexpected independent Rice frame')
                activation=rice_decode(payload,previous,self.zero)
            else:raise ValueError('Wire encoding')
            state=np.frombuffer(activation,np.int8).astype(np.int16);state_bytes=activation
            if crc(activation)!=r['original_crc']:raise ValueError('Lossless CRC')
        else:
            radius=struct.unpack('<f',struct.pack('<I',r['radius_bits']))[0]
            if not np.isfinite(radius) or radius<0:raise ValueError('Radius')
            if mode==4:symbols=inflate(payload,N)
            else:
                if len(payload)!=N//2:raise ValueError('Packed size')
                b=np.frombuffer(payload,np.uint8);q=np.empty(N,np.int8)
                q[::2]=(b>>4).astype(np.int8);q[1::2]=(b&15).astype(np.int8);q[q>=8]-=16;symbols=q.tobytes()
            q=np.frombuffer(symbols,np.int8)
            if (q < -8).any() or (q>7).any():raise ValueError('Symbol range')
            state=legacy.restore(q,radius,4,previous);state_bytes=f32_bytes(state)
            activation=requantize(state,self.scale,self.zero)
        if crc(state_bytes)!=r['state_crc']:raise ValueError('State CRC')
        if not diag:
            device=r['device'];old=self.latest.get(device)
            if old is not None and old!=r['session']:
                if r['seq']!=0:raise ValueError('New session without complete')
                self.states={k:v for k,v in self.states.items() if k[0]!=device}
            if device not in self.latest and len(self.latest)>=4:raise ValueError('Device limit')
            self.latest[device]=r['session'];self.states[key]=(r['seq'],state.copy())
        r.update(activation=activation,state=state,radius=0 if mode<4 else radius)
        return r
