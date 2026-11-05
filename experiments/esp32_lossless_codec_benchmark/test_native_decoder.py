import unittest
import numpy as np
from native import Native
from native_decoder import NativeRice
from protocol import N,rice_decode

class NativeDecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.encoder=Native();cls.decoder=NativeRice()
    def test_valid_exact_against_python(self):
        rng=np.random.default_rng(73)
        frames=[np.full(N,v,np.int8) for v in (-128,127,-20,0)]
        frames+=[rng.integers(-40,40,N,dtype=np.int16).astype(np.int8) for _ in range(6)]
        frames+=[frames[-1].copy()]
        prior=None
        for x in frames:
            for p in (None,prior):
                data=self.encoder.rice(x,p)
                if data:
                    reference=None if p is None else p.astype(np.int16)
                    self.assertEqual(self.decoder.decode(data,reference,-20),rice_decode(data,reference,-20))
                    self.assertEqual(self.decoder.decode(data,reference,-20),x.tobytes())
            prior=x
    def test_invalid_matches_python(self):
        x=np.full(N,-20,np.int8);x[0]=-19;data=self.encoder.rice(x)
        malformed=[b'',bytes([9])+data[1:],data[:-1],data+b'\0',data[:-1]+bytes([data[-1]|1]),bytes(8)+bytes(4096),bytes(8)+bytes([255])*577]
        for payload in malformed:
            for decode in (self.decoder.decode,rice_decode):
                with self.assertRaises(ValueError):decode(payload,None,-20)
if __name__=='__main__':unittest.main()
