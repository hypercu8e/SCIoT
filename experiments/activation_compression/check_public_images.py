"""Run the fixed FOMO and quantized variants on downloaded public images.

Functional checks and prediction fidelity; class-channel mapping is not assumed.
"""

import argparse
import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import numpy as np
from check_16x8 import evaluate
from compare_lossy import cell_labels, output_stats
from PIL import Image, ImageDraw


def prepare_image(image):
    image = image.convert("RGB")
    side = min(image.size)
    left, top = (image.width - side) // 2, (image.height - side) // 2
    rgb = np.asarray(image.crop((left, top, left + side, top + side)).resize(
        (96, 96), Image.Resampling.LANCZOS), dtype=np.uint8)
    normalized = rgb.astype(np.float32) / np.float32(255)
    gray = (normalized[..., 0] * np.float32(.299) + normalized[..., 1] * np.float32(.587)
            + normalized[..., 2] * np.float32(.114))[..., None]
    return rgb, gray


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--model-input-dir", type=Path, required=True)
    parser.add_argument("--quantized-archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir
    if out.exists() and any(out.iterdir()):
        parser.error("Use an empty output directory")
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((args.dataset_dir / "manifest.json").read_text())
    records, rgbs, frames = [], [], []
    for item in manifest["edgeimpulse_test_images"]:
        path = args.dataset_dir / item["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        with Image.open(path) as image:
            rgb, frame = prepare_image(image)
        records.append({"group": "edgeimpulse_test", "id": str(item["id"]), "path": item["path"]})
        rgbs.append(rgb)
        frames.append(frame)
    for sequence in manifest["otb_sequences"]:
        with zipfile.ZipFile(args.dataset_dir / sequence["path"]) as archive:
            indices = np.unique(np.linspace(0, len(sequence["frame_members"]) - 1, 32, dtype=int))
            for index in indices:
                member = sequence["frame_members"][index]
                with archive.open(member) as stream, Image.open(stream) as image:
                    rgb, frame = prepare_image(image)
                records.append({"group": sequence["name"], "id": str(index + 1), "path": member})
                rgbs.append(rgb)
                frames.append(frame)
    frames = np.asarray(frames, dtype=np.float32)
    import tensorflow as tf

    model_path = args.model_input_dir / "model.h5"
    controls = json.loads((args.quantized_archive / "summary.json").read_text())
    assert hashlib.sha256(model_path.read_bytes()).hexdigest() == controls["input_sha256"]["model.h5"]
    model = tf.keras.models.load_model(model_path, compile=False)
    cut = model.get_layer("block_2_add")
    prefix, suffix = tf.keras.Model(model.input, cut.output), tf.keras.Model(cut.output, model.output)

    @tf.function(input_signature=[tf.TensorSpec([1, 96, 96, 1], tf.float32)])
    def full(batch):
        return model(batch, training=False)

    @tf.function(input_signature=[tf.TensorSpec([1, 96, 96, 1], tf.float32)])
    def head(batch):
        return prefix(batch, training=False)

    @tf.function(input_signature=[tf.TensorSpec([1, 24, 24, 8], tf.float32)])
    def tail(batch):
        return suffix(batch, training=False)

    reference, split_outputs = [], []
    for frame in frames:
        reference.append(full(frame[None]).numpy()[0])
        split_outputs.append(tail(head(frame[None])).numpy()[0])
    reference, split_outputs = np.asarray(reference), np.asarray(split_outputs)
    np.testing.assert_allclose(reference, split_outputs, rtol=1e-5, atol=1e-6)
    report = {"scope": "Public-image CPU functional/fidelity checks; no accuracy claim or retraining",
              "images": len(frames), "manifest_sha256": hashlib.sha256((args.dataset_dir / "manifest.json").read_bytes()).hexdigest(),
              "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
              "preprocessing": "center square crop, Pillow Lanczos 96x96, BT.601 grayscale float32 [0,1]; not pixel-parity with Studio/FFmpeg",
              "split_max_error": float(np.max(np.abs(reference - split_outputs))),
              "class_channels": "channel 0 background; 1/2 unnamed, local H5 label order unconfirmed",
              "calibration": "none; use existing binaries calibrated on the original 48 frames", "variants": {}, "groups": {}}
    for mode in ("float32", "int8", "16x8"):
        path = args.quantized_archive / f"fomo_{mode}.tflite"
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == controls["models"][mode]["sha256"]
        info, prediction, _, _ = evaluate(tf, content, frames, "block_2_add")
        report["variants"][mode] = {"model_sha256": info["sha256"],
                                    "output_vs_keras": output_stats(reference, prediction, [.25, .5, .75])}
    rows = []
    labels = cell_labels(reference, .5)
    for index, item in enumerate(records):
        rows.append(dict(item, max_foreground_score=float(np.max(reference[index, ..., 1:])),
                         foreground_cells_0_5=int(np.count_nonzero(labels[index])),
                         channel1_cells=int(np.count_nonzero(labels[index] == 1)),
                         channel2_cells=int(np.count_nonzero(labels[index] == 2))))
    for group in dict.fromkeys(row["group"] for row in rows):
        selected = [row for row in rows if row["group"] == group]
        report["groups"][group] = {"images": len(selected),
                                   "images_with_foreground_0_5": sum(row["foreground_cells_0_5"] > 0 for row in selected),
                                   "foreground_cells_0_5": sum(row["foreground_cells_0_5"] for row in selected)}
    with (out / "images.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    selected = []
    for group in report["groups"]:
        indices = [i for i, row in enumerate(rows) if row["group"] == group]
        selected.extend(indices[int(i)] for i in np.linspace(0, len(indices) - 1, 8, dtype=int))
    canvas = Image.new("RGB", (4 * 240, 6 * 275), "white")
    draw = ImageDraw.Draw(canvas)
    for n, index in enumerate(selected):
        x, y = n % 4 * 240, n // 4 * 275
        image = Image.fromarray(rgbs[index]).resize((240, 240), Image.Resampling.NEAREST)
        canvas.paste(image, (x, y + 35))
        draw.text((x + 4, y + 4), f"{rows[index]['group']} {rows[index]['id']} | cells {rows[index]['foreground_cells_0_5']}", fill="black")
        for cy, cx in np.argwhere(labels[index] != 0):
            color = "red" if labels[index, cy, cx] == 1 else "blue"
            draw.rectangle((x + int(cx) * 20, y + 35 + int(cy) * 20,
                            x + int(cx + 1) * 20, y + 35 + int(cy + 1) * 20), outline=color, width=2)
    canvas.save(out / "predictions.png")
    shutil.copyfile(args.dataset_dir / "manifest.json", out / "dataset-manifest.json")
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["groups"], indent=2))


if __name__ == "__main__":
    main()
