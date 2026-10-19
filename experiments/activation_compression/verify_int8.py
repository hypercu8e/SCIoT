"""Reload saved TFLite artifacts and verify input/source hashes and held-out outputs.

Uses the same metric helpers, but a separate interpreter/evaluation path and no
conversion. Exact output hashes apply to the recorded desktop environment.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from compare_lossy import output_stats


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import tensorflow as tf

    report = json.loads((args.result_dir / "summary.json").read_text())
    for name, expected in report["source_sha256"].items():
        if digest(Path(__file__).with_name(name)) != expected:
            raise AssertionError(f"Source hash mismatch: {name}")
    for name, expected in report["input_sha256"].items():
        if digest(args.input_dir / name) != expected:
            raise AssertionError(f"Input hash mismatch: {name}")
    calibration = report["dataset"]["calibration_indices"]
    evaluation = report["dataset"]["evaluation_indices"]
    inputs = np.load(args.input_dir / "input_frames.npy", allow_pickle=False)
    reference = np.load(args.input_dir / "outputs.npy", allow_pickle=False)[evaluation]
    assert not set(calibration) & set(evaluation)
    assert sorted(calibration + evaluation) == list(range(len(inputs)))
    with (args.result_dir / "frames.csv").open() as stream:
        csv_rows = list(csv.DictReader(stream))
    checked = {}
    for mode, saved in report["models"].items():
        path = args.result_dir / f"fomo_{mode}.tflite"
        assert digest(path) == saved["sha256"]
        assert path.stat().st_size == saved["file_bytes"]
        interpreter = tf.lite.Interpreter(
            model_path=str(path), num_threads=1, experimental_preserve_all_tensors=True,
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
        interpreter.allocate_tensors()
        source, target = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
        cut = next(d for d in interpreter.get_tensor_details() if d["index"] == saved["boundary"]["index"])
        assert cut["name"] == saved["boundary"]["name"]
        assert int(np.prod(cut["shape"])) * np.dtype(cut["dtype"]).itemsize == saved["boundary"]["logical_value_bytes"]
        if mode == "int8":
            assert source["dtype"] == target["dtype"] == cut["dtype"] == np.int8
            assert all(d["dtype"] in (np.int8, np.int32) for d in interpreter.get_tensor_details())
        predictions, clipped = [], 0
        for index in evaluation:
            frame = inputs[index][None]
            if mode == "int8":
                scale, zero = source["quantization"]
                rounded = np.rint(frame.astype(np.float64) / scale + zero)
                clipped += int(np.count_nonzero((rounded < -128) | (rounded > 127)))
                frame = np.clip(rounded, -128, 127).astype(np.int8)
            interpreter.set_tensor(source["index"], frame)
            interpreter.invoke()
            result = interpreter.get_tensor(target["index"])
            if mode == "int8":
                scale, zero = target["quantization"]
                result = ((result.astype(np.float64) - zero) * scale).astype(np.float32)
            predictions.append(result[0])
        predictions = np.asarray(predictions)
        assert hashlib.sha256(predictions.tobytes()).hexdigest() == saved["dequantized_output_sha256"]
        metrics = output_stats(reference, predictions, [.25, .5, .75])
        assert metrics == saved["output_vs_keras"]
        assert clipped == saved["input_values_clipped"]
        rows = [row for row in csv_rows if row["mode"] == mode]
        assert [int(row["source_frame_index"]) for row in rows] == evaluation
        assert sum(int(row["changed_cells_0.5"]) for row in rows) == metrics["thresholds"]["0.5"]["changed_cells"]
        assert sum(int(row["input_values_clipped"]) for row in rows) == clipped
        checked[mode] = {"file_hash_and_size": True, "outputs_recomputed_from_saved_binary": True,
                         "output_hash_and_metrics_match": True, "csv_counts_match": True,
                         "frames": len(evaluation)}
    verification = {
        "scope": "Separate desktop reload/evaluation path; shared metric helpers; no conversion or ESP32",
        "source_and_input_hashes_match": True, "calibration_evaluation_indices_disjoint": True,
        "models": checked,
    }
    args.output.write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
