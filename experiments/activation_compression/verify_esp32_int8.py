"""Independently reload saved full/split binaries and the three firmware vectors."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=Path(__file__).with_name("esp32_prep_2026-10-19"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import tensorflow as tf
    source = args.artifacts
    manifest = json.loads((source / "manifest.json").read_text())
    for name, expected in manifest["source_sha256"].items():
        if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != expected:
            raise AssertionError(f"Source hash mismatch: {name}")
    vectors_path = source / "vectors.npz"
    assert hashlib.sha256(vectors_path.read_bytes()).hexdigest() == manifest["vectors_sha256"]
    with np.load(vectors_path, allow_pickle=False) as saved:
        vectors = {key: saved[key] for key in saved.files}
    assert vectors["frame_indices"].tolist() == manifest["selected_frame_indices"]
    runtimes = {}
    for stage in ("full", "prefix", "suffix"):
        path = source / f"{stage}.tflite"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["models"][stage]["sha256"]
        runtime = tf.lite.Interpreter(
            model_path=str(path), num_threads=1, experimental_preserve_all_tensors=True,
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
        runtime.allocate_tensors()
        for role, details in (("input", runtime.get_input_details()), ("output", runtime.get_output_details())):
            assert len(details) == 1
            detail, expected = details[0], manifest["models"][stage][role]
            assert detail["dtype"] == np.int8
            assert detail["shape"].tolist() == expected["shape"]
            assert detail["quantization_parameters"]["scales"].tolist() == expected["scales"]
            assert detail["quantization_parameters"]["zero_points"].tolist() == expected["zero_points"]
        assert all(d["dtype"] in (np.int8, np.int32) for d in runtime.get_tensor_details())
        runtimes[stage] = runtime
    for i, frame in enumerate(vectors["frame_indices"]):
        for stage, input_key, output_key in (("full", "inputs", "outputs"),
                                             ("prefix", "inputs", "boundaries"),
                                             ("suffix", "boundaries", "outputs")):
            runtime = runtimes[stage]
            runtime.set_tensor(runtime.get_input_details()[0]["index"], vectors[input_key][i:i+1])
            runtime.invoke()
            actual = runtime.get_tensor(runtime.get_output_details()[0]["index"])[0]
            np.testing.assert_array_equal(actual, vectors[output_key][i], err_msg=f"{stage} frame {frame}")
        boundary = next(d for d in runtimes["full"].get_tensor_details()
                        if d["name"] == manifest["boundary_tensor"]["name"])
        np.testing.assert_array_equal(runtimes["full"].get_tensor(boundary["index"])[0], vectors["boundaries"][i])
    report = {"scope": "Independent reload of saved binaries/vectors on desktop; no conversion or ESP32",
              "models_checked": list(runtimes), "frame_indices": vectors["frame_indices"].tolist(),
              "hashes_io_quantization_and_integer_types_match": True,
              "all_saved_inputs_reproduce_expected_bytes": True, "passed": True}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

