"""Native server hot path, cross-checked against the independent Python decoder."""
import ctypes
from pathlib import Path
import subprocess
import tempfile
import numpy as np
HERE=Path(__file__).resolve().parent

class NativeRice:
    def __init__(self):
        self.temp=tempfile.TemporaryDirectory(prefix='sciot-rice-decoder-')
        p=Path(self.temp.name)
        (p/'wrapper.cpp').write_text('#include "rice_decoder.h"\nextern "C" int decode(const uint8_t* d,size_t n,const int16_t* p,int z,int8_t* o){return decodeRice(d,n,p,z,o);}\n')
        subprocess.run(['c++','-O2','-std=c++17','-Wall','-Wextra','-Werror','-shared','-fPIC','-I'+str(HERE/'include'),str(p/'wrapper.cpp'),'-o',str(p/'decoder.so')],check=True)
        self.lib=ctypes.CDLL(str(p/'decoder.so'))
        self.lib.decode.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p]
        self.lib.decode.restype=ctypes.c_int
    def decode(self,data,previous,zero):
        source=np.frombuffer(data,np.uint8);output=np.empty(4608,np.int8)
        prior=None if previous is None else np.ascontiguousarray(previous,np.int16)
        if prior is not None and prior.shape!=(4608,):raise ValueError('Reference shape')
        code=self.lib.decode(source.ctypes.data,len(data),None if prior is None else prior.ctypes.data,int(zero),output.ctypes.data)
        if code:raise ValueError(f'Invalid native Rice stream ({code})')
        return output.tobytes()
