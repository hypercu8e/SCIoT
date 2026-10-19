"""Evaluate integer-only 16x8 FOMO against the archived INT8/float32 controls.

Fixed calibration/evaluation partition, full model on CPU; no ESP32 benchmark.
"""

import argparse
import csv
import hashlib
import json
import platform
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from check_int8 import (
    operator_inventory,
    scalar_quantization,
    sha256,
    tensor_description,
)
from compare_lossy import cell_labels, error_stats, output_stats


def prepare(values, detail):
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite input")
    dtype = np.dtype(detail["dtype"])
    if dtype == np.dtype("float32"):
        return values.astype(dtype), 0
    if dtype not in (np.dtype("int8"), np.dtype("int16")):
        raise ValueError("Expected float32, int8 or int16 input")
    scale, zero = scalar_quantization(detail)
    bounds = np.iinfo(dtype)
    rounded = np.rint(values.astype(np.float64) / scale + zero)
    clipped = int(np.count_nonzero((rounded < bounds.min) | (rounded > bounds.max)))
    return np.clip(rounded, bounds.min, bounds.max).astype(dtype), clipped


def restore(values, detail):
    if values.dtype == np.float32:
        return values.copy()
    if values.dtype not in (np.dtype("int8"), np.dtype("int16")):
        raise ValueError("Expected int8/int16 activation")
    scale, zero = scalar_quantization(detail)
    return ((values.astype(np.float64) - zero) * scale).astype(np.float32)


def evaluate(tf, content, frames, split_layer):
    interpreter = tf.lite.Interpreter(
        model_content=content, num_threads=1, experimental_preserve_all_tensors=True,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    interpreter.allocate_tensors()
    source, target = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    details = interpreter.get_tensor_details()
    cuts = [d for d in details if f"/{split_layer}/" in d["name"]]
    if len(cuts) != 1 or tuple(cuts[0]["shape"]) != (1, 24, 24, 8):
        raise ValueError("Expected the fixed FOMO block_2_add boundary")
    cut = cuts[0]
    typed_ops = []
    by_index = {d["index"]: d for d in details}
    for op in interpreter._get_ops_details():
        typed_ops.append({
            "name": op["op_name"],
            "inputs": [np.dtype(by_index[i]["dtype"]).name for i in op["inputs"] if i >= 0],
            "outputs": [np.dtype(by_index[i]["dtype"]).name for i in op["outputs"] if i >= 0],
        })
    predictions, boundaries, clips = [], [], []
    for frame in frames:
        encoded, clipped = prepare(frame[None], source)
        interpreter.set_tensor(source["index"], encoded)
        interpreter.invoke()
        predictions.append(restore(interpreter.get_tensor(target["index"]), target)[0])
        boundaries.append(restore(interpreter.get_tensor(cut["index"]), cut)[0])
        clips.append(clipped)
    info = {
        "file_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
        "input": tensor_description(source), "output": tensor_description(target),
        "boundary": tensor_description(cut),
        "tensor_dtype_counts": dict(Counter(np.dtype(d["dtype"]).name for d in details)),
        "operators": operator_inventory(content), "operator_tensor_types": typed_ops,
        "desktop_allocate_and_invoke_passed": True, "default_delegates_disabled": True,
        "preserve_all_tensors": True, "timing_and_peak_memory_measured": False,
        "input_values_clipped": sum(clips), "input_values_evaluated": int(frames.size),
    }
    return info, np.asarray(predictions), np.asarray(boundaries), clips


def validate_16x8(info):
    if any(info[name]["dtype"] != "int16" for name in ("input", "output", "boundary")):
        raise AssertionError("INT16 input/output/boundary not obtained")
    if set(info["tensor_dtype_counts"]) - {"int8", "int16", "int32", "int64"}:
        raise AssertionError("Unexpected noninteger tensor")
    if any(op["name"].startswith("CUSTOM") or op["name"] == "DEQUANTIZE" for op in info["operators"]):
        raise AssertionError("Unexpected custom/fallback operation")
    convolutions = [op for op in info["operator_tensor_types"]
                    if op["name"] in ("CONV_2D", "DEPTHWISE_CONV_2D")]
    if not convolutions or any(op["inputs"] != ["int16", "int8", "int64"]
                               or op["outputs"] != ["int16"] for op in convolutions):
        raise AssertionError("Expected int16 activations, int8 weights and int64 biases")


def write_report(report, path):
    lines = ["# Confronto float32, INT8 e 16×8 — CPU PC", "",
             ("Stesso H5, preprocessing e partizione della prima prova INT8: 48 frame "
             "di calibrazione e 98 di valutazione, disgiunti ma dallo stesso video. "
             "Nessun riaddestramento o ricerca dei parametri sui dati di valutazione."), "",
             "| Variante | Byte TFLite | Byte valori al confine | Max errore punteggi | Celle cambiate a 0,5 | Perse | Introdotte |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for mode, info in report["models"].items():
        metric = info["output_vs_keras"]
        cells = metric["thresholds"]["0.5"]
        lines.append(f"| {mode} | {info['file_bytes']} | {info['boundary']['logical_value_bytes']} | "
                     f"{metric['max_absolute_error']:.6g} | {cells['changed_cells']} / {metric['cells']} | "
                     f"{cells['lost_foreground_cells']} | {cells['introduced_foreground_cells']} |")
    info = report["models"]["16x8"]
    lines.extend(["", ("Il riferimento Keras ha 99 celle oggetto a soglia 0,5. Le celle "
                  "non sono oggetti distinti: queste metriche misurano fedeltà al modello "
                  "originale senza annotazioni o postprocessing FOMO. Leggere anche soglie "
                  "0,25/0,75 e IoU delle celle di primo piano nel JSON."), "",
                  "## Verifiche", "",
                  ("Float32 e INT8 sono gli stessi binari dell'archivio precedente, "
                  "ricaricati e rieseguiti; hash delle uscite e metriche coincidono. "
                  "16×8 è convertito con il solo set sperimentale integer-only, "
                  "ingresso/uscita INT16. Le convoluzioni usano attivazioni INT16, "
                  "pesi INT8 e bias INT64, senza fallback float."), "",
                  (f"Tipi dei tensori 16×8: `{info['tensor_dtype_counts']}`. "
                  f"Valori d'ingresso tagliati: {info['input_values_clipped']} / {info['input_values_evaluated']}."), "",
                  "Confine 16×8: " + json.dumps(info["boundary"], ensure_ascii=False) + ".", "",
                  "Operatori/versioni 16×8: " + ", ".join(f"`{op['name']}` v{op['version']}" for op in info["operators"]) + ".", "",
                  "## Limiti e seguito", "",
                  ("È un modello intero eseguito sul PC. Il confine viene ispezionato "
                  "internamente: due sottomodelli quantizzati e il protocollo SCIoT con "
                  "scale/zero point coerenti non sono ancora verificati. I byte al confine "
                  "sono i soli valori, esclusi metadati e trasporto; non sono picco di RAM."), "",
                  ("Nessuna misura di velocità, memoria o energia, né esecuzione ESP32. "
                  "L'interprete conserva tutti i tensori e disabilita i delegati per ispezione. "
                  "La conversione riuscita non dimostra il supporto degli operatori INT16 "
                  "nel runtime Micro del firmware o l'accelerazione ESP-NN."), "",
                  ("Confrontare la fedeltà delle due varianti prima di scegliere la "
                  "rappresentazione. Verificare il runtime Micro e poi memoria/tempo "
                  "sulla scheda, conservando il controllo float32. Ampliare calibrazione "
                  "e valutazione su sequenze distinte per generalizzare; non ottimizzare "
                  "parametri sullo stesso campione di test. Nessuna soglia di qualità "
                  "accettabile per l'applicazione è stata stabilita."), ""])
    path.write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--int8-archive", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    import tensorflow as tf

    baseline = json.loads((args.int8_archive / "summary.json").read_text())
    for name, expected in baseline["input_sha256"].items():
        if sha256(args.input_dir / name) != expected:
            raise ValueError(f"Input differs from INT8 control: {name}")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("Use an empty output directory")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frames = np.load(args.input_dir / "input_frames.npy", allow_pickle=False)
    saved = np.load(args.input_dir / "outputs.npy", allow_pickle=False)
    calibration = baseline["dataset"]["calibration_indices"]
    evaluation = baseline["dataset"]["evaluation_indices"]
    assert not set(calibration) & set(evaluation)
    model = tf.keras.models.load_model(args.input_dir / "model.h5", compile=False)
    split = baseline["input_metadata"]["split"]["layer"]
    inspector = tf.keras.Model(model.input, [model.output, model.get_layer(split).output])

    @tf.function(input_signature=[tf.TensorSpec([1, *frames.shape[1:]], tf.float32)])
    def reference_run(batch):
        return inspector(batch, training=False)

    reference, boundary_reference = [], []
    for frame in frames[evaluation]:
        prediction, cut = reference_run(frame[None])
        reference.append(prediction.numpy()[0])
        boundary_reference.append(cut.numpy()[0])
    reference, boundary_reference = np.asarray(reference), np.asarray(boundary_reference)
    np.testing.assert_allclose(reference, saved[evaluation], rtol=1e-5, atol=1e-6)
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.representative_dataset = lambda: ([frame[None]] for frame in frames[calibration])
    converter.target_spec.supported_ops = [tf.lite.OpsSet.EXPERIMENTAL_TFLITE_BUILTINS_ACTIVATIONS_INT16_WEIGHTS_INT8]
    converter.inference_input_type = tf.int16
    converter.inference_output_type = tf.int16
    int16_content = converter.convert()
    report = {
        "created_utc": datetime.now(UTC).isoformat(),
        "scope": "CPU full-model 16x8 evaluation; no training, split deployment, ESP32 or timing",
        "environment": {"tensorflow": tf.__version__, "numpy": np.__version__,
                        "python": platform.python_version(), "platform": platform.platform()},
        "source_sha256": {name: sha256(Path(__file__).with_name(name)) for name in
                          ("check_16x8.py", "verify_16x8.py", "test_16x8.py", "check_int8.py",
                           "compare_lossy.py", "lossy_codec.py", "compare.py")},
        "input_sha256": baseline["input_sha256"], "input_metadata": baseline["input_metadata"],
        "control_summary_sha256": sha256(args.int8_archive / "summary.json"),
        "dataset": baseline["dataset"], "keras_vs_saved_outputs": error_stats(saved[evaluation], reference),
        "models": {},
    }
    csv_rows, predictions = [], {}
    for mode in ("float32", "int8", "16x8"):
        content = int16_content if mode == "16x8" else (args.int8_archive / f"fomo_{mode}.tflite").read_bytes()
        if mode != "16x8" and hashlib.sha256(content).hexdigest() != baseline["models"][mode]["sha256"]:
            raise ValueError(f"Control binary hash mismatch: {mode}")
        info, prediction, cut, clips = evaluate(tf, content, frames[evaluation], split)
        if not np.isfinite(prediction).all() or not np.isfinite(cut).all():
            raise AssertionError("Nonfinite prediction/boundary")
        info.update({"output_vs_keras": output_stats(reference, prediction, [.25, .5, .75]),
                     "boundary_vs_keras": error_stats(boundary_reference, cut),
                     "dequantized_output_sha256": hashlib.sha256(prediction.tobytes()).hexdigest()})
        if mode == "16x8":
            validate_16x8(info)
        else:
            assert info["dequantized_output_sha256"] == baseline["models"][mode]["dequantized_output_sha256"]
            assert info["output_vs_keras"] == baseline["models"][mode]["output_vs_keras"]
        (args.output_dir / f"fomo_{mode}.tflite").write_bytes(content)
        report["models"][mode], predictions[mode] = info, prediction
        before, after = cell_labels(reference, .5), cell_labels(prediction, .5)
        for row, original_index in enumerate(evaluation):
            csv_rows.append({"mode": mode, "source_frame_index": original_index,
                             "max_output_error": float(np.max(np.abs(prediction[row] - reference[row]))),
                             "reference_foreground_cells_0.5": int(np.count_nonzero(before[row])),
                             "changed_cells_0.5": int(np.count_nonzero(before[row] != after[row])),
                             "input_values_clipped": clips[row]})
    report["16x8_vs_int8"] = output_stats(predictions["int8"], predictions["16x8"], [.25, .5, .75])
    report["controls_reloaded_and_output_hashes_match"] = True
    with (args.output_dir / "frames.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    (args.output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    write_report(report, args.output_dir / "report.md")
    print(json.dumps({name: {"file_bytes": info["file_bytes"], "output_vs_keras": info["output_vs_keras"]}
                      for name, info in report["models"].items()}, indent=2))


if __name__ == "__main__":
    main()
