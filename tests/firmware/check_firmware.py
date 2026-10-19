"""Validate production firmware helpers on the host, with real TFLite Micro.

Creates only local build/test artifacts. Does not connect to hardware, brokers,
NTP or servers, and does not modify the server's stored profiles.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "src/server/models/test/test_model"
CLIENTS = ROOT / "src/client"
DEFAULT_RUNTIME = CLIENTS / "esp32-s3-eye-http/.pio/libdeps/esp32dev/TensorFlowLite_ESP32/src"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def failing_model(schema, version=3, int8_input=False, int8_output=False):
    import flatbuffers
    model = schema.ModelT()
    model.version = version
    code = schema.OperatorCodeT()
    code.builtinCode = code.deprecatedBuiltinCode = schema.BuiltinOperator.CUSTOM
    code.customCode = b"SCIoTFail"
    code.version = 1
    model.operatorCodes = [code]
    graph = schema.SubGraphT()
    graph.name = b"failure_test"
    graph.inputs, graph.outputs = np.array([0], np.int32), np.array([1], np.int32)
    graph.tensors = []
    for name in (b"input", b"output"):
        tensor = schema.TensorT()
        tensor.name = name
        int8 = int8_input if name == b"input" else int8_output
        tensor.shape = np.array([4 if int8 else 1], np.int32)
        tensor.type = schema.TensorType.INT8 if int8 else schema.TensorType.FLOAT32
        graph.tensors.append(tensor)
    op = schema.OperatorT()
    op.inputs, op.outputs = graph.inputs, graph.outputs
    graph.operators = [op]
    model.subgraphs, model.buffers = [graph], [schema.BufferT()]
    builder = flatbuffers.Builder(0)
    offset = model.Pack(builder)
    builder.Finish(offset, file_identifier=b"TFL3")
    return bytes(builder.Output())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "experiments/activation_compression/results/firmware-checks")
    args = parser.parse_args()
    runtime, out = args.runtime.resolve(), args.output_dir.resolve()
    if not (runtime / "tensorflow/lite/micro/micro_interpreter.cpp").exists():
        parser.error("Install the pinned TensorFlowLite_ESP32 dependency first; see tests/firmware/README.md")
    out.mkdir(parents=True, exist_ok=True)
    fixtures = out / "fixtures"
    fixtures.mkdir(exist_ok=True)
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
    import tensorflow as tf
    from tensorflow.lite.python import schema_py_generated as schema

    inputs = np.stack([np.zeros((96, 96, 3), np.float32),
                       np.random.default_rng(20261019).random((96, 96, 3), dtype=np.float32),
                       np.linspace(0, 1, 96 * 96 * 3, dtype=np.float32).reshape(96, 96, 3)])
    model = tf.keras.models.load_model(MODEL_DIR / "test_model.h5", compile=False)
    assert len(model.layers) == 60
    inspector = tf.keras.Model(model.input, [layer.output for layer in model.layers[1:]])
    keras_references = inspector(inputs, training=False)
    # Compare Micro to reference kernels executing the exact deployed binaries.
    # Comparing every intermediate to Keras instead conflates this refactor with
    # converter/float accumulation differences, amplified by standalone BN ops.
    runtimes = []
    for index in range(59):
        runtime_ref = tf.lite.Interpreter(
            model_path=str(MODEL_DIR / f"layers/tflite/submodel_{index}.tflite"), num_threads=1,
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_REF)
        runtime_ref.allocate_tensors()
        runtimes.append(runtime_ref)
    keras_errors, final_errors = [], []
    for sample, values in enumerate(inputs):
        values.tofile(fixtures / f"input_{sample}.bin")
        work, residual = values[None], None
        for index, runtime_ref in enumerate(runtimes):
            details = runtime_ref.get_input_details()
            runtime_ref.set_tensor(details[0]["index"], work)
            if len(details) == 2:
                assert residual is not None
                runtime_ref.set_tensor(details[1]["index"], residual)
            runtime_ref.invoke()
            work = runtime_ref.get_tensor(runtime_ref.get_output_details()[0]["index"])
            work.tofile(fixtures / f"reference_{sample}_{index}.bin")
            if index in (16, 34, 43):
                residual = work.copy()
            keras_errors.append(float(np.max(np.abs(work[0] - np.asarray(keras_references[index][sample])))))
        np.testing.assert_allclose(work[0], np.asarray(keras_references[-1][sample]), rtol=1e-5, atol=1e-5)
        final_errors.append(float(np.max(np.abs(work[0] - np.asarray(keras_references[-1][sample])))))
    (fixtures / "failed_invoke.tflite").write_bytes(failing_model(schema))
    (fixtures / "bad_schema.tflite").write_bytes(failing_model(schema, 99))
    (fixtures / "int8_input.tflite").write_bytes(failing_model(schema, int8_input=True))
    (fixtures / "int8_output.tflite").write_bytes(failing_model(schema, int8_output=True))

    counts, maximum, models = Counter(), 0, {}
    op_names = {value: name for name, value in vars(schema.BuiltinOperator).items() if isinstance(value, int)}
    for index in range(59):
        path = MODEL_DIR / f"layers/tflite/submodel_{index}.tflite"
        content = path.read_bytes()
        # Test exactly the models embedded in all three firmware clients.
        for transport in ("http", "mqtt", "websocket"):
            header = CLIENTS / f"esp32-s3-eye-{transport}/src/model_layers/layer_{index}.h"
            body = header.read_text().split("{", 1)[1].split("}", 1)[0]
            assert bytes(map(int, re.findall(r"\d+", body))) == content, str(header)
        binary = schema.Model.GetRootAsModel(content, 0)
        graph = binary.Subgraphs(0)
        assert graph.OutputsLength() == 1 and graph.InputsLength() in (1, 2)
        for i in range(graph.OutputsLength()):
            tensor = graph.Tensors(graph.Outputs(i))
            assert tensor.Type() == schema.TensorType.FLOAT32
            maximum = max(maximum, int(np.prod(tensor.ShapeAsNumpy())))
        for i in range(graph.InputsLength()):
            tensor = graph.Tensors(graph.Inputs(i))
            assert tensor.Type() == schema.TensorType.FLOAT32 and np.prod(tensor.ShapeAsNumpy()) <= 115248
        for i in range(graph.OperatorsLength()):
            code = binary.OperatorCodes(graph.Operators(i).OpcodeIndex())
            counts[op_names[max(code.BuiltinCode(), code.DeprecatedBuiltinCode())]] += 1
        models[path.name] = digest(path)
    assert maximum == 115248
    residual_sources = {}
    for index, layer in enumerate(model.layers[1:]):
        if isinstance(layer.input, (list, tuple)) and len(layer.input) == 2:
            sources = [model.layers.index(t._keras_history.layer) - 1 for t in layer.input]
            assert index - 1 in sources
            residual_sources[index] = next(i for i in sources if i != index - 1)
    assert residual_sources == {25: 16, 43: 34, 52: 43}

    build = out / "build"
    with (out / "native-build.log").open("w") as log:
        subprocess.run(["cmake", "-S", str(Path(__file__).parent), "-B", str(build),
                        f"-DTFLM_ROOT={runtime}", "-DCMAKE_BUILD_TYPE=Debug", "-DSCIOT_SANITIZERS=ON"],
                       check=True, stdout=log, stderr=log)
        subprocess.run(["cmake", "--build", str(build), "-j", "2"], check=True, stdout=log, stderr=log)
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run([str(build / "firmware_host"), str(MODEL_DIR / "layers/tflite"), str(fixtures)],
                            capture_output=True, text=True, env=env)
    (out / "native-stdout.txt").write_text(result.stdout)
    (out / "native-stderr.txt").write_text(result.stderr)
    result.check_returncode()
    native = json.loads(result.stdout.strip().splitlines()[-1])

    sys.path.insert(0, str(ROOT / "src"))
    from server.communication.request_handler import RequestHandler

    packets = {}
    for split in (0, 11, 25, 58):
        body = (fixtures / f"packet_{split}.bin").read_bytes()
        parsed = RequestHandler._from_raw("device_inference_result", body)
        values = 115248 if split in (11, 58) else 12
        expected_output = (np.arange(values) % 257 - 128) / 32.0
        expected_times = np.arange(1, split + 2) / 1024.0
        assert parsed.device_id == "device_01" and parsed.message_id == "a1b2"
        assert parsed.timestamp == 1234567890.125
        assert parsed.message_content["offloading_layer_index"] == split
        np.testing.assert_array_equal(parsed.message_content["layer_output"], expected_output)
        np.testing.assert_array_equal(parsed.message_content["layers_inference_time"], expected_times)
        assert len(body) == 33 + values * 4 + (split + 1) * 4
        packets[str(split)] = {"bytes": len(body), "parsed_by_unmodified_server": True}
    report = {
        "scope": "Native host execution of production helpers and real TensorFlowLite_ESP32; not ESP32 execution",
        "tensorflow": tf.__version__, "model_sha256": digest(MODEL_DIR / "test_model.h5"),
        "embedded_models_match_all_three_clients": True, "submodel_sha256": models,
        "operators": dict(counts), "max_output_values": maximum, "residual_sources": residual_sources,
        "message_capacity_before_bytes": 922253, "message_capacity_after_bytes": 461261,
        "reserved_buffer_reduction_bytes": 460992,
        "native_checks": native, "sanitizers": ["AddressSanitizer", "UndefinedBehaviorSanitizer"],
        "native_reference": "Desktop TFLite reference kernels, same 59 binaries, rtol=1e-5 atol=1e-5",
        "desktop_tflite_vs_keras": {"max_intermediate_absolute_error": max(keras_errors),
                                    "max_final_absolute_error": max(final_errors),
                                    "final_output_tolerance": {"rtol": 1e-5, "atol": 1e-5, "passed": True}},
        "server_packet_checks": packets, "hardware_verified": False,
        "source_sha256": {str(p.relative_to(ROOT)): digest(p) for p in
                          [CLIENTS / "common/inference_message.h", CLIENTS / "common/float_layer.h",
                           Path(__file__), Path(__file__).with_name("firmware_host.cpp"),
                           Path(__file__).with_name("CMakeLists.txt")]},
    }
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"native": native, "server_packets": packets, "passed": True}, indent=2))


if __name__ == "__main__":
    main()
