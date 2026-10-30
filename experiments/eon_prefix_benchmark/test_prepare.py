"""Contract and corruption checks for the EON preparation (no network)."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from prepare import SOURCE, checked_file, quantize, sha, validate_boundary


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.models = json.loads((SOURCE / "manifest.json").read_text())["models"]["int8"]

    def test_frozen_models_and_boundary(self):
        for name in ("prefix", "suffix"):
            checked_file(SOURCE / f"int8-{name}.tflite", self.models[name]["sha256"])
        validate_boundary(self.models["prefix"], self.models["suffix"])

    def test_scale_change_is_rejected(self):
        suffix = copy.deepcopy(self.models["suffix"])
        suffix["input"]["scales"][0] *= 2
        with self.assertRaisesRegex(ValueError, "boundary"):
            validate_boundary(self.models["prefix"], suffix)

    def test_wrong_shape_is_rejected_even_if_boundary_matches(self):
        prefix, suffix = copy.deepcopy(self.models["prefix"]), copy.deepcopy(self.models["suffix"])
        prefix["output"]["shape"] = suffix["input"]["shape"] = [1, 12, 12, 32]
        with self.assertRaisesRegex(ValueError, "Unexpected"):
            validate_boundary(prefix, suffix)

    def test_corrupt_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.tflite"
            path.write_bytes(b"broken")
            with self.assertRaisesRegex(ValueError, "Hash mismatch"):
                checked_file(path, sha(b"original"))

    def test_quantization_ties_clipping_and_zero_point(self):
        values = np.array([-1000, -1.25, -.75, -.25, .25, .75, 1.25, 1000])
        np.testing.assert_array_equal(quantize(values, {"scales": [.5], "zero_points": [0]}),
                                      [-128, -2, -2, 0, 0, 2, 2, 127])
        np.testing.assert_array_equal(quantize(np.array([0, 1]), {"scales": [.5], "zero_points": [-3]}),
                                      [-3, -1])


if __name__ == "__main__":
    unittest.main()
