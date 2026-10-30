"""Freeze the existing INT8 prefix and local vectors for the EON comparison.

No training, calibration, model conversion or network access. Desktop references
are deliberately distinct from the hardware baseline still to be collected.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "esp32_representation_benchmark/artifacts"
SEMANTICS = ("shape", "dtype", "logical_value_bytes", "scales", "zero_points",
             "quantized_dimension")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_file(path, expected):
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError(f"Hash mismatch: {path.name}")
    return data


def validate_boundary(prefix, suffix):
    if any(prefix["output"][k] != suffix["input"][k] for k in SEMANTICS):
        raise ValueError("Prefix/suffix boundary differs")
    for spec, shape in ((prefix["input"], [1, 96, 96, 1]),
                        (prefix["output"], [1, 24, 24, 8])):
        if spec["dtype"] != "int8" or spec["shape"] != shape:
            raise ValueError("Unexpected prefix input/output")
        if len(spec["scales"]) != 1 or spec["scales"][0] <= 0:
            raise ValueError("Expected positive per-tensor quantization scale")
        if len(spec["zero_points"]) != 1:
            raise ValueError("Expected one zero point")


def quantize(frames, spec):
    # Match the device: double precision calculation, ties to nearest even.
    return np.clip(np.rint(frames.astype(np.float64) / spec["scales"][0]
                           + spec["zero_points"][0]), -128, 127).astype(np.int8)


def prepare(source=SOURCE, output=HERE / "artifacts"):
    import tensorflow as tf

    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory; preserve previous preparations")
    original = json.loads((source / "manifest.json").read_text())
    models = original["models"]["int8"]
    validate_boundary(models["prefix"], models["suffix"])
    binaries = {name: checked_file(source / f"int8-{name}.tflite", models[name]["sha256"])
                for name in ("prefix", "suffix")}
    inputs_data = checked_file(source / "inputs.npz", original["inputs_sha256"])
    with np.load(source / "inputs.npz", allow_pickle=False) as inputs:
        frames, frame_ids = inputs["frames"].copy(), inputs["frame_ids"].copy()
    if frame_ids.tolist() != original["frames"] or frames.shape != (3, 96, 96, 1):
        raise ValueError("Unexpected canonical frames")
    if not np.isfinite(frames).all():
        raise ValueError("Nonfinite canonical input")
    values = quantize(frames, models["prefix"]["input"])
    tensors, rows = {}, []
    for label, resolver in (
        ("desktop_builtin", tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES),
        ("desktop_reference", tf.lite.experimental.OpResolverType.BUILTIN_REF),
    ):
        runtimes = {}
        for name, binary in binaries.items():
            runtime = tf.lite.Interpreter(model_content=binary, num_threads=1,
                                         experimental_op_resolver_type=resolver)
            runtime.allocate_tensors()
            for direction, details in (("input", runtime.get_input_details()),
                                       ("output", runtime.get_output_details())):
                spec = models[name][direction]
                if len(details) != 1:
                    raise ValueError("Expected a single input/output tensor")
                detail = details[0]
                params = detail["quantization_parameters"]
                if (detail["dtype"] != np.int8 or detail["shape"].tolist() != spec["shape"]
                    or params["scales"].tolist() != spec["scales"]
                    or params["zero_points"].tolist() != spec["zero_points"]):
                    raise ValueError("Runtime tensor differs from manifest")
            runtimes[name] = runtime
        activations, outputs = [], []
        for frame_id, value in zip(frame_ids, values):
            prefix, suffix = runtimes["prefix"], runtimes["suffix"]
            prefix.set_tensor(prefix.get_input_details()[0]["index"], value[None])
            prefix.invoke()
            activation = prefix.get_tensor(prefix.get_output_details()[0]["index"])
            suffix.set_tensor(suffix.get_input_details()[0]["index"], activation)
            suffix.invoke()
            result = suffix.get_tensor(suffix.get_output_details()[0]["index"])
            activations.append(activation[0])
            outputs.append(result[0])
            rows.append({"runtime": label, "frame": int(frame_id),
                         "activation_sha256": sha(activation.tobytes()),
                         "output_sha256": sha(result.tobytes())})
        tensors[label + "_activations"] = np.stack(activations)
        tensors[label + "_outputs"] = np.stack(outputs)
    output.mkdir(parents=True, exist_ok=True)
    for name, binary in binaries.items():
        (output / f"int8-{name}.tflite").write_bytes(binary)
    (output / "inputs.npz").write_bytes(inputs_data)
    np.savez_compressed(output / "vectors.npz", frame_ids=frame_ids,
                        input_int8=values, **tensors)
    for frame_id, value in zip(frame_ids, values):
        (output / f"input-{frame_id}.bin").write_bytes(value.tobytes())
    report = {
        "status": "local_preparation_only", "tensorflow_version": tf.__version__,
        "source_manifest_sha256": sha((source / "manifest.json").read_bytes()),
        "source_experiment_sha256": original["experiment_sha256"],
        "models": models, "frames": frame_ids.tolist(), "desktop_vectors": rows,
        "desktop_resolvers_equal": bool(np.array_equal(tensors["desktop_builtin_activations"],
                                                         tensors["desktop_reference_activations"])),
        "hardware_baseline_collected": False, "eon_export_obtained": False,
        "files": {p.name: sha(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file()},
    }
    (output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    with zipfile.ZipFile(output / "upload-prefix.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(output / "int8-prefix.tflite", "int8-prefix.tflite")
        archive.write(output / "manifest.json", "manifest.json")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=HERE / "artifacts")
    args = parser.parse_args()
    result = prepare(args.source, args.output)
    print(json.dumps({k: result[k] for k in ("status", "frames", "desktop_resolvers_equal",
                                             "hardware_baseline_collected", "eon_export_obtained")}))
