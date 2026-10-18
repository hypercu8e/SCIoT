"""Compare independent/temporal coding at IDENTICAL quantized reconstruction.

CPU-only, offline Keras experiment. No training, target emulation or networking.
"""

import argparse
import csv
import hashlib
import json
import os
import platform
import statistics
import subprocess
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from compare import HEADER, benchmark as benchmark_lossless
from lossy_codec import DELTA_COMPRESSED, Decoder, Encoder, Session, quantize, reconstruct


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def error_stats(expected, actual):
    error = actual.astype(np.float64) - expected.astype(np.float64)
    rmse = float(np.sqrt(np.mean(error**2)))
    std = float(np.std(expected.astype(np.float64)))
    return {
        "mae": float(np.mean(np.abs(error))), "rmse": rmse,
        "max_absolute_error": float(np.max(np.abs(error))),
        "normalized_rmse_by_reference_std": rmse / std if std else None,
    }


def cell_labels(outputs, threshold):
    # Grid proxy: strongest foreground class above threshold, else background.
    # Looking at foreground scores also makes thresholds below 1/3 informative.
    foreground = outputs[..., 1:]
    labels = np.argmax(foreground, axis=-1) + 1
    return np.where(np.max(foreground, axis=-1) >= threshold, labels, 0)


def output_stats(expected, actual, thresholds):
    result = error_stats(expected, actual)
    result["argmax_changed_cells"] = int(np.count_nonzero(
        np.argmax(expected, axis=-1) != np.argmax(actual, axis=-1)))
    result["cells"] = int(np.prod(expected.shape[:-1]))
    result["thresholds"] = {}
    for threshold in thresholds:
        before, after = cell_labels(expected, threshold), cell_labels(actual, threshold)
        foreground_union = (before != 0) | (after != 0)
        intersection = (before != 0) & (before == after)
        union_count = int(np.count_nonzero(foreground_union))
        changed = int(np.count_nonzero(before != after))
        result["thresholds"][str(threshold)] = {
            "reference_foreground_cells": int(np.count_nonzero(before)),
            "reconstructed_foreground_cells": int(np.count_nonzero(after)),
            "changed_cells": changed,
            "agreement_percent": 100 * (1 - changed / before.size),
            "lost_foreground_cells": int(np.count_nonzero((before != 0) & (after == 0))),
            "introduced_foreground_cells": int(np.count_nonzero((before == 0) & (after != 0))),
            "foreground_class_changed_cells": int(np.count_nonzero(
                (before != 0) & (after != 0) & (before != after))),
            # No objects in either output is uninformative, not a perfect IoU.
            "foreground_label_cell_iou": int(np.count_nonzero(intersection)) / union_count
            if union_count else None,
        }
    return result


def benchmark_lossy(arrays, method, step, fps, metadata, rounds):
    session = Session(
        tuple(arrays.shape[1:]), step, method, max(1, round(5 * fps)),
        metadata["model_sha256"], metadata["split"]["layer"], fps,
    )
    session_packet = session.to_packet()
    expected = quantize(arrays, step)
    expected_reconstruction = reconstruct(expected, step)
    encode_means, decode_means = [], []
    for iteration in range(rounds):
        encoder, decoder = Encoder(session), Decoder(Session.from_packet(session_packet))
        encode_ns, decode_ns, rows, restored_frames = [], [], [], []
        for frame_index, frame in enumerate(arrays):
            start = time.perf_counter_ns()
            packet, row = encoder.encode(frame)
            encode_ns.append(time.perf_counter_ns() - start)
            start = time.perf_counter_ns()
            integer_raw, restored = decoder.decode(packet)
            decode_ns.append(time.perf_counter_ns() - start)
            if integer_raw != expected[frame_index].tobytes():
                raise AssertionError("Decoded integers differ from quantizer output")
            if restored.tobytes() != expected_reconstruction[frame_index].tobytes():
                raise AssertionError("Decoded float32 reconstruction differs")
            if method == "temporal" and encoder.reference != decoder.reference:
                raise AssertionError("Encoder/decoder references diverged")
            row.update(
                method=method, step=step, sampling_fps=fps,
                source_frame_index=frame_index * round(5 / fps),
                encode_ms=encode_ns[-1] / 1e6, decode_ms=decode_ns[-1] / 1e6,
            )
            rows.append(row)
            if iteration == 0:
                restored_frames.append(restored)
        if iteration == 0:
            first_reconstruction = np.asarray(restored_frames, dtype="<f4")
        encode_means.append(statistics.mean(encode_ns) / 1e6)
        decode_means.append(statistics.mean(decode_ns) / 1e6)
    total = len(session_packet) + sum(row["packet_bytes"] for row in rows)
    delta_zero_fractions = [row["zero_delta_fraction"] for row in rows
                            if row["zero_delta_fraction"] is not None]
    return {
        "method": method, "step": step, "sampling_fps": fps, "frames": len(arrays),
        "session_header_bytes": len(session_packet), "frame_header_bytes": HEADER.size,
        "payload_bytes": sum(row["payload_bytes"] for row in rows), "total_bytes": total,
        "mean_bytes_per_frame_including_session": total / len(arrays),
        "selected_delta_frames": sum(row["kind"] == DELTA_COMPRESSED for row in rows),
        "full_frames": sum(row["kind"] != DELTA_COMPRESSED for row in rows),
        "scheduled_refresh_frames": sum(row["scheduled_refresh"] for row in rows)
        if method == "temporal" else None,
        "mean_zero_delta_fraction_on_candidate_frames": statistics.mean(delta_zero_fractions)
        if delta_zero_fractions else None,
        "encoder_ms_per_frame_median_round_mean": statistics.median(encode_means),
        "decoder_ms_per_frame_median_round_mean": statistics.median(decode_means),
        "minimum_persistent_reference_bytes_per_side": arrays[0].nbytes
        if method == "temporal" else 0,
        "integer_roundtrip_and_shared_reference_all_frames_all_rounds": True,
        "reconstruction_sha256": hashlib.sha256(first_reconstruction.tobytes()).hexdigest(),
    }, rows, first_reconstruction


def predict_suffix(tf, suffix, arrays):
    @tf.function(input_signature=[tf.TensorSpec([None, *arrays.shape[1:]], tf.float32)])
    def run(batch):
        return suffix(batch, training=False)

    outputs = np.concatenate([run(batch).numpy() for batch in
                              (arrays[i:i + 16] for i in range(0, len(arrays), 16))])
    if not np.isfinite(outputs).all():
        raise AssertionError("Nonfinite model output")
    return outputs


def write_report(report, path):
    lines = [
        "# Prima prova con perdita controllata", "",
        f"Eseguita il {report['created_utc']} su CPU PC; nessuna emulazione ESP32.", "",
        "## Metodo", "",
        "`q = rint(attivazione / passo)`, interi int32 senza clipping; "
        "ricostruzione `float32(q * passo)`. Arrotondamento al più vicino, parità ai pareggi.",
        "Indipendente: intero tensore q. Temporale: differenza intera q corrente - q precedente.",
        "Entrambi usano byte shuffle e zlib livello 1 e ricostruiscono gli stessi float32 a ogni passo.",
        "Completo iniziale e ogni 5 secondi; tra i rinnovi scelta del payload minore "
        "tra completo e differenza. Fallback raw se comprimere il completo espande i dati.",
        "Sono conteggiati sessione AQST, 24 byte AQF1 per frame, wrapper zlib e rinnovi. "
        "CRC sugli interi ricostruiti. Il formato non è integrato in SCIoT.", "",
        "Il riferimento per le metriche di uscita è il suffisso sulle attivazioni originali, "
        "eseguito con gli stessi batch delle ricostruzioni. Il suo confronto con le uscite "
        "del modello intero salvate nell'estrazione è verificato con rtol=1e-5, atol=1e-6; "
        "le piccole differenze numeriche di esecuzione sono registrate nel JSON.", "",
        "## Controlli senza perdita sulla stessa macchina", "",
        "Tempi nuovi, separati dalla baseline storica del 15 ottobre. "
        "Tempi lossless senza conversione iniziale float32/byte; "
        "tempi lossy includono quantizzazione e ricostruzione float32, quindi ambiti diversi.", "",
        "| fps | Metodo | Byte totali | Encode ms/frame PC | Decode ms/frame PC |",
        "|---:|---|---:|---:|---:|",
    ]
    for row in report["lossless_controls"]:
        lines.append(f"| {row['sampling_fps']:g} | {row['method']} | {row['total_bytes']} | "
                     f"{row['encoder_ms_per_frame_median_round_mean']:.3f} | "
                     f"{row['decoder_ms_per_frame_median_round_mean']:.3f} |")
    for fps in (5.0, 1.0):
        lines.extend([
            "", f"## Risultati a {fps:g} fps", "",
            "Una riga per passo: le due codifiche hanno ricostruzioni identiche. "
            "Errore uscita e celle cambiate si riferiscono al modello originale, non a etichette corrette.", "",
            "| Passo | Byte indip. | Byte temp. | Risparmio temp./indip. | "
            "Risparmio temp./raw | Max errore attiv. | Max errore uscita | Celle cambiate a 0,5 |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for row in report["results"]:
            if row["sampling_fps"] != fps or row["method"] != "temporal":
                continue
            independent = next(r for r in report["results"] if r["sampling_fps"] == fps
                               and r["step"] == row["step"] and r["method"] == "independent")
            lines.append(
                f"| {row['step']:g} | {independent['total_bytes']} | {row['total_bytes']} | "
                f"{row['saving_vs_independent_same_step_percent']:.2f}% | "
                f"{row['saving_vs_raw_percent']:.2f}% | "
                f"{row['activation_error']['max_absolute_error']:.6g} | "
                f"{row['output_error']['max_absolute_error']:.6g} | "
                f"{row['output_error']['thresholds']['0.5']['changed_cells']} |")
        baseline = report["reference_output"][str(fps)]
        lines.extend([
            "", f"Celle oggetto nel riferimento a soglia 0,5: "
            f"**{baseline['thresholds']['0.5']['reference_foreground_cells']}** "
            f"su {baseline['cells']} celle. Sono celle di griglia, non oggetti distinti.",
        ])
    lines.extend([
        "", "## Interpretazione e limiti", "",
        "- Errore sulle attivazioni limitato dal passo/2, più arrotondamento numerico float32; "
        "il limite è controllato su tutti i valori. Nessuna saturazione o errore accumulato nel riferimento.",
        "- Nessuna soglia di errore sull'uscita è stata concordata come accettabile. "
        "Le tabelle descrivono un compromesso, non selezionano una configurazione sicura.",
        "- Le metriche di griglia scelgono la classe oggetto col punteggio maggiore "
        "tra i canali 1 e 2, se raggiunge la soglia; altrimenti sfondo. "
        "Argmax sui tre canali è riportato separatamente nel JSON. "
        "Sono proxy: non applicano il postprocessing FOMO a componenti connesse "
        "né conteggiano oggetti distinti.",
        "- Soglia 0,5 primaria; 0,25 e 0,1 sono analisi di sensibilità, "
        "senza modificare il modello. JSON con MAE, RMSE, max errore, "
        "celle perse/introdotte e cambi di classe. IoU null se non ci sono celle oggetto nell'unione.",
        "- Accordo con il modello originale non equivale ad accuratezza: mancano annotazioni. "
        "Molte celle di sfondo possono rendere l'accordo poco informativo.",
        "- Un video, un modello e uno split; passi scelti per esplorare, "
        "senza insieme separato di calibrazione/validazione. Nessun riaddestramento.",
        "- Quantizzazione del messaggio intermedio; la rete resta float32. "
        "Non è una conversione del modello in INT8.",
        "- Tempi: mediana delle medie per frame su tre ripetizioni di default; "
        "includono selezione adattiva e CRC, escludono inferenza, verifiche contro "
        "l'originale, file e rete. Non stimano i tempi ESP32.",
        "- Riferimento temporale int32: 18.432 byte per lato per questo split. "
        "Il dato esclude workspace zlib, tensori temporanei, modello e runtime; "
        "non è una misura del picco RAM. Nessuna misura di energia o rete reale.",
        "", "## Artefatti", "",
        "- `summary.json`: protocollo, parametri, hash, ambiente, misure e metriche complete.",
        "- `frames.csv`: dimensioni, modalità scelta e diagnostica di ciascun frame; "
        "tempi della sola ultima ripetizione, mentre i riepiloghi usano la mediana delle medie.",
        "- I tensori originali si rigenerano con `extract_activations.py`; "
        "le ricostruzioni quantizzate sono deterministiche e identificate da SHA-256.", "",
    ])
    path.write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", nargs="+", type=float,
                        default=[0.0001, 0.001, 0.01, 0.1, 0.5, 1.0])
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if args.rounds < 1 or len(set(args.steps)) != len(args.steps):
        parser.error("Positive rounds and distinct quantization steps required")
    if (args.output_dir / "summary.json").exists():
        parser.error("Output already contains a summary; choose a new output directory")
    # Set before importing TensorFlow; no GPU or architecture emulation.
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    import tensorflow as tf

    tf.config.threading.set_intra_op_parallelism_threads(1)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    metadata = json.loads((args.input_dir / "result.json").read_text())
    if metadata["preprocessing"]["sampling_fps"] != 5:
        parser.error("This experiment requires extraction at 5 fps")
    model_path = args.input_dir / "model.h5"
    if sha256(model_path) != metadata["model_sha256"]:
        raise ValueError("Model hash disagrees with extraction metadata")
    arrays = np.load(args.input_dir / "activations.npy", allow_pickle=False)
    original_outputs = np.load(args.input_dir / "outputs.npy", allow_pickle=False)
    if (arrays.dtype != np.float32 or arrays.ndim != 4 or len(arrays) < 2
            or list(arrays.shape[1:]) != metadata["split"]["activation_shape_without_batch"]
            or not np.isfinite(arrays).all()):
        raise ValueError("Invalid activation input")
    if (len(original_outputs) != len(arrays) or original_outputs.shape[1:] != (12, 12, 3)
            or not np.isfinite(original_outputs).all()):
        raise ValueError("Expected finite FOMO 12x12x3 outputs for every frame")
    for step in args.steps:
        quantize(arrays, step)  # Validate every step before starting measurements.
    model = tf.keras.models.load_model(model_path, compile=False)
    suffix = tf.keras.Model(model.get_layer(metadata["split"]["layer"]).output, model.output)
    suffix_control = predict_suffix(tf, suffix, arrays)
    np.testing.assert_allclose(suffix_control, original_outputs, rtol=1e-5, atol=1e-6)
    thresholds = [0.5, 0.25, 0.1]
    controls, results, frame_rows, reference = [], [], [], {}
    for stride in (1, 5):
        sample, fps = arrays[::stride], 5.0 / stride
        reference[str(fps)] = output_stats(suffix_control[::stride], suffix_control[::stride], thresholds)
        for method in ("raw", "full_shuffle_zlib", "xor_shuffle_zlib"):
            control, _ = benchmark_lossless(sample, method, fps, metadata, args.rounds)
            controls.append(control)
    for step in args.steps:
        expected_reconstruction = reconstruct(quantize(arrays, step), step)
        difference = np.abs(expected_reconstruction.astype(np.float64) - arrays)
        allowance = step / 2 + np.finfo(np.float32).eps * np.abs(expected_reconstruction.astype(float))
        allowance += np.finfo(np.float64).eps * np.abs(arrays.astype(float)) * 4
        if np.any(difference > allowance):
            raise AssertionError("Quantization error exceeds the stated bound")
        quantized_outputs = predict_suffix(tf, suffix, expected_reconstruction)
        for stride in (1, 5):
            sample, fps = arrays[::stride], 5.0 / stride
            raw_total = next(c["total_bytes"] for c in controls
                             if c["method"] == "raw" and c["sampling_fps"] == fps)
            independent = None
            for method in ("independent", "temporal"):
                row, rows, restored = benchmark_lossy(sample, method, step, fps, metadata, args.rounds)
                if restored.tobytes() != expected_reconstruction[::stride].tobytes():
                    raise AssertionError("Independent and temporal reconstruction differ")
                row["activation_error"] = error_stats(sample, restored)
                row["output_error"] = output_stats(
                    suffix_control[::stride], quantized_outputs[::stride], thresholds)
                row["activation_error_bound_checked_all_values"] = True
                row["saving_vs_raw_percent"] = 100 * (1 - row["total_bytes"] / raw_total)
                if method == "independent":
                    independent = row
                else:
                    row["saving_vs_independent_same_step_percent"] = 100 * (
                        1 - row["total_bytes"] / independent["total_bytes"])
                    assert row["reconstruction_sha256"] == independent["reconstruction_sha256"]
                for frame_index, frame_row in enumerate(rows):
                    frame_row["activation_max_absolute_error"] = float(np.max(difference[::stride][frame_index]))
                    frame_row["output_max_absolute_error"] = float(np.max(np.abs(
                        quantized_outputs[::stride][frame_index].astype(float)
                        - suffix_control[::stride][frame_index])))
                frame_rows.extend(rows)
                results.append(row)
                print(f"step={step:g} {fps:g} fps {method:11s} {row['total_bytes']} bytes "
                      f"{row['saving_vs_raw_percent']:.2f}% vs raw", flush=True)
    tracked_sources = [Path(__file__), Path(__file__).with_name("lossy_codec.py"),
                       Path(__file__).with_name("compare.py"),
                       Path(__file__).with_name("extract_activations.py")]
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "git_head_at_run": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_sha256": {p.name: sha256(p) for p in tracked_sources},
        "input_sha256": {name: sha256(args.input_dir / name) for name in
                         ("activations.npy", "outputs.npy", "result.json", "model.h5")},
        "input_metadata": metadata,
        "platform": {"python": platform.python_version(), "platform": platform.platform(),
                     "processor": platform.processor(), "numpy": np.__version__,
                     "tensorflow": tf.__version__, "zlib": zlib.ZLIB_RUNTIME_VERSION,
                     "tensorflow_intra_op_threads": 1, "tensorflow_inter_op_threads": 1,
                     "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"]},
        "activation_statistics": {"min": float(arrays.min()), "max": float(arrays.max()),
                                  "std": float(arrays.std()), "frames": len(arrays)},
        "parameters": {"steps": args.steps, "rounds": args.rounds,
                       "primary_cell_threshold": 0.5, "sensitivity_thresholds": [0.25, 0.1],
                       "output_reference": "suffix on unquantized activations, same batch size (16)",
                       "quantization": "rint(float64(x)/step) to signed little-endian int32; no clipping",
                       "reconstruction": "float32(float64(q)*step)",
                       "temporal": "exact signed int32 difference of quantized tensors",
                       "refresh_seconds": 5, "zlib_level": 1, "zlib_window_bits": 15,
                       "zlib_mem_level": 8, "frame_header_bytes": HEADER.size},
        "suffix_control_vs_original_output": error_stats(original_outputs, suffix_control),
        "reference_output": reference, "lossless_controls": controls, "results": results,
        "scope": "offline PC Keras; one video/split; no annotations, network, energy or ESP32 measurements",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    with (args.output_dir / "frames.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(frame_rows[0]))
        writer.writeheader()
        writer.writerows(frame_rows)
    write_report(report, args.output_dir / "report.md")


if __name__ == "__main__":
    main()
