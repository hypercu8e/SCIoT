"""Cut a single-subgraph TFLite model without re-converting its quantization.

Conservative experimental utility: only a single live boundary tensor is allowed.
Operator order, weights, quantization and builtin options are preserved. This is
not a general graph partitioner (control flow, variables and custom ops rejected).
"""

import copy

import flatbuffers
import numpy as np
from tensorflow.lite.python import schema_py_generated as schema


def unpack(content):
    if content[4:8] != b"TFL3":
        raise ValueError("Expected a TFLite flatbuffer")
    return schema.ModelT.InitFromObj(schema.Model.GetRootAsModel(content, 0))


def pack(model):
    builder = flatbuffers.Builder(0)
    root = model.Pack(builder)
    builder.Finish(root, file_identifier=b"TFL3")
    return bytes(builder.Output())


def indices(values):
    return [] if values is None else [int(i) for i in values if i >= 0]


def partition(model, operators, inputs, outputs, name):
    """Remap tensors, buffers and opcodes, dropping constants from the other half."""
    result = copy.deepcopy(model)
    graph = result.subgraphs[0]
    chosen = [graph.operators[i] for i in operators]
    used = set(inputs) | set(outputs)
    for op in chosen:
        used.update(indices(op.inputs) + indices(op.outputs) + indices(op.intermediates))
    tensor_ids = sorted(used)
    tensor_map = {old: new for new, old in enumerate(tensor_ids)}
    graph.tensors = [graph.tensors[i] for i in tensor_ids]
    # Buffer zero must remain the empty sentinel for runtime tensors.
    buffers = [0] + sorted({int(t.buffer) for t in graph.tensors} - {0})
    buffer_map = {old: new for new, old in enumerate(buffers)}
    result.buffers = [result.buffers[i] for i in buffers]
    for tensor in graph.tensors:
        tensor.buffer = buffer_map[int(tensor.buffer)]
    codes = sorted({int(op.opcodeIndex) for op in chosen})
    code_map = {old: new for new, old in enumerate(codes)}
    result.operatorCodes = [result.operatorCodes[i] for i in codes]
    for op in chosen:
        op.opcodeIndex = code_map[int(op.opcodeIndex)]
        for field in ("inputs", "outputs", "intermediates"):
            values = getattr(op, field)
            if values is not None:
                setattr(op, field, np.array([tensor_map[int(i)] if i >= 0 else -1
                                            for i in values], dtype=np.int32))
    graph.operators = chosen
    graph.inputs = np.array([tensor_map[i] for i in inputs], dtype=np.int32)
    graph.outputs = np.array([tensor_map[i] for i in outputs], dtype=np.int32)
    graph.name = name.encode()
    # Original signatures and metadata refer to original graph/tensor/buffer IDs.
    result.signatureDefs = None
    result.metadata = None
    result.metadataBuffer = None
    result.description = b"SCIoT experimental cut; quantization and kernels unchanged"
    return pack(result)


def split_single_boundary(content, boundary_name):
    model = unpack(content)
    if len(model.subgraphs) != 1:
        raise ValueError("Only one subgraph is supported")
    graph = model.subgraphs[0]
    if len(graph.inputs) != 1 or len(graph.outputs) != 1:
        raise ValueError("Expected one model input and output")
    if any(t.isVariable or t.sparsity is not None for t in graph.tensors):
        raise ValueError("Variables and sparse tensors are not supported")
    forbidden = {schema.BuiltinOperator.CUSTOM, schema.BuiltinOperator.IF,
                 schema.BuiltinOperator.WHILE, schema.BuiltinOperator.CALL_ONCE}
    for code in model.operatorCodes:
        if max(code.builtinCode, code.deprecatedBuiltinCode) in forbidden:
            raise ValueError("Custom and control-flow operators are not supported")
    candidates = [i for i, t in enumerate(graph.tensors)
                  if t.name.decode() == boundary_name]
    if len(candidates) != 1:
        raise ValueError("Boundary tensor name must match exactly once")
    boundary = candidates[0]
    producers = [i for i, op in enumerate(graph.operators) if boundary in indices(op.outputs)]
    if len(producers) != 1 or producers[0] == len(graph.operators) - 1:
        raise ValueError("Boundary must have one producer and a nonempty suffix")
    cut = producers[0] + 1
    prefix_ops, suffix_ops = range(cut), range(cut, len(graph.operators))
    available = set(indices(graph.inputs))
    for op in graph.operators[:cut]:
        available.update(indices(op.outputs))
    required = set(indices(graph.outputs))
    for op in graph.operators[cut:]:
        required.update(indices(op.inputs))
    frontier = available & required
    if frontier != {boundary}:
        names = [graph.tensors[i].name.decode() for i in sorted(frontier)]
        raise ValueError(f"Split needs multiple/different boundary tensors: {names}")
    # Ensure neither partition has any other unprovided runtime inputs.
    for ops, inputs in ((prefix_ops, indices(graph.inputs)), (suffix_ops, [boundary])):
        known = set(inputs)
        known.update(i for i, t in enumerate(graph.tensors)
                     if model.buffers[t.buffer].data is not None
                     and len(model.buffers[t.buffer].data))
        for index in ops:
            op = graph.operators[index]
            if not set(indices(op.inputs)) <= known:
                raise ValueError("Unprovided runtime input or non-topological graph")
            known.update(indices(op.outputs))
    return (
        partition(model, prefix_ops, indices(graph.inputs), [boundary], "prefix"),
        partition(model, suffix_ops, [boundary], indices(graph.outputs), "suffix"),
    )
