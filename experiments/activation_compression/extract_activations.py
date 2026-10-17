"""Extract a fixed Keras split from a video and verify against the full model."""

import argparse
import hashlib
import json
import subprocess
import zipfile
from fractions import Fraction
from pathlib import Path

import numpy as np
import tensorflow as tf
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--model-zip", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--split-layer", default="block_2_add")
    parser.add_argument("--fps", type=int, default=5)
    args = parser.parse_args()
    if args.fps < 1:
        parser.error("--fps must be positive")
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(args.video),
    ]))
    stream = next(s for s in probe["streams"] if s["codec_type"] == "video")
    if any(d.get("rotation", 0) for d in stream.get("side_data_list", [])):
        raise ValueError("Normalize video rotation before this first experiment")
    width, height = stream["width"], stream["height"]
    side = min(width, height)
    left, top = (width - side) // 2, (height - side) // 2
    filters = f"fps={args.fps},crop={side}:{side}:{left}:{top},scale=96:96:flags=lanczos"
    raw = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(args.video), "-an", "-vf", filters,
        "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
    ])
    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 96, 96, 3)
    if len(rgb) < 2:
        raise ValueError("Video has fewer than two sampled frames")
    normalized = rgb.astype(np.float32) / np.float32(255)
    inputs = (
        normalized[..., 0] * np.float32(.299)
        + normalized[..., 1] * np.float32(.587)
        + normalized[..., 2] * np.float32(.114)
    )[..., None]
    with zipfile.ZipFile(args.model_zip) as archive:
        model_bytes = archive.read("model.h5")
    model_path = out / "model.h5"
    model_path.write_bytes(model_bytes)
    model = tf.keras.models.load_model(model_path, compile=False)
    if model.input_shape[1:] != (96, 96, 1):
        raise ValueError("This preprocessing requires 96x96 grayscale input")
    cut = model.get_layer(args.split_layer)
    cut_index = model.layers.index(cut)
    left_names = {layer.name for layer in model.layers[:cut_index + 1]}
    frontier = set()
    for layer in model.layers[cut_index + 1:]:
        for tensor in tf.nest.flatten(layer.input):
            name = tensor._keras_history.layer.name
            if name in left_names:
                frontier.add(name)
    if frontier != {cut.name}:
        raise ValueError(f"Split requires more than one boundary tensor: {frontier}")
    prefix = tf.keras.Model(model.input, cut.output)
    suffix = tf.keras.Model(cut.output, model.output)
    activations, outputs, errors = [], [], []
    for sample in inputs:
        original = model(sample[None], training=False).numpy()
        activation = prefix(sample[None], training=False)
        reconstructed = suffix(activation, training=False).numpy()
        np.testing.assert_allclose(reconstructed, original, rtol=1e-5, atol=1e-6)
        errors.append(float(np.max(np.abs(reconstructed - original))))
        activations.append(activation.numpy()[0])
        outputs.append(original[0])
    activations = np.asarray(activations, dtype=np.float32)
    if not np.isfinite(activations).all():
        raise ValueError("Nonfinite activations")
    np.save(out / "activations.npy", activations)
    np.save(out / "outputs.npy", np.asarray(outputs, dtype=np.float32))
    np.save(out / "input_frames.npy", inputs)
    np.save(out / "sample_times_seconds.npy", np.arange(len(inputs)) / args.fps)
    report = {
        "video": args.video.name,
        "video_sha256": hashlib.sha256(args.video.read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "video_duration_seconds": float(probe["format"]["duration"]),
        "original_size_wh": [width, height],
        "original_average_fps": float(Fraction(stream["avg_frame_rate"])),
        "original_frame_count": int(stream["nb_frames"]) if "nb_frames" in stream else None,
        "preprocessing": {
            "sampling_fps": args.fps,
            "sampling": "ffmpeg fps filter; times are nominal sampling-grid times",
            "crop_xywh": [left, top, side, side],
            "resize": "96x96, FFmpeg Lanczos; pixel parity with Studio not established",
            "grayscale": "BT.601 .299 .587 .114, float32 in [0,1]",
        },
        "split": {
            "layer": cut.name, "keras_layer_index_including_input": cut_index,
            "boundary_tensors": sorted(frontier),
            "activation_shape_without_batch": list(activations.shape[1:]),
            "dtype": str(activations.dtype),
            "values_per_frame": int(activations[0].size),
            "raw_tensor_bytes_per_frame": int(activations[0].nbytes),
        },
        "verification": {
            "frames_checked": len(inputs), "full_vs_split_max_absolute_error": max(errors),
            "rtol": 1e-5, "atol": 1e-6, "passed": True,
            "scope": "Keras float32 on CPU, one process; no TFLite/network/ESP32 verification",
        },
    }
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    indices = np.linspace(0, len(rgb) - 1, 6, dtype=int)
    canvas = Image.new("RGB", (864, 636), "white")
    draw = ImageDraw.Draw(canvas)
    for n, index in enumerate(indices):
        x, y = (n % 3) * 288, (n // 3) * 318
        canvas.paste(Image.fromarray(rgb[index]).resize((288, 288), Image.Resampling.NEAREST), (x, y + 30))
        draw.text((x + 8, y + 8), f"t = {index / args.fps:.1f} s", fill="black")
    canvas.save(out / "sampled_frames.png")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
