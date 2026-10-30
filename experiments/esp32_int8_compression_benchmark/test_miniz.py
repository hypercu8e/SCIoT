"""Validate the actual pinned C compressor and repeated stream reset against Python."""
import ctypes
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
import zlib
from protocol import REQUEST,REQUEST_MAGIC,VERSION,parse_request

HERE=Path(__file__).resolve().parent


class MinizTests(unittest.TestCase):
    def test_native_encoder_reuse_and_exact_reconstruction(self):
        vendor=HERE/'idf/vendor/miniz';wrapper=HERE/'idf/components/miniz_idf'
        if not vendor.exists():self.skipTest('Run idf/fetch_miniz.py first')
        with tempfile.TemporaryDirectory(prefix='sciot-miniz-test-') as folder:
            folder=Path(folder);source=folder/'check.c';library=folder/'check.so'
            source.write_text('''#include "miniz.h"
int encode_many(const unsigned char* input,int count,unsigned char* output,unsigned int* sizes) {
  mz_stream s={0}; if(mz_deflateInit(&s,1)!=MZ_OK) return 1;
  for(int i=0;i<count;++i) {
    if(mz_deflateReset(&s)!=MZ_OK) return 2;
    s.next_in=input+i*4608;s.avail_in=4608;s.next_out=output+i*8192;s.avail_out=8192;
    if(mz_deflate(&s,MZ_FINISH)!=MZ_STREAM_END || s.avail_in) return 3;
    sizes[i]=s.total_out;
  }
  mz_deflateEnd(&s);return 0;
}''')
            subprocess.run(['cc','-shared','-fPIC','-O2','-DMINIZ_NO_ARCHIVE_APIS','-DMINIZ_NO_STDIO',
                '-DMINIZ_NO_TIME','-DMINIZ_NO_ZLIB_COMPATIBLE_NAMES','-I'+str(vendor),'-I'+str(wrapper),
                str(source),str(vendor/'miniz.c'),str(vendor/'miniz_tdef.c'),str(vendor/'miniz_tinfl.c'),'-o',str(library)],check=True)
            codec=ctypes.CDLL(str(library));codec.encode_many.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p]
            real_dir=HERE.parent/'esp32_representation_benchmark/results/2026-10-27-espnn-run1/server'
            real=[p.read_bytes()[32:] for p in sorted(real_dir.glob('*int8*.request.bin'))[:12]]
            frames=[b'\x80'*4608,os.urandom(4608),bytes(range(256))*18]+real
            frames=frames+frames
            output=ctypes.create_string_buffer(8192*len(frames));sizes=(ctypes.c_uint*len(frames))()
            source_bytes=b''.join(frames)
            self.assertEqual(codec.encode_many(source_bytes,len(frames),output,sizes),0)
            for index,frame in enumerate(frames):
                payload=output.raw[index*8192:index*8192+sizes[index]]
                packet=REQUEST.pack(REQUEST_MAGIC,VERSION,1,48,index,4608,len(payload),zlib.crc32(frame))+payload
                self.assertEqual(parse_request(packet)['activation'],frame)
            halfway=len(frames)//2
            self.assertEqual(list(sizes[:halfway]),list(sizes[halfway:]))

if __name__=='__main__':unittest.main()
