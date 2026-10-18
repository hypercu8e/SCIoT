"""Loss/error bounds, closed-loop references, and independent wire decoding."""

import unittest
import zlib

import numpy as np

from compare import HEADER
from compare_lossy import cell_labels, output_stats
from lossy_codec import (
    DELTA_COMPRESSED, QUANT_LIMIT, Decoder, Encoder, Session, quantize, reconstruct,
)


class LossyTests(unittest.TestCase):
    def test_methods_have_identical_reconstructions_across_refreshes(self):
        rng = np.random.default_rng(67)
        frames = rng.normal(size=(15, 12, 12, 8)).astype(np.float32)
        frames[1] = frames[0]
        for step in (0.0001, 0.01, 0.1, 1.0):
            results = []
            for method in ("independent", "temporal"):
                session = Session(frames.shape[1:], step, method, 4)
                decoder = Decoder(Session.from_packet(session.to_packet()))
                encoder = Encoder(session)
                restored_frames = []
                for frame in frames:
                    packet, info = encoder.encode(frame)
                    raw, restored = decoder.decode(packet)
                    expected = quantize(frame, step)
                    self.assertEqual(raw, expected.tobytes())
                    if info["scheduled_refresh"]:
                        self.assertNotEqual(info["kind"], DELTA_COMPRESSED)
                    tolerance = step / 2 + np.finfo(np.float32).eps * np.abs(restored)
                    self.assertTrue(np.all(np.abs(frame.astype(float) - restored) <= tolerance))
                    restored_frames.append(restored)
                results.append(np.asarray(restored_frames).tobytes())
            self.assertEqual(*results)

    def test_no_drift_when_small_changes_accumulate(self):
        # Comparing to the previous ORIGINAL would suppress every .03 change.
        # The shared reconstructed reference must eventually advance instead.
        session = Session((1024,), 0.1, "temporal", 50)
        encoder, decoder = Encoder(session), Decoder(session)
        for value in np.arange(30) * 0.03:
            frame = np.full(1024, value, dtype=np.float32)
            raw, restored = decoder.decode(encoder.encode(frame)[0])
            self.assertEqual(encoder.reference, decoder.reference)
            self.assertEqual(raw, quantize(frame, 0.1).tobytes())
            self.assertLessEqual(float(np.max(np.abs(frame - restored))), 0.050001)
        self.assertGreater(float(restored[0]), 0.8)

    def test_lost_delta_requires_refresh_and_recovers(self):
        session = Session((1024,), 0.1, "temporal", 4)
        encoder, decoder = Encoder(session), Decoder(session)
        frame = np.arange(1024, dtype=np.float32)
        packets = [encoder.encode(frame)[0] for _ in range(5)]
        self.assertEqual(HEADER.unpack_from(packets[2])[2], DELTA_COMPRESSED)
        decoder.decode(packets[0])
        with self.assertRaisesRegex(ValueError, "Missing reference"):
            decoder.decode(packets[2])
        self.assertEqual(decoder.decode(packets[4])[0], quantize(frame, 0.1).tobytes())

    def test_corruption_rejection_preserves_reference(self):
        session = Session((1024,), 0.1, "temporal", 5)
        encoder, decoder = Encoder(session), Decoder(session)
        frame = np.arange(1024, dtype=np.float32)
        decoder.decode(encoder.encode(frame)[0])
        packet, _ = encoder.encode(frame)
        fields = list(HEADER.unpack_from(packet))
        fields[-1] ^= 1
        corrupt = HEADER.pack(*fields) + packet[HEADER.size:]
        old_state = decoder.reference, decoder.sequence
        with self.assertRaisesRegex(ValueError, "checksum"):
            decoder.decode(corrupt)
        self.assertEqual(old_state, (decoder.reference, decoder.sequence))
        decoder.decode(packet)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            decoder.decode(packet)
        with self.assertRaisesRegex(ValueError, "length"):
            Decoder(session).decode(packet[:-1])

    def test_overflow_nonfinite_and_invalid_steps_are_rejected(self):
        for step in (0, -1, np.inf, np.nan):
            with self.assertRaises(ValueError):
                quantize(np.zeros(1, np.float32), step)
        for value in (np.nan, np.inf, np.finfo(np.float32).max):
            with self.assertRaises(ValueError):
                quantize(np.array([value], np.float32), 0.01)
        extremes = np.array([-QUANT_LIMIT, QUANT_LIMIT], dtype="<i4")
        self.assertTrue(np.isfinite(reconstruct(extremes, 0.1)).all())

    def test_session_truncation_and_oversized_decompression_are_rejected(self):
        session = Session((4,), 0.1, "independent", 5)
        with self.assertRaises(ValueError):
            Session.from_packet(session.to_packet()[:-1])
        payload = zlib.compress(bytes(100000))
        packet = HEADER.pack(b"AQF1", 1, 1, 0, 0, 0xFFFFFFFF, len(payload), 0) + payload
        with self.assertRaises(ValueError):
            Decoder(session).decode(packet)

    def test_no_foreground_is_not_reported_as_perfect_foreground_iou(self):
        background = np.array([[[[0.98, 0.01, 0.01]]]], dtype=np.float32)
        metrics = output_stats(background, background, [0.5])["thresholds"]["0.5"]
        self.assertEqual(metrics["agreement_percent"], 100)
        self.assertEqual(metrics["reference_foreground_cells"], 0)
        self.assertIsNone(metrics["foreground_label_cell_iou"])

    def test_foreground_thresholds_and_lost_introduced_class_changes(self):
        before = np.array([[[[0.6, 0.3, 0.1], [0.1, 0.8, 0.1], [0.9, 0.05, 0.05]]]], np.float32)
        after = np.array([[[[0.6, 0.1, 0.3], [0.9, 0.05, 0.05], [0.1, 0.8, 0.1]]]], np.float32)
        self.assertEqual(cell_labels(before, 0.25).tolist(), [[[1, 1, 0]]])
        metrics = output_stats(before, after, [0.25])["thresholds"]["0.25"]
        self.assertEqual(metrics["changed_cells"], 3)
        self.assertEqual(metrics["lost_foreground_cells"], 1)
        self.assertEqual(metrics["introduced_foreground_cells"], 1)
        self.assertEqual(metrics["foreground_class_changed_cells"], 1)

    def test_extreme_integer_transition_does_not_wrap(self):
        # Powers of two are exactly representable in float32 near the safe limit.
        magnitude = 2**29
        session = Session((1024,), 1.0, "temporal", 10)
        encoder, decoder = Encoder(session), Decoder(session)
        base = np.arange(1024, dtype=np.float32) * 64 - magnitude
        for index, offset in enumerate((0, 2 * magnitude, 0)):
            frame = (base + offset).astype(np.float32)
            packet, info = encoder.encode(frame)
            if index:
                self.assertEqual(info["kind"], DELTA_COMPRESSED)
            _, restored = decoder.decode(packet)
            np.testing.assert_array_equal(restored, frame)


if __name__ == "__main__":
    unittest.main()
