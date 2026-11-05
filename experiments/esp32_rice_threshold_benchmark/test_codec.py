import unittest
from host_encoder import *

class CodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.native=Native()
    def test_lossless_extremes_noise_long_sequence(self):
        rng=np.random.default_rng(20261030)
        frames=[np.full(N,v,np.int8) for v in [-128,127,-20,0]]
        frames+=[np.tile(np.arange(-128,128,dtype=np.int16).astype(np.int8),18)]
        frames+=[rng.integers(-128,128,N,dtype=np.int16).astype(np.int8) for _ in range(65)]
        frames += [frames[-1].copy() for _ in range(35)]
        for c in range(4):
            d=Decoder(.06843240559101105,-20);p=None
            for seq,x in enumerate(frames):
                body=packet(x,c,seq,p,native=self.native);r=d.decode(body)
                self.assertEqual(r['activation'],x.tobytes());p=x
                if c in (2,3):self.assertLessEqual(len(body),80+N)
    def test_rice_integer_boundaries(self):
        for current,previous in [(127,-128),(-128,127),(0,0),(-20,-20)]:
            x=np.full(N,current,np.int8);p=np.full(N,previous,np.int8)
            data=self.native.rice(x,p)
            if data:self.assertEqual(rice_decode(data,p.astype(np.int16),-20),x.tobytes())
    def test_rice_python_reference_bitstream(self):
        x=np.full(N,-20,np.int8);x[0]=-19;x[1]=-21
        data=self.native.rice(x)
        # All channels choose k=0. ZigZag + unary zeros + terminator.
        bits=''.join('0'*(2*int(v+20) if v>=-20 else -2*int(v+20)-1)+'1' for v in x.astype(np.int16))
        bits+='0'*(-len(bits)%8)
        expected=bytes(8)+bytes(int(bits[i:i+8],2) for i in range(0,len(bits),8))
        self.assertEqual(data,expected)
    def test_packing_preserves_lossy_reconstruction(self):
        rng=np.random.default_rng(4);scale=.06843240559101105;p=np.zeros(N,'<f4')
        decoders=[Decoder(scale,-20),Decoder(scale,-20)]
        for seq in range(65):
            x=rng.integers(-50,50,N,dtype=np.int16).astype(np.int8)
            rows=[d.decode(packet(x,c,seq,p,native=self.native)) for c,d in zip((4,5),decoders)]
            self.assertEqual(rows[0]['activation'],rows[1]['activation']);self.assertEqual(f32_bytes(rows[0]['state']),f32_bytes(rows[1]['state']))
            delta=bool(seq%30)
            v=dequantize(x.tobytes(),scale,-20)
            residual=(v.astype(np.float64)-p.astype(np.float64)).astype('<f4') if delta else v
            q,r=legacy.quantize(residual,4,delta)
            # C++ wrapper covers the P-frame encoder; complete uses same legacy code in firmware.
            if delta:
                cq,cr,cs=self.native.lossy(x,p,scale,-20)
                self.assertEqual(cq.tobytes(),q.tobytes());self.assertEqual(f32_bytes(cs),f32_bytes(rows[0]['state']))
            p=rows[0]['state']
    def test_corrupt_packets(self):
        x=np.full(N,-20,np.int8);b=packet(x,2,native=self.native)
        for bad in [b[:79],b[:-1],b+b'\0',alter(b,1,1),alter(b,4,99),alter(b,10,4),alter(b,13,N+1),alter(b,16,123),alter(b,12,99)]:
            with self.assertRaises(ValueError):Decoder(.1,-20).decode(bad)
        for data in [bytes([9])+b[81:],bytes(8)+bytes(4096),bytes(8)+bytes([255])*577]:
            with self.assertRaises(ValueError):rice_decode(data,None,-20)
        data=self.native.rice(x)
        with self.assertRaises(ValueError):rice_decode(data+b'\0',None,-20)
        y=x.copy();y[0]=-19;data=self.native.rice(y)
        with self.assertRaises(ValueError):rice_decode(data[:-1]+bytes([data[-1]|1]),None,-20)
    def test_sequence_restart_and_transactional_failure(self):
        x=np.full(N,-20,np.int8);d=Decoder(.1,-20)
        b=packet(x,3,native=self.native);d.decode(b)
        for bad in [b,packet(x,3,2,x,native=self.native),alter(packet(x,3,1,x,native=self.native),6,99)]:
            with self.assertRaises(ValueError):d.decode(bad)
        d.decode(packet(x,3,1,x,native=self.native))
        d.decode(packet(x,3,session=2,native=self.native))
        with self.assertRaises(ValueError):Decoder(.1,-20).decode(packet(x,3,1,x,native=self.native))
    def test_zlib_bounds(self):
        x=np.full(N,-20,np.int8);b=packet(x,1)
        for payload in [zlib.compress(bytes(N+1)),zlib.compress(bytes(N))+b'x',zlib.compress(bytes(N))[:-1]]:
            h=list(HEADER.unpack_from(b));h[14]=len(payload);h[-1]=crc(HEADER.pack(*h)[:76])
            with self.assertRaises(ValueError):Decoder(.1,-20).decode(HEADER.pack(*h)+payload)

if __name__=='__main__':unittest.main()
