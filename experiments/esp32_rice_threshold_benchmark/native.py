"""Compile the firmware Rice/packing kernels for host correctness checks."""
import ctypes
from pathlib import Path
import subprocess
import tempfile
import numpy as np

class Native:
    def __init__(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='sciot-lossless-')
        p=Path(self.tmp.name)
        (p/'wrapper.cpp').write_text('''#include "codec.h"
extern "C" size_t rice(const int8_t* x,const int8_t* p,int d,int z,uint8_t* o){return dz::rice(x,p,d,z,o);}
extern "C" void pack4(const int8_t* x,uint8_t* o){dz::pack4(x,o);}
extern "C" float lossy(const int8_t* x,const float* p,float* s,int8_t* q,float* w,int d,double scale,int z){return legacy::encode(x,p,s,q,w,9,d,scale,z);}
''')
        subprocess.run(['c++','-shared','-fPIC','-O2','-std=c++17','-ffp-contract=off','-I'+str(Path(__file__).parent/'include'),str(p/'wrapper.cpp'),'-o',str(p/'codec.so')],check=True)
        self.lib=ctypes.CDLL(str(p/'codec.so'))
        self.lib.rice.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_void_p];self.lib.rice.restype=ctypes.c_size_t
        self.lib.pack4.argtypes=[ctypes.c_void_p,ctypes.c_void_p]
        self.lib.lossy.argtypes=[ctypes.c_void_p]*5+[ctypes.c_int,ctypes.c_double,ctypes.c_int];self.lib.lossy.restype=ctypes.c_float
    def rice(self,x,p=None,zero=-20):
        x=np.ascontiguousarray(x,np.int8);p=np.ascontiguousarray(p,np.int8) if p is not None else None
        out=np.empty(8192,np.uint8)
        n=self.lib.rice(x.ctypes.data,p.ctypes.data if p is not None else None,p is not None,zero,out.ctypes.data)
        return out[:n].tobytes()
    def lossy(self,x,p,scale,zero):
        x=np.ascontiguousarray(x,np.int8);p=np.ascontiguousarray(p,'<f4')
        s=np.empty(4608,'<f4');w=np.empty_like(s);q=np.empty(4608,np.int8)
        r=self.lib.lossy(x.ctypes.data,p.ctypes.data,s.ctypes.data,q.ctypes.data,w.ctypes.data,1,scale,zero)
        return q,r,s
    def pack(self,q):
        q=np.ascontiguousarray(q,np.int8);out=np.empty(len(q)//2,np.uint8)
        self.lib.pack4(q.ctypes.data,out.ctypes.data);return out.tobytes()
