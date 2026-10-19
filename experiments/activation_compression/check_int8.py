"""Convert the fixed FOMO to float32/INT8 TFLite and compare held-out frames.

CPU feasibility check only: no training, ESP32 execution or transport benchmark.
"""

import argparse
import csv
import hashlib
import json
import platform
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from compare_lossy import cell_labels, error_stats, output_stats


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_indices(frame_count, calibration_frames):
    if not 1 <= calibration_frames < frame_count:
        raise ValueError("Calibration must leave at least one evaluation frame")
    return np.arange(calibration_frames), np.arange(calibration_frames, frame_count)


def scalar_quantization(detail):
    params = detail["quantization_parameters"]
    scales, zeros = params["scales"], params["zero_points"]
    if len(scales) != 1 or len(zeros) != 1 or not np.isfinite(scales[0]) or scales[0] <= 0:
        raise ValueError("Expected a finite positive per-tensor quantization scale")
    return float(scales[0]), int(zeros[0])


def prepare_input(values, detail):
    """Return input plus number of values actually clipped, not endpoint hits."""
    if not np.isfinite(values).all():
        raise ValueError("Nonfinite input")
    dtype = np.dtype(detail["dtype"])
    if dtype == np.dtype("float32"):
        return values.astype(dtype), 0
    if dtype != np.dtype("int8"):
        raise ValueError("Expected float32 or int8 input")
    scale, zero = scalar_quantization(detail)
    bounds = np.iinfo(dtype)
    rounded = np.rint(values.astype(np.float64) / scale + zero)
    clipped = int(np.count_nonzero((rounded < bounds.min) | (rounded > bounds.max)))
    return np.clip(rounded, bounds.min, bounds.max).astype(dtype), clipped


def dequantize(values, detail):
    if values.dtype == np.float32:
        return values.copy()
    if values.dtype != np.int8:
        raise ValueError("Expected float32 or int8 activation")
    scale, zero = scalar_quantization(detail)
    return ((values.astype(np.float64) - zero) * scale).astype(np.float32)


def tensor_description(detail):
    params = detail["quantization_parameters"]
    return {
        "index": int(detail["index"]), "name": detail["name"],
        "shape": detail["shape"].tolist(), "dtype": np.dtype(detail["dtype"]).name,
        "logical_value_bytes": int(np.prod(detail["shape"])) * np.dtype(detail["dtype"]).itemsize,
        "scales": params["scales"].tolist(), "zero_points": params["zero_points"].tolist(),
        "quantized_dimension": int(params["quantized_dimension"]),
    }


def operator_inventory(content):
    # Record builtin opcode versions too: desktop success is not Micro support.
    from tensorflow.lite.python import schema_py_generated as schema

    names = {value: name for name, value in vars(schema.BuiltinOperator).items()
             if isinstance(value, int)}
    model = schema.Model.GetRootAsModel(content, 0)
    graph = model.Subgraphs(0)
    counts = Counter()
    for index in range(graph.OperatorsLength()):
        code = model.OperatorCodes(graph.Operators(index).OpcodeIndex())
        builtin = max(code.BuiltinCode(), code.DeprecatedBuiltinCode())
        name = names.get(builtin, str(builtin))
        if code.CustomCode():
            name += ":" + code.CustomCode().decode()
        counts[name, int(code.Version())] += 1
    return [{"name": name, "version": version, "count": count}
            for (name, version), count in sorted(counts.items())]


def convert(tf, model, samples, mode):
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    if mode == "int8":
        converter.optimizations = [tf.lite.Optimize.DEFAULT]
        converter.representative_dataset = lambda: ([sample[None]] for sample in samples)
        converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
        converter.inference_input_type = tf.int8
        converter.inference_output_type = tf.int8
    return converter.convert()


def run_tflite(tf, content, samples, split_layer, expected_boundary_shape):
    interpreter = tf.lite.Interpreter(
        model_content=content, num_threads=1, experimental_preserve_all_tensors=True,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES,
    )
    interpreter.allocate_tensors()
    inputs, outputs = interpreter.get_input_details(), interpreter.get_output_details()
    if len(inputs) != 1 or len(outputs) != 1:
        raise ValueError("This check expects one input and one output")
    details = interpreter.get_tensor_details()
    cuts = [d for d in details if f"/{split_layer}/" in d["name"]
            and tuple(d["shape"]) == tuple(expected_boundary_shape)]
    if len(cuts) != 1:
        raise ValueError(f"Cannot uniquely identify converted boundary {split_layer}: {len(cuts)}")
    boundary = cuts[0]
    predictions, boundaries, rows = [], [], []
    for sample in samples:
        prepared, clipped = prepare_input(sample[None], inputs[0])
        interpreter.set_tensor(inputs[0]["index"], prepared)
        interpreter.invoke()
        output = interpreter.get_tensor(outputs[0]["index"])
        cut = interpreter.get_tensor(boundary["index"])
        predictions.append(dequantize(output, outputs[0])[0])
        boundaries.append(dequantize(cut, boundary)[0])
        rows.append({"input_values_clipped": clipped})
    description = {
        "file_bytes": len(content), "input": tensor_description(inputs[0]),
        "output": tensor_description(outputs[0]), "boundary": tensor_description(boundary),
        "tensor_dtype_counts": dict(Counter(np.dtype(d["dtype"]).name for d in details)),
        "operators": operator_inventory(content),
        "desktop_allocate_and_invoke_passed": True,
        "default_delegates_disabled": True, "preserve_all_tensors": True,
        "timing_and_peak_memory_measured": False,
    }
    return description, np.asarray(predictions), np.asarray(boundaries), rows


def write_report(report, path):
    i8 = report["models"]["int8"]
    lines = [
        "# Fattibilità INT8 del FOMO — prova PC", "",
        ("Conversione post-training senza riaddestramento. Modello intero, non due "
        "sottomodelli distribuiti; nessuna esecuzione ESP32 o misura di latenza/RAM."), "",
        (f"Calibrazione: primi {len(report['dataset']['calibration_indices'])} frame. "
        f"Valutazione: successivi {len(report['dataset']['evaluation_indices'])} frame, "
        "disgiunti ma dallo stesso video e temporalmente correlati. "
        "Non è un dataset indipendente né una misura di accuratezza su annotazioni."), "",
        "| Artefatto | Byte file TFLite | Tipo ingresso/uscita | Byte valori al confine |",
        "|---|---:|---|---:|",
    ]
    for name, model in report["models"].items():
        lines.append(f"| {name} | {model['file_bytes']} | {model['input']['dtype']}/"
                     f"{model['output']['dtype']} | {model['boundary']['logical_value_bytes']} |")
    lines.extend([
        "", (f"Riduzione file INT8 rispetto a TFLite float32: "
        f"{report['tflite_file_size_reduction_percent']:.2f}%. "
        "Il confronto include anche metadati e operatori del file; non usa la dimensione H5."), "",
        "## Fedeltà al modello Keras float32 sui frame di valutazione", "",
        "| Versione | Max errore punteggi | MAE punteggi | Celle cambiate a 0,5 | Perse | Introdotte | Classe cambiata |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for name, model in report["models"].items():
        metrics = model["output_vs_keras"]
        cells = metrics["thresholds"]["0.5"]
        lines.append(f"| {name} | {metrics['max_absolute_error']:.6g} | {metrics['mae']:.6g} | "
                     f"{cells['changed_cells']} / {metrics['cells']} | {cells['lost_foreground_cells']} | "
                     f"{cells['introduced_foreground_cells']} | {cells['foreground_class_changed_cells']} |")
    cells = i8["output_vs_keras"]["thresholds"]["0.5"]
    lines.extend([
        "", (f"Il riferimento ha {cells['reference_foreground_cells']} celle oggetto a soglia 0,5. "
        "Sono celle di griglia, non oggetti distinti o risultati del postprocessing FOMO. "
        "Accordo globale dominato dallo sfondo: leggere anche celle perse/introdotte e IoU "
        "di primo piano nel JSON. Sono conservate anche le soglie 0,25 e 0,75."), "",
        ("Confronto INT8 con TFLite float32, per isolare meglio la quantizzazione: "
        f"max errore punteggi {report['int8_vs_tflite_float32']['max_absolute_error']:.6g}."), "",
        "## Rappresentazione e compatibilità", "",
        (f"Confine osservato nel modello intero: `{i8['boundary']['name']}`, "
        f"forma `{i8['boundary']['shape']}`, scale `{i8['boundary']['scales']}`, "
        f"zero point `{i8['boundary']['zero_points']}`."), "",
        (f"Valori d'ingresso effettivamente tagliati ai limiti INT8: "
        f"{i8['input_values_clipped']} / {i8['input_values_evaluated']}."), "",
        "Operatori INT8: " + ", ".join(f"`{op['name']}` v{op['version']} ({op['count']})"
                                          for op in i8["operators"]) + ".", "",
        (f"Tipi dei tensori del modello INT8: `{i8['tensor_dtype_counts']}`. "
        "Gli int32 servono anche per bias e forme; non sono fallback float. "
        "Conversione integer-only e allocazione/inferenza desktop riuscite."), "",
        ("Questo inventario non certifica il supporto di operatori/versioni nel runtime Micro "
        "del firmware. Servono compilazione, allocazione e Invoke sulla scheda; "
        "ESP-NN non è stato integrato o misurato."), "",
        ("I 4.608 byte al confine sono i soli valori di un tensore INT8 osservato "
        "nel modello intero, non un payload SCIoT già implementato. "
        "Lo split INT8 deve ancora essere esportato e verificato con scale/zero point "
        "coerenti tra prefisso, messaggio e suffisso. Il protocollo corrente assume float32."), "",
        ("L'interprete conserva tutti i tensori per ispezionarli: nessun numero di RAM "
        "o tempo PC è usato per prevedere prestazioni ESP32. La qualità accettabile "
        "per l'applicazione non è stata stabilita."), "",
        "## Prossima decisione", "",
        ("La conversione è fattibile sul PC, ma questa variante non è promossa a baseline "
        "di qualità: valutare le celle perse/introdotte e ampliare la calibrazione con "
        "input rappresentativi separati dalla valutazione, senza cercare parametri sul "
        "campione di test. Non è stata identificata la causa delle variazioni. "
        "La successiva prova minima ESP32 dovrà misurare compatibilità, memoria e tempo reali; "
        "poi confrontare compressione indipendente e temporale sulla rappresentazione scelta. "
        "I precedenti risparmi su float32 non si trasferiscono automaticamente a INT8."), "",
    ])
    path.write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--calibration-frames", type=int, default=48)
    args = parser.parse_args()
    import tensorflow as tf

    source, out = args.input_dir, args.output_dir
    if out.exists() and any(out.iterdir()):
        parser.error("Use an empty output directory to preserve previous runs")
    out.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((source / "result.json").read_text())
    if sha256(source / "model.h5") != metadata["model_sha256"]:
        raise ValueError("Model hash differs from extraction metadata")
    frames = np.load(source / "input_frames.npy", allow_pickle=False)
    if frames.dtype != np.float32 or not np.isfinite(frames).all():
        raise ValueError("Expected finite float32 source frames")
    calibration, evaluation = split_indices(len(frames), args.calibration_frames)
    model = tf.keras.models.load_model(source / "model.h5", compile=False)
    if tuple(frames.shape[1:]) != tuple(model.input_shape[1:]):
        raise ValueError("Input frame shape differs from model")
    split_layer = metadata["split"]["layer"]
    boundary = model.get_layer(split_layer).output
    inspector = tf.keras.Model(model.input, [model.output, boundary])

    @tf.function(input_signature=[tf.TensorSpec([1, *frames.shape[1:]], tf.float32)])
    def keras_run(batch):
        return inspector(batch, training=False)

    reference, cut_reference = [], []
    for sample in frames:
        prediction, cut = keras_run(sample[None])
        reference.append(prediction.numpy()[0])
        cut_reference.append(cut.numpy()[0])
    reference, cut_reference = np.asarray(reference), np.asarray(cut_reference)
    saved = np.load(source / "outputs.npy", allow_pickle=False)
    np.testing.assert_allclose(reference, saved, rtol=1e-5, atol=1e-6)
    report = {
        "created_utc": datetime.now(UTC).isoformat(),
        "scope": "CPU full-model TFLite conversion/evaluation; no training, split deployment, ESP32 or network",
        "environment": {"tensorflow": tf.__version__, "numpy": np.__version__,
                        "python": platform.python_version(), "platform": platform.platform(),
                        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()},
        "source_sha256": {name: sha256(Path(__file__).with_name(name)) for name in
                          ("check_int8.py", "verify_int8.py", "test_int8.py", "compare_lossy.py",
                           "lossy_codec.py", "compare.py")},
        "input_sha256": {name: sha256(source / name) for name in
                         ("model.h5", "input_frames.npy", "outputs.npy", "result.json")},
        "input_metadata": metadata,
        "dataset": {"calibration_indices": calibration.tolist(), "evaluation_indices": evaluation.tolist(),
                    "disjoint_frame_indices": True, "same_video_temporally_correlated": True,
                    "annotated": False, "evaluation_used_for_calibration": False},
        "keras_vs_saved_outputs": error_stats(saved, reference), "models": {},
    }
    thresholds = [0.25, 0.5, 0.75]
    predictions, frame_rows = {}, {}
    for mode in ("float32", "int8"):
        content = convert(tf, model, frames[calibration], mode)
        model_path = out / f"fomo_{mode}.tflite"
        model_path.write_bytes(content)
        info, prediction, cut, rows = run_tflite(
            tf, content, frames[evaluation], split_layer, (1, *cut_reference.shape[1:]))
        if not np.isfinite(prediction).all() or not np.isfinite(cut).all():
            raise ValueError("Nonfinite TFLite output")
        if mode == "int8":
            if info["input"]["dtype"] != "int8" or info["output"]["dtype"] != "int8":
                raise AssertionError("INT8 input/output not obtained")
            if set(info["tensor_dtype_counts"]) - {"int8", "int32"}:
                raise AssertionError("Unexpected noninteger tensor in full INT8 model")
            if any(op["name"].startswith("CUSTOM") or op["name"] == "DEQUANTIZE"
                   for op in info["operators"]):
                raise AssertionError("Unexpected custom/dequantization operator")
        info.update({
            "sha256": sha256(model_path),
            "output_vs_keras": output_stats(reference[evaluation], prediction, thresholds),
            "boundary_vs_keras": error_stats(cut_reference[evaluation], cut),
            "input_values_clipped": sum(row["input_values_clipped"] for row in rows),
            "input_values_evaluated": int(frames[evaluation].size),
            "dequantized_output_sha256": hashlib.sha256(prediction.tobytes()).hexdigest(),
        })
        report["models"][mode] = info
        predictions[mode], frame_rows[mode] = prediction, rows
    report["int8_vs_tflite_float32"] = output_stats(predictions["float32"], predictions["int8"], thresholds)
    report["tflite_file_size_reduction_percent"] = 100 * (
        1 - report["models"]["int8"]["file_bytes"] / report["models"]["float32"]["file_bytes"])
    with (out / "frames.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "mode", "source_frame_index", "max_output_error", "reference_foreground_cells_0.5",
            "changed_cells_0.5", "input_values_clipped"])
        writer.writeheader()
        for mode, prediction in predictions.items():
            before, after = cell_labels(reference[evaluation], .5), cell_labels(prediction, .5)
            for index, original_index in enumerate(evaluation):
                writer.writerow({
                    "mode": mode, "source_frame_index": int(original_index),
                    "max_output_error": float(np.max(np.abs(prediction[index] - reference[original_index]))),
                    "reference_foreground_cells_0.5": int(np.count_nonzero(before[index])),
                    "changed_cells_0.5": int(np.count_nonzero(before[index] != after[index])),
                    **frame_rows[mode][index],
                })
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    write_report(report, out / "report.md")
    print(json.dumps({"models": {name: {"bytes": info["file_bytes"],
                     "output_vs_keras": info["output_vs_keras"]}
                     for name, info in report["models"].items()}}, indent=2))


if __name__ == "__main__":
    main()
