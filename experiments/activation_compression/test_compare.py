"""Check reversible codecs and reference recovery independently of video results."""

import unittest

import numpy as np
from compare import (
    FULL_ZLIB,
    HEADER,
    METHODS,
    RAW,
    XOR,
    Decoder,
    Encoder,
    shuffle,
    unshuffle,
)


class CodecTests(unittest.TestCase):
    def test_all_methods_preserve_float_bits_across_refreshes(self):
        rng = np.random.default_rng(431)
        frames = rng.normal(size=(8, 12, 12, 8)).astype("<f4")
        frames[1] = frames[0]
        frames[2, 0, 0, 0] = -0.0
        frames[3, 0, 0, 0] = np.finfo(np.float32).max
        frames[4, 0, 0, 0] = np.finfo(np.float32).tiny
        for method in METHODS:
            with self.subTest(method=method):
                encoder = Encoder(method, refresh_frames=3)
                decoder = Decoder(frames[0].nbytes)
                for frame in frames:
                    raw = frame.tobytes()
                    packet, info = encoder.encode(raw)
                    self.assertEqual(decoder.decode(packet), raw)
                    if info["refresh"]:
                        self.assertNotIn(info["kind"], (2, 3, 5))

    def test_shuffle_preserves_every_bit_pattern(self):
        words = np.array([0, 0x80000000, 0x7FC00001, 0x7F800000, 0xFF800000, 0x12345678], dtype="<u4")
        self.assertEqual(unshuffle(shuffle(words.tobytes())), words.tobytes())

    def test_float64_delta_falls_back_when_signed_zero_would_be_lost(self):
        previous = np.arange(1024, dtype="<f4")
        current = previous.copy()
        current[0] = -0.0
        encoder = Encoder("delta64_zlib", refresh_frames=25)
        decoder = Decoder(previous.nbytes)
        first, _ = encoder.encode(previous.tobytes())
        decoder.decode(first)
        second, info = encoder.encode(current.tobytes())
        self.assertFalse(info["delta_candidate_exact"])
        self.assertIn(info["kind"], (RAW, FULL_ZLIB))
        self.assertEqual(decoder.decode(second), current.tobytes())

    def test_missing_delta_is_rejected_until_complete_refresh(self):
        raw = np.arange(1024, dtype="<f4").tobytes()
        encoder = Encoder("xor_zlib", refresh_frames=3)
        packets = [encoder.encode(raw)[0] for _ in range(4)]
        self.assertEqual(HEADER.unpack_from(packets[2])[2], XOR)
        decoder = Decoder(len(raw))
        decoder.decode(packets[0])
        with self.assertRaisesRegex(ValueError, "Missing reference"):
            decoder.decode(packets[2])
        self.assertEqual(decoder.decode(packets[3]), raw)

    def test_corrupted_tensor_is_rejected(self):
        raw = np.arange(32, dtype="<f4").tobytes()
        packet, _ = Encoder("raw", refresh_frames=25).encode(raw)
        corrupted = packet[:-1] + bytes([packet[-1] ^ 1])
        with self.assertRaisesRegex(ValueError, "checksum"):
            Decoder(len(raw)).decode(corrupted)

    def test_duplicate_and_truncated_packets_are_rejected(self):
        raw = np.arange(32, dtype="<f4").tobytes()
        packet, _ = Encoder("raw", refresh_frames=25).encode(raw)
        decoder = Decoder(len(raw))
        decoder.decode(packet)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            decoder.decode(packet)
        with self.assertRaises(ValueError):
            Decoder(len(raw)).decode(packet[:-1])


if __name__ == "__main__":
    unittest.main()
