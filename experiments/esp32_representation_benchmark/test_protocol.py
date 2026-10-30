import struct
import unittest
import zlib

from protocol import REQUEST, REQUEST_MAGIC, parse_request


def packet(dtype=1,image=b''):
    activation=bytes(4608*(4 if dtype==0 else 1))
    payload=image+activation
    return REQUEST.pack(REQUEST_MAGIC,1,dtype,48,0,len(image),len(activation),zlib.crc32(payload))+payload


class ProtocolTest(unittest.TestCase):
    def test_both_representations_and_optional_image(self):
        for dtype in (0,1):
            for image in (b'',bytes(96*96*2)):
                r=parse_request(packet(dtype,image))
                self.assertEqual(len(r['image']),len(image))
                self.assertEqual(len(r['activation']),4608*(4 if dtype==0 else 1))

    def test_truncated_overlong_and_corrupted_body(self):
        body=packet()
        for bad in (body[:-1],body+b'x',body[:-1]+b'x'):
            with self.assertRaises(ValueError):
                parse_request(bad)

    def test_wrong_version_dtype_and_tensor_size(self):
        body=bytearray(packet())
        for field,value in ((0,0),(1,2),(2,2),(5,1),(6,4)):
            bad=bytearray(body)
            struct.pack_into('<I',bad,4*field,value)
            with self.assertRaises(ValueError):
                parse_request(bad)


if __name__=='__main__':
    unittest.main()
