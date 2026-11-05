"""Check the actual pinned miniz C implementation, including stream resets."""
import ctypes
from pathlib import Path
import subprocess
import tempfile
import unittest
import zlib
import numpy as np
N=4608
HERE=Path(__file__).resolve().parent
class MinizTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='sciot-lossless-miniz-')
        self.addCleanup(self.temp.cleanup)
    def test_actual_miniz_levels_and_repeated_reset(self):
        vendor=HERE/'idf/vendor/miniz'
        wrapper=HERE/'idf/components/miniz_idf'
        folder=Path(self.temp.name)
        source=folder/'miniz_check.c';library=folder/'miniz_check.so'
        source.write_text('''#include "miniz.h"
int compress_frames(const unsigned char* input,unsigned char* output,unsigned int* sizes,int count,int level) {
 mz_stream s={0};if(mz_deflateInit(&s,level)!=MZ_OK)return 1;
 for(int i=0;i<count;++i) {
  if(mz_deflateReset(&s)!=MZ_OK)return 2;
  s.next_in=input+i*4608;s.avail_in=4608;s.next_out=output+i*8192;s.avail_out=8192;
  if(mz_deflate(&s,MZ_FINISH)!=MZ_STREAM_END || s.avail_in)return 3;sizes[i]=s.total_out;
 }mz_deflateEnd(&s);return 0;
}''')
        subprocess.run(['cc','-shared','-fPIC','-O2','-DMINIZ_NO_ARCHIVE_APIS','-DMINIZ_NO_STDIO',
            '-DMINIZ_NO_TIME','-DMINIZ_NO_ZLIB_COMPATIBLE_NAMES','-I'+str(vendor),'-I'+str(wrapper),
            str(source),str(vendor/'miniz.c'),str(vendor/'miniz_tdef.c'),str(vendor/'miniz_tinfl.c'),'-o',str(library)],check=True)
        native=ctypes.CDLL(str(library))
        native.compress_frames.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.c_int]
        frames=[bytes(N),np.random.default_rng(7).integers(0,256,N,dtype=np.uint8).tobytes(),bytes(range(256))*18]*2
        for level in (1,6):
            output=ctypes.create_string_buffer(8192*len(frames));sizes=(ctypes.c_uint*len(frames))()
            self.assertEqual(native.compress_frames(b''.join(frames),output,sizes,len(frames),level),0)
            for i,frame in enumerate(frames):
                self.assertEqual(zlib.decompress(output.raw[i*8192:i*8192+sizes[i]]),frame)
            self.assertEqual(list(sizes[:3]),list(sizes[3:]))

