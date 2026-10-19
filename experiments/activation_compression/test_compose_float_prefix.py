"""Numerical and rejection checks for the restricted float layer composer."""
import unittest

import numpy as np
import tensorflow as tf
from tensorflow.lite.python import schema_py_generated as schema

from compose_float_prefix import compose_prefix
from split_tflite import pack, unpack


def layer(add=False, width=2):
    model = schema.ModelT()
    model.version = 3
    code = schema.OperatorCodeT()
    code.builtinCode = code.deprecatedBuiltinCode = (schema.BuiltinOperator.ADD if add else schema.BuiltinOperator.RELU6)
    code.version = 1
    model.operatorCodes = [code]
    graph = schema.SubGraphT()
    graph.inputs = np.array([0, 1] if add else [0], np.int32)
    graph.outputs = np.array([2 if add else 1], np.int32)
    graph.tensors = []
    for i in range(3 if add else 2):
        tensor = schema.TensorT()
        tensor.name = str(i).encode()
        tensor.shape = np.array([1, width], np.int32)
        tensor.type = schema.TensorType.FLOAT32
        graph.tensors.append(tensor)
    op = schema.OperatorT()
    op.inputs, op.outputs = graph.inputs, graph.outputs
    if add:
        op.builtinOptionsType = schema.BuiltinOptions.AddOptions
        op.builtinOptions = schema.AddOptionsT()
    graph.operators = [op]
    model.subgraphs, model.buffers = [graph], [schema.BufferT()]
    return pack(model)


def run(content, values):
    interpreter = tf.lite.Interpreter(model_content=content, num_threads=1,
                                     experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
    interpreter.allocate_tensors()
    interpreter.set_tensor(interpreter.get_input_details()[0]["index"], np.array([values], np.float32))
    interpreter.invoke()
    return interpreter.get_tensor(interpreter.get_output_details()[0]["index"])[0]


class ComposeTests(unittest.TestCase):
    def test_chain_numerical_output(self):
        content = compose_prefix([layer(), layer()], {})
        np.testing.assert_array_equal(run(content, [-2, 8]), [0, 6])
        self.assertEqual(len(unpack(content).subgraphs[0].operators), 2)

    def test_residual_preserves_earlier_output(self):
        content = compose_prefix([layer(), layer(), layer(add=True)], {2: 0})
        np.testing.assert_array_equal(run(content, [2, 8]), [4, 12])
        graph = unpack(content).subgraphs[0]
        self.assertEqual(graph.operators[2].inputs[1], graph.operators[0].outputs[0])

    def test_nonzero_empty_buffer_is_a_runtime_tensor(self):
        model = unpack(layer())
        model.buffers.append(schema.BufferT())
        model.subgraphs[0].tensors[0].buffer = 1
        content = compose_prefix([layer(), pack(model)], {})
        np.testing.assert_array_equal(run(content, [2, 8]), [2, 6])

    def test_incompatible_connections_and_missing_residual(self):
        for contents, sources in (([layer(), layer(width=3)], {}),
                                  ([layer(), layer(add=True)], {}),
                                  ([layer(), layer(add=True)], {1: 1})):
            with self.assertRaises(ValueError):
                compose_prefix(contents, sources)
        wrong = unpack(layer())
        wrong.subgraphs[0].tensors[0].type = schema.TensorType.INT8
        with self.assertRaisesRegex(ValueError, "shape/type"):
            compose_prefix([layer(), pack(wrong)], {})

    def test_unsupported_graphs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Empty"):
            compose_prefix([], {})
        for change in ("variable", "schema", "custom", "unprovided"):
            model = unpack(layer())
            if change == "variable":
                model.subgraphs[0].tensors[0].isVariable = True
            elif change == "schema":
                model.version = 99
            elif change == "custom":
                model.operatorCodes[0].builtinCode = schema.BuiltinOperator.CUSTOM
            else:
                model.subgraphs[0].operators[0].inputs = np.array([1], np.int32)
            with self.assertRaises(ValueError):
                compose_prefix([pack(model)], {})


if __name__ == "__main__":
    unittest.main()
