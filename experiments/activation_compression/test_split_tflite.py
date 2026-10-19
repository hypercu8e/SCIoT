"""Guard against losing cross-boundary branches or changing quantized constants."""

import unittest
from pathlib import Path

import numpy as np

from split_tflite import pack, split_single_boundary, unpack

MODEL = Path(__file__).with_name("int8_2026-10-18") / "fomo_int8.tflite"
BOUNDARY = "model_1/block_2_add/add"


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.content = MODEL.read_bytes()

    def test_cut_keeps_original_constants_and_quantization(self):
        original = unpack(self.content)
        originals = {t.name: t for t in original.subgraphs[0].tensors}
        for content in split_single_boundary(self.content, BOUNDARY):
            part = unpack(content)
            self.assertLess(len(content), len(self.content))
            for tensor in part.subgraphs[0].tensors:
                source = originals[tensor.name]
                np.testing.assert_array_equal(tensor.shape, source.shape)
                self.assertEqual(tensor.type, source.type)
                if source.quantization is not None:
                    np.testing.assert_array_equal(tensor.quantization.scale, source.quantization.scale)
                    np.testing.assert_array_equal(tensor.quantization.zeroPoint, source.quantization.zeroPoint)
                np.testing.assert_array_equal(part.buffers[tensor.buffer].data,
                                              original.buffers[source.buffer].data)

    def test_crossing_residual_branch_is_rejected(self):
        model = unpack(self.content)
        graph = model.subgraphs[0]
        boundary = next(i for i, t in enumerate(graph.tensors) if t.name.decode() == BOUNDARY)
        producer = next(i for i, op in enumerate(graph.operators) if boundary in op.outputs)
        another_live_tensor = graph.operators[producer - 1].outputs[0]
        graph.operators[producer + 1].inputs = np.append(graph.operators[producer + 1].inputs, another_live_tensor)
        with self.assertRaisesRegex(ValueError, "boundary tensors"):
            split_single_boundary(pack(model), BOUNDARY)

    def test_unknown_boundary_final_output_and_variables_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "exactly once"):
            split_single_boundary(self.content, "missing")
        model = unpack(self.content)
        graph = model.subgraphs[0]
        with self.assertRaisesRegex(ValueError, "nonempty suffix"):
            split_single_boundary(self.content, graph.tensors[graph.outputs[0]].name.decode())
        graph.tensors[0].isVariable = True
        with self.assertRaisesRegex(ValueError, "Variables"):
            split_single_boundary(pack(model), BOUNDARY)


if __name__ == "__main__":
    unittest.main()

