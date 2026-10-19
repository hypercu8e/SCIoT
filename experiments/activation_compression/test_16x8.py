"""Check that INT16 mapping preserves its wider range without wrapping."""

import unittest

import numpy as np
from check_16x8 import prepare, restore


def detail(scale=.125, zero=0, dtype=np.int16):
    return {"dtype": dtype, "quantization_parameters": {
        "scales": np.array([scale]), "zero_points": np.array([zero])}}


class Int16Tests(unittest.TestCase):
    def test_values_above_int8_range_and_negative_values_roundtrip(self):
        values = np.array([-512., -.25, 0., .25, 512.], np.float32)
        encoded, clipped = prepare(values, detail())
        self.assertEqual(encoded.dtype, np.int16)
        np.testing.assert_array_equal(encoded, [-4096, -2, 0, 2, 4096])
        np.testing.assert_array_equal(restore(encoded, detail()), values)
        self.assertEqual(clipped, 0)

    def test_clipping_uses_int16_limits_and_counts_only_out_of_range(self):
        encoded, clipped = prepare(np.array([-40000., -32768., 32767., 40000.]), detail(1.))
        np.testing.assert_array_equal(encoded, [-32768, -32768, 32767, 32767])
        self.assertEqual(clipped, 2)

    def test_int8_mapping_remains_compatible_with_previous_experiment(self):
        from check_int8 import dequantize, prepare_input

        values = np.array([-100., -.25, 0., .25, 100.], np.float32)
        metadata = detail(.125, -7, np.int8)
        expected, clipped = prepare_input(values, metadata)
        actual, new_clipped = prepare(values, metadata)
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(restore(actual, metadata), dequantize(expected, metadata))
        self.assertEqual(new_clipped, clipped)

    def test_nonfinite_and_invalid_scale_are_rejected(self):
        for value in (np.nan, np.inf):
            with self.assertRaises(ValueError):
                prepare(np.array([value]), detail())
        for scale in (0., -1., np.nan):
            with self.assertRaises(ValueError):
                prepare(np.zeros(1), detail(scale))


if __name__ == "__main__":
    unittest.main()
