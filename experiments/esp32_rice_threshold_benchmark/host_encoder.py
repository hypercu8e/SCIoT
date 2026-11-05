import struct
import zlib
import numpy as np
from native import Native
from protocol import *

def packet(x,c,seq=0,previous=None,session=1,native=None,scale=.06843240559101105,zero=-20):
    x=np.ascontiguousarray(x,np.int8);raw=x.tobytes();delta=c>=3 and bool(seq%30)
    payload=raw;field=0;state=raw
    if c==1:payload=zlib.compress(raw,1);field=1
    elif c in (2,3):
        payload=native.rice(x,previous if delta else None,zero)
        if payload:field=2
        else:payload=raw;delta=False
    elif c>=4:
        v=dequantize(raw,scale,zero)
        residual=(v.astype(np.float64)-previous.astype(np.float64)).astype('<f4') if delta else v
        q,r=legacy.quantize(residual,4,delta)
        state=legacy.restore(q,r,4,previous if delta else None)
        payload=zlib.compress(q.tobytes(),6) if c==4 else native.pack(q)
        state=f32_bytes(state);field=struct.unpack('<I',struct.pack('<f',r))[0]
    bits,level=CONFIGS[c][1:]
    h=[MAGIC,VERSION,1,session,c,seq,seq-1 if delta else NONE,int(delta),seq,0,bits,level,field,N,len(payload),crc(raw),crc(state),0,0,0]
    h[-1]=crc(HEADER.pack(*h)[:76]);return HEADER.pack(*h)+payload

def alter(body,field,value):
    h=list(HEADER.unpack_from(body));h[field]=value;h[-1]=crc(HEADER.pack(*h)[:76]);return HEADER.pack(*h)+body[80:]

