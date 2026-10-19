"""Join the deployed float layer binaries without converting or optimizing them.

Specific to straight chains with explicitly supplied residual edges. Preserves
operator order/options/versions and constant bytes; never deduplicates constants.
"""

import copy

import numpy as np
from tensorflow.lite.python import schema_py_generated as schema

from split_tflite import indices, pack, unpack


def compose_prefix(contents, residual_sources):
    if not contents:
        raise ValueError("Empty chain")
    result = schema.ModelT()
    result.version = 3
    result.description = b"SCIoT float prefix: unchanged deployed operators"
    result.buffers = [schema.BufferT()]
    result.operatorCodes = []
    graph = schema.SubGraphT()
    graph.name = b"prefix"
    graph.tensors, graph.operators = [], []
    outputs = []
    forbidden = {schema.BuiltinOperator.CUSTOM, schema.BuiltinOperator.IF,
                 schema.BuiltinOperator.WHILE, schema.BuiltinOperator.CALL_ONCE}
    for layer, content in enumerate(contents):
        model = unpack(content)
        if model.version != 3 or len(model.subgraphs) != 1:
            raise ValueError("Unsupported schema or subgraphs")
        src = model.subgraphs[0]
        if len(src.outputs) != 1 or len(src.inputs) != (2 if layer in residual_sources else 1):
            raise ValueError("Unexpected input/output count")
        if any(t.isVariable or t.sparsity is not None for t in src.tensors):
            raise ValueError("Variables and sparse tensors are unsupported")
        if any(max(c.builtinCode, c.deprecatedBuiltinCode) in forbidden for c in model.operatorCodes):
            raise ValueError("Custom and control-flow operators are unsupported")
        buffer_map = {0: 0}
        for old in range(1, len(model.buffers)):
            buffer_map[old] = len(result.buffers)
            result.buffers.append(copy.deepcopy(model.buffers[old]))
        mapping = {}
        if layer:
            mapping[int(src.inputs[0])] = outputs[-1]
        if layer in residual_sources:
            previous = residual_sources[layer]
            if not 0 <= previous < layer:
                raise ValueError("Residual source must precede its consumer")
            mapping[int(src.inputs[1])] = outputs[previous]
        for old, tensor in enumerate(src.tensors):
            if old in mapping:
                other = graph.tensors[mapping[old]]
                if (tensor.type != schema.TensorType.FLOAT32 or other.type != tensor.type
                        or not np.array_equal(tensor.shape, other.shape)
                        or (model.buffers[tensor.buffer].data is not None
                            and len(model.buffers[tensor.buffer].data))):
                    raise ValueError("Incompatible shape/type or constant at connection")
            else:
                new = copy.deepcopy(tensor)
                new.name = f"layer_{layer}/".encode() + (tensor.name or b"unnamed")
                new.buffer = buffer_map[int(tensor.buffer)]
                mapping[old] = len(graph.tensors)
                graph.tensors.append(new)
        if not layer:
            graph.inputs = np.array([mapping[int(src.inputs[0])]], dtype=np.int32)
            if graph.tensors[graph.inputs[0]].type != schema.TensorType.FLOAT32:
                raise ValueError("Expected float32 chain input")
        if src.tensors[int(src.outputs[0])].type != schema.TensorType.FLOAT32:
            raise ValueError("Expected float32 chain output")
        offset = len(result.operatorCodes)
        result.operatorCodes.extend(copy.deepcopy(model.operatorCodes))
        known = set(indices(src.inputs)) | {i for i, t in enumerate(src.tensors)
                                           if model.buffers[t.buffer].data is not None
                                           and len(model.buffers[t.buffer].data)}
        for original in src.operators:
            if not set(indices(original.inputs)) <= known:
                raise ValueError("Unprovided input or non-topological graph")
            known.update(indices(original.outputs))
            op = copy.deepcopy(original)
            op.opcodeIndex += offset
            for field in ("inputs", "outputs", "intermediates"):
                values = getattr(op, field)
                if values is not None:
                    setattr(op, field, np.array([mapping[int(i)] if i >= 0 else -1
                                                for i in values], dtype=np.int32))
            graph.operators.append(op)
        if int(src.outputs[0]) not in known:
            raise ValueError("Unprovided graph output")
        outputs.append(mapping[int(src.outputs[0])])
    graph.outputs = np.array([outputs[-1]], dtype=np.int32)
    result.subgraphs = [graph]
    return pack(result)
