"""Prepare existing INT8 full/prefix/suffix models and fixed ESP32 test vectors.

No training or calibration. Verify the cut byte-for-byte on every decoded video
frame, then retain three predetermined evaluation frames for the firmware probe.
"""

import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path

import numpy as np

from check_int8 import operator_inventory, prepare_input, tensor_description
from split_tflite import split_single_boundary

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = Path(__file__).with_name("int8_2026-10-18")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def video_inputs(video):
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(video)]))
    stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
    if any(d.get("rotation", 0) for d in stream.get("side_data_list", [])):
        raise ValueError("Rotated video is not supported")
    w, h = stream["width"], stream["height"]
    side = min(w, h)
    filters = (f"fps=5,crop={side}:{side}:{(w-side)//2}:{(h-side)//2},"
               "scale=96:96:flags=lanczos")
    data = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(video), "-an", "-vf", filters,
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])
    rgb = np.frombuffer(data, dtype=np.uint8).reshape(-1, 96, 96, 3).astype(np.float32) / np.float32(255)
    return (rgb[..., 0] * np.float32(.299) + rgb[..., 1] * np.float32(.587)
            + rgb[..., 2] * np.float32(.114))[..., None]


def interpreter(content, preserve=False):
    import tensorflow as tf
    result = tf.lite.Interpreter(
        model_content=content, num_threads=1, experimental_preserve_all_tensors=preserve,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    result.allocate_tensors()
    return result


def io_description(runtime):
    return {"input": tensor_description(runtime.get_input_details()[0]),
            "output": tensor_description(runtime.get_output_details()[0])}


def invoke(runtime, values):
    runtime.set_tensor(runtime.get_input_details()[0]["index"], values)
    runtime.invoke()
    return runtime.get_tensor(runtime.get_output_details()[0]["index"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=ROOT / "VideoWithCan.mp4")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        parser.error("Use an empty output directory to preserve previous runs")
    original = json.loads((ARCHIVE / "summary.json").read_text())
    full = (ARCHIVE / "fomo_int8.tflite").read_bytes()
    if digest(full) != original["models"]["int8"]["sha256"]:
        raise ValueError("INT8 model differs from archived experiment")
    video_hash = digest(args.video.read_bytes())
    if video_hash != original["input_metadata"]["video_sha256"]:
        raise ValueError("Video differs from archived experiment")
    boundary_name = original["models"]["int8"]["boundary"]["name"]
    prefix, suffix = split_single_boundary(full, boundary_name)
    binaries = {"full": full, "prefix": prefix, "suffix": suffix}
    runtimes = {name: interpreter(binary, name == "full") for name, binary in binaries.items()}
    descriptions = {name: io_description(runtime) for name, runtime in runtimes.items()}
    full_runtime = runtimes["full"]
    boundary = next(d for d in full_runtime.get_tensor_details() if d["name"] == boundary_name)
    original_boundary = tensor_description(boundary)
    # IDs/names may change, but every semantic I/O attribute must survive the cut.
    semantic_keys = ("shape", "dtype", "logical_value_bytes", "scales", "zero_points", "quantized_dimension")
    for description in (descriptions["prefix"]["output"], descriptions["suffix"]["input"]):
        if any(description[k] != original_boundary[k] for k in semantic_keys):
            raise AssertionError("Boundary quantization or shape changed")
    frames = video_inputs(args.video)
    selected = [48, 96, 145]
    if len(frames) != 146:
        raise ValueError("Expected 146 sampled frames; review vector selection")
    inputs, cuts, outputs = [], [], []
    clipped = 0
    all_output_hash = hashlib.sha256()
    for index, frame in enumerate(frames):
        values, count = prepare_input(frame[None], full_runtime.get_input_details()[0])
        clipped += count
        expected = invoke(full_runtime, values)
        expected_cut = full_runtime.get_tensor(boundary["index"])
        cut = invoke(runtimes["prefix"], values)
        np.testing.assert_array_equal(cut, expected_cut)
        # An actual byte serialization/reload at the boundary, without rescaling.
        received = np.frombuffer(cut.tobytes(), dtype=np.int8).reshape(cut.shape).copy()
        actual = invoke(runtimes["suffix"], received)
        np.testing.assert_array_equal(actual, expected)
        all_output_hash.update(expected.tobytes())
        if index in selected:
            inputs.append(values[0])
            cuts.append(cut[0])
            outputs.append(expected[0])
    out.mkdir(parents=True, exist_ok=True)
    for name, binary in binaries.items():
        (out / f"{name}.tflite").write_bytes(binary)
        descriptions[name].update(sha256=digest(binary), file_bytes=len(binary),
                                  operators=operator_inventory(binary))
    np.savez_compressed(out / "vectors.npz", frame_indices=np.array(selected, dtype=np.int32),
                        inputs=np.asarray(inputs), boundaries=np.asarray(cuts), outputs=np.asarray(outputs))
    # Save NPY representation hash to distinguish regenerated input sets.
    import io
    import tensorflow as tf
    stream = io.BytesIO()
    np.save(stream, frames)
    input_hash = digest(stream.getvalue())
    report = {
        "scope": "Desktop verification and hardware preparation; no ESP32 execution or Wi-Fi",
        "tensorflow": tf.__version__, "numpy": np.__version__, "python": platform.python_version(),
        "git_head_before_changes": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {name: digest(Path(__file__).with_name(name).read_bytes())
                          for name in ("prepare_esp32_int8.py", "split_tflite.py", "check_int8.py")},
        "video_sha256": video_hash, "decoded_input_npy_sha256": input_hash,
        "decoded_inputs_match_archived_int8": input_hash == original["input_sha256"]["input_frames.npy"],
        "frames_verified": len(frames), "selected_frame_indices": selected,
        "selected_frames_in_archived_evaluation_partition": all(i in original["dataset"]["evaluation_indices"] for i in selected),
        "input_values_clipped": clipped, "boundary_tensor": original_boundary,
        "models": descriptions, "vectors_sha256": digest((out / "vectors.npz").read_bytes()),
        "full_raw_int8_output_sha256_all_frames": all_output_hash.hexdigest(),
        "verification": {"prefix_matches_full_boundary_byte_for_byte": True,
                         "split_matches_full_output_byte_for_byte": True,
                         "boundary_quantization_unchanged": True,
                         "new_calibration_or_training": False,
                         "hardware_allocate_invoke_checked": False},
    }
    (out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"frames_verified": len(frames), "file_bytes": {k: len(v) for k, v in binaries.items()},
                      "matches_archived_inputs": report["decoded_inputs_match_archived_int8"],
                      "split_matches_full_byte_for_byte": True}, indent=2))


if __name__ == "__main__":
    main()
