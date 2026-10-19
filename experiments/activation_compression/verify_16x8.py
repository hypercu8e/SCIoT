"""Reload all saved controls and 16x8 binary; recompute held-out outputs.

Separate evaluation path with shared metric helpers; exact hashes apply to the
recorded desktop environment. No conversion, target or network execution.
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
    parser.add_argument("--int8-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import tensorflow as tf

    report = json.loads((args.result_dir / "summary.json").read_text())
    assert digest(args.int8_archive / "summary.json") == report["control_summary_sha256"]
    for name, expected in report["source_sha256"].items():
        assert digest(Path(__file__).with_name(name)) == expected, name
    for name, expected in report["input_sha256"].items():
        assert digest(args.input_dir / name) == expected, name
    calibration, evaluation = (report["dataset"][key] for key in ("calibration_indices", "evaluation_indices"))
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
        details = {d["index"]: d for d in interpreter.get_tensor_details()}
        boundary = details[saved["boundary"]["index"]]
        assert boundary["name"] == saved["boundary"]["name"]
        assert int(np.prod(boundary["shape"])) * np.dtype(boundary["dtype"]).itemsize == saved["boundary"]["logical_value_bytes"]
        if mode == "16x8":
            assert source["dtype"] == target["dtype"] == boundary["dtype"] == np.int16
            assert all(d["dtype"] in (np.int8, np.int16, np.int32, np.int64) for d in details.values())
            for op in interpreter._get_ops_details():
                if op["op_name"] in ("CONV_2D", "DEPTHWISE_CONV_2D"):
                    assert [details[i]["dtype"] for i in op["inputs"]] == [np.int16, np.int8, np.int64]
        predictions, clipped = [], 0
        for index in evaluation:
            frame = inputs[index][None]
            if np.issubdtype(source["dtype"], np.integer):
                scale, zero = source["quantization"]
                bounds = np.iinfo(source["dtype"])
                rounded = np.rint(frame.astype(np.float64) / scale + zero)
                clipped += int(np.count_nonzero((rounded < bounds.min) | (rounded > bounds.max)))
                frame = np.clip(rounded, bounds.min, bounds.max).astype(source["dtype"])
            interpreter.set_tensor(source["index"], frame)
            interpreter.invoke()
            result = interpreter.get_tensor(target["index"])
            if np.issubdtype(result.dtype, np.integer):
                scale, zero = target["quantization"]
                result = ((result.astype(np.float64) - zero) * scale).astype(np.float32)
            predictions.append(result[0])
        predictions = np.asarray(predictions)
        assert hashlib.sha256(predictions.tobytes()).hexdigest() == saved["dequantized_output_sha256"]
        metrics = output_stats(reference, predictions, [.25, .5, .75])
        assert metrics == saved["output_vs_keras"]
        assert clipped == saved["input_values_clipped"]
        rows = [r for r in csv_rows if r["mode"] == mode]
        assert [int(r["source_frame_index"]) for r in rows] == evaluation
        assert sum(int(r["changed_cells_0.5"]) for r in rows) == metrics["thresholds"]["0.5"]["changed_cells"]
        assert sum(int(r["input_values_clipped"]) for r in rows) == clipped
        checked[mode] = {"file_hash_and_size": True, "output_recomputed_and_hash_matches": True,
                         "metrics_and_csv_match": True, "evaluation_frames": len(evaluation)}
    result = {"scope": "Separate desktop binary reload/evaluation; shared metric helpers; no ESP32",
              "source_input_control_hashes_match": True, "disjoint_frame_indices": True, "models": checked}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
