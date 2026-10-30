import os
import struct
import unittest
import zlib
from protocol import encode,parse_request,REQUEST,REQUEST_MAGIC,VERSION,RAW_BYTES


class ProtocolTests(unittest.TestCase):
    def test_roundtrip_real_repetitive_and_incompressible(self):
        from pathlib import Path
        parent=Path(__file__).resolve().parent.parent/'esp32_representation_benchmark/results/2026-10-27-espnn-run1/server'
        captures=list(parent.glob('*int8*.request.bin'))
        real=[captures[0].read_bytes()[32:]] if captures else []
        for raw in real+[b'\x80'*RAW_BYTES,bytes(range(256))*18,os.urandom(RAW_BYTES)]:
            for codec in (0,1):
                self.assertEqual(parse_request(encode(raw,codec))['activation'],raw)

    def test_bounded_decode_trailing_and_incomplete(self):
        for data in (b'x'*(RAW_BYTES+1),b'x'*1000000):
            wire=zlib.compress(data,1)
            packet=REQUEST.pack(REQUEST_MAGIC,VERSION,1,48,0,RAW_BYTES,len(wire),0)+wire
            with self.assertRaises(ValueError):parse_request(packet)
        valid=encode(b'x'*RAW_BYTES,1)
        for payload in (valid[32:]+b'extra',valid[32:-1],valid[32:]+valid[32:]):
            fields=list(REQUEST.unpack_from(valid));fields[6]=len(payload)
            with self.assertRaises(ValueError):parse_request(REQUEST.pack(*fields)+payload)

    def test_headers_corruption_and_wrong_sizes(self):
        valid=encode(b'x'*RAW_BYTES,1)
        for index,value in ((0,0),(1,1),(2,8),(5,RAW_BYTES+1),(6,9000),(7,0)):
            fields=list(REQUEST.unpack_from(valid));fields[index]=value
            with self.assertRaises(ValueError):parse_request(REQUEST.pack(*fields)+valid[32:])
        for bad in (b'',valid[:-1],valid+b'x',valid[:-1]+bytes([valid[-1]^1])):
            with self.assertRaises(ValueError):parse_request(bad)

if __name__=='__main__':unittest.main()
