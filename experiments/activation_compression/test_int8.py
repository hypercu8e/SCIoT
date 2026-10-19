"""Numerical checks for INT8 input mapping and calibration/evaluation isolation."""

import unittest

import numpy as np
from check_int8 import dequantize, prepare_input, split_indices


def detail(scale=.25, zero=-7):
    return {"dtype": np.int8, "quantization_parameters": {
        "scales": np.array([scale]), "zero_points": np.array([zero])}}


class Int8Tests(unittest.TestCase):
    def test_scale_zero_point_and_clipping_do_not_wrap(self):
        values = np.array([-100., -0.5, 0., 0.5, 100.], np.float32)
        quantized, clipped = prepare_input(values, detail())
        np.testing.assert_array_equal(quantized, [-128, -9, -7, -5, 127])
        self.assertEqual(clipped, 2)
        restored = dequantize(quantized, detail())
        np.testing.assert_array_equal(restored[1:4], values[1:4])
        self.assertEqual(restored.dtype, np.float32)

    def test_endpoint_hits_are_not_counted_as_clipping(self):
        quantized, clipped = prepare_input(np.array([-128., 127.], np.float32), detail(1., 0))
        np.testing.assert_array_equal(quantized, [-128, 127])
        self.assertEqual(clipped, 0)

    def test_invalid_input_or_quantization_is_rejected(self):
        for scale in (0., -1., np.inf, np.nan):
            with self.assertRaises(ValueError):
                prepare_input(np.zeros(1, np.float32), detail(scale))
        with self.assertRaises(ValueError):
            prepare_input(np.array([np.nan], np.float32), detail())
        with self.assertRaises(ValueError):
            prepare_input(np.zeros(1, np.float32), {"dtype": np.uint8})
        metadata = detail()
        metadata["quantization_parameters"]["scales"] = np.array([1., 2.])
        with self.assertRaises(ValueError):
            prepare_input(np.zeros(1, np.float32), metadata)

    def test_frame_partitions_are_disjoint_and_cover_the_sequence(self):
        calibration, evaluation = split_indices(146, 48)
        self.assertEqual(set(calibration) & set(evaluation), set())
        np.testing.assert_array_equal(np.concatenate([calibration, evaluation]), np.arange(146))
        for count in (0, 146, 147):
            with self.assertRaises(ValueError):
                split_indices(146, count)


if __name__ == "__main__":
    unittest.main()
