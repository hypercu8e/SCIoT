"""Exercise production C++ quantizer and Python decoder, not an ESP32 emulator."""
import ctypes
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib

import numpy as np
from protocol import (CONFIGS, Decoder, HEADER, MAGIC, N, NONE, crc, dequantize,
                      f32_bytes, float_bits, quantize, requantize, restore)

HERE = Path(__file__).resolve().parent


def packet(raw, config, seq, previous=None, session=1, source=0, scale=.06843240559101105, zero=-20):
    mode, bits, level = CONFIGS[config]
    delta = mode >= 3 and seq % 30 != 0
    values = dequantize(raw, scale, zero)
    if mode < 2:
        symbols, radius, state = raw, 0., values
    else:
        residual = (values.astype(np.float64)-previous.astype(np.float64)).astype('<f4') if delta else values
        indices, radius = quantize(residual, bits, mode == 4 and delta)
        symbols = indices.tobytes()
        state = restore(indices, radius, bits, previous if delta else None)
    payload = symbols if mode == 0 else zlib.compress(symbols, level)
    fields = [MAGIC, 1, 7, session, config, seq, seq-1 if delta else NONE, int(delta), seq,
              source, bits, level, float_bits(radius), N, len(payload), crc(raw), crc(f32_bytes(state)), 0, 0, 0]
    header = HEADER.pack(*fields)
    fields[-1] = crc(header[:76])
    return HEADER.pack(*fields)+payload, state


def change_packet(body, changes=None, payload=None):
    fields=list(HEADER.unpack_from(body))
    for key,value in (changes or {}).items():fields[key]=value
    if payload is None:payload=body[80:]
    fields[14]=len(payload)
    header=HEADER.pack(*fields);fields[-1]=crc(header[:76])
    return HEADER.pack(*fields)+payload


class CodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='sciot-deadzone-native-')
        folder = Path(cls.temp.name)
        (folder/'native.cpp').write_text('''#include "codec.h"
extern "C" float encode(const int8_t* x,const float* p,float* s,int8_t* q,float* w,int c,int d,double scale,int z) {
 return dz::encode(x,p,s,q,w,c,d,scale,z);
}
extern "C" int requant(const float* x,int8_t* y,double scale,int z) {
 for(int i=0;i<dz::N;++i)y[i]=dz::requant(x[i],scale,z);return 0;
}''')
        subprocess.run(['c++', '-shared', '-fPIC', '-O2', '-ffp-contract=off', '-std=c++17',
                        '-I'+str(HERE/'include'), str(folder/'native.cpp'), '-o', str(folder/'native.so')], check=True)
        cls.lib = ctypes.CDLL(str(folder/'native.so'))
        cls.lib.encode.argtypes = [ctypes.c_void_p]*5 + [ctypes.c_int, ctypes.c_int, ctypes.c_double, ctypes.c_int]
        cls.lib.encode.restype = ctypes.c_float
        cls.lib.requant.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double, ctypes.c_int]

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_native_matches_decoder_all_modes_long_sequences(self):
        scale, zero = .06843240559101105, -20
        rng = np.random.default_rng(20261029)
        frames = [np.full(N, zero, np.int8), np.full(N, -128, np.int8), np.full(N, 127, np.int8),
                  np.tile(np.arange(-128, 128, dtype=np.int16).astype(np.int8), 18)]
        frames += [rng.integers(-128, 128, N, dtype=np.int16).astype(np.int8) for _ in range(61)]
        for config, (mode, bits, level) in enumerate(CONFIGS):
            decoder, previous = Decoder(scale, zero), np.zeros(N, '<f4')
            for seq, raw in enumerate(frames):
                delta = mode >= 3 and seq % 30 != 0
                state, work, indices = np.empty(N, '<f4'), np.empty(N, '<f4'), np.empty(N, np.int8)
                radius = self.lib.encode(raw.ctypes.data, previous.ctypes.data, state.ctypes.data,
                    indices.ctypes.data, work.ctypes.data, config, delta, scale, zero)
                expected, expected_state = packet(raw.tobytes(), config, seq, previous, scale=scale, zero=zero)
                self.assertEqual(state.tobytes(), expected_state.tobytes(), (config, seq))
                self.assertEqual(float_bits(radius), HEADER.unpack_from(expected)[12])
                restored = decoder.decode(expected)
                self.assertEqual(restored['state'].tobytes(), state.tobytes())
                q = np.empty(N, np.int8)
                self.lib.requant(state.ctypes.data, q.ctypes.data, scale, zero)
                self.assertEqual(q.tobytes(), requantize(state, scale, zero))
                if mode >= 2:
                    self.assertEqual(zlib.decompress(expected[80:]), indices.tobytes())
                previous = state

    def test_deadzone_boundaries_and_rounding(self):
        # Fill with R=1 so the P99 range is fixed; b=4 gives step .125.
        values = np.ones(N, '<f4')
        values[:8] = [0, .0625, -.0625, .093749, .09375, -.09375, .1875, -.1875]
        q, radius = quantize(values, 4, True)
        self.assertEqual(float(radius), 1.)
        self.assertEqual(list(q[:8]), [0, 0, 0, 0, 1, -1, 2, -2])
        q, radius = quantize(np.zeros(N, '<f4'), 8, True)
        self.assertEqual(float(radius), 0.)
        self.assertFalse(q.any())

    def test_reject_corruption_missing_reference_and_transactional_state(self):
        decoder = Decoder(.06843240559101105, -20)
        first, state = packet(bytes(N), 9, 0)
        following, _ = packet(bytes(N), 9, 1, state)
        with self.assertRaises(ValueError): decoder.decode(following)
        decoder.decode(first)
        damaged = bytearray(following); damaged[-1] ^= 1
        with self.assertRaises(ValueError): decoder.decode(damaged)
        self.assertEqual(decoder.streams[(7, 1)].seq, 0)
        decoder.decode(following)
        with self.assertRaises(ValueError): decoder.decode(following)
        reset, _ = packet(bytes(N), 9, 0, session=2)
        decoder.decode(reset)
        self.assertEqual(list(decoder.streams), [(7, 2)])

    def test_bounded_streams_and_header_and_payload(self):
        decoder = Decoder(.06843240559101105, -20)
        first, _ = packet(bytes(N), 0, 0)
        for payload in (first[:70], first+b'x', first[:80]+b'x'*8193):
            with self.assertRaises(ValueError): decoder.decode(payload)
        fields = list(HEADER.unpack_from(first)); fields[12] = 0x7fc00000
        header = HEADER.pack(*fields); fields[-1] = crc(header[:76])
        with self.assertRaises(ValueError):decoder.decode(HEADER.pack(*fields)+first[80:])

    def test_zlib_bombs_truncation_concatenation_and_unknown_fields(self):
        body,_=packet(bytes(N),1,0)
        decoder=Decoder(.06843240559101105,-20)
        cases=[change_packet(body,payload=body[80:]+body[80:]),
               change_packet(body,payload=body[80:-1]),
               change_packet(body,payload=zlib.compress(bytes(N+1))),
               change_packet(body,{4:99}),change_packet(body,{10:4}),
               change_packet(body,{3:1,6:1,7:1})]
        for wire in cases:
            with self.assertRaises(ValueError):decoder.decode(wire)
        self.assertFalse(decoder.streams)

    def test_diagnostic_does_not_change_reference_and_wrong_ref_is_rejected(self):
        decoder=Decoder(.06843240559101105,-20)
        first,state=packet(bytes(N),9,0)
        decoder.decode(first)
        raw,_=packet(bytes([127])*N,0,0)
        diagnostic=change_packet(raw,{4:9,9:2,18:1})
        decoder.decode(diagnostic)
        self.assertEqual(decoder.streams[(7,1)].state.tobytes(),state.tobytes())
        next_frame,_=packet(bytes(N),9,1,state)
        with self.assertRaises(ValueError):decoder.decode(change_packet(next_frame,{6:17}))
        decoder.decode(next_frame)

    def test_device_isolation_and_bounded_sessions(self):
        decoder=Decoder(.06843240559101105,-20)
        first,_=packet(bytes(N),0,0)
        for device in range(4):decoder.decode(change_packet(first,{2:device}))
        with self.assertRaises(ValueError):decoder.decode(change_packet(first,{2:4}))
        self.assertEqual(len(decoder.streams),4)
        decoder.decode(change_packet(first,{2:0,3:2}))
        self.assertEqual(len(decoder.streams),4)
        self.assertIn((0,2),decoder.streams)

    def test_real_hardware_activation_vectors(self):
        folder = HERE.parent/'esp32_int8_compression_benchmark/results/2026-10-28-run1/server'
        paths = sorted(folder.glob('*raw*.request.bin'))[:16]
        self.assertTrue(paths, 'Archived hardware vectors must exist')
        for config in range(len(CONFIGS)):
            decoder, previous = Decoder(.06843240559101105, -20), None
            for seq, path in enumerate(paths):
                raw = path.read_bytes()[32:]
                self.assertEqual(len(raw), N)
                wire, previous = packet(raw, config, seq, previous)
                decoder.decode(wire)

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


if __name__ == '__main__':
    unittest.main()
