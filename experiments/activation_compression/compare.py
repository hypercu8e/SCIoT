"""Offline lossless comparison; does not change the SCIoT transport or model."""

import argparse
import collections
import csv
import hashlib
import json
import platform
import statistics
import struct
import time
import zlib
from pathlib import Path

import numpy as np

HEADER = struct.Struct("!4sBBHIIII")
NO_REFERENCE = 0xFFFFFFFF
RAW, FULL_ZLIB, DELTA64, XOR, FULL_SHUFFLE, XOR_SHUFFLE = range(6)
METHODS = (
    "raw",
    "full_zlib",
    "delta64_zlib",
    "xor_zlib",
    "full_shuffle_zlib",
    "xor_shuffle_zlib",
)


def shuffle(raw):
    """Group equal byte positions of float32 words; entirely reversible."""
    return np.frombuffer(raw, np.uint8).reshape(-1, 4).T.copy().tobytes()


def unshuffle(raw):
    return np.frombuffer(raw, np.uint8).reshape(4, -1).T.copy().tobytes()


class Encoder:
    def __init__(self, method, refresh_frames, level=1):
        if method not in METHODS or refresh_frames < 1:
            raise ValueError("Invalid codec or refresh interval")
        self.method = method
        self.refresh_frames = refresh_frames
        self.level = level
        self.reference = None
        self.sequence = 0

    def encode(self, raw):
        if len(raw) % 4:
            raise ValueError("Expected float32 words")
        sequence = self.sequence
        refresh = sequence % self.refresh_frames == 0
        kind, payload = RAW, raw
        candidate_bytes = None
        candidate_exact = True
        reordered = "shuffle" in self.method

        if self.method != "raw":
            full = zlib.compress(shuffle(raw) if reordered else raw, self.level)
            if len(full) < len(payload):
                kind = FULL_SHUFFLE if reordered else FULL_ZLIB
                payload = full

        differential = self.method in ("delta64_zlib", "xor_zlib", "xor_shuffle_zlib")
        if differential and not refresh and self.reference is not None:
            if len(raw) != len(self.reference):
                raise ValueError("Tensor changed size; start a new session")
            if self.method == "delta64_zlib":
                current = np.frombuffer(raw, dtype="<f4").astype(np.float64)
                previous = np.frombuffer(self.reference, dtype="<f4").astype(np.float64)
                delta = (current - previous).astype("<f8")
                candidate_exact = (previous + delta).astype("<f4").tobytes() == raw
                residual = delta.tobytes()
                delta_kind = DELTA64
            else:
                residual = np.bitwise_xor(
                    np.frombuffer(raw, np.uint8),
                    np.frombuffer(self.reference, np.uint8),
                ).tobytes()
                delta_kind = XOR_SHUFFLE if reordered else XOR
                if reordered:
                    residual = shuffle(residual)
            compressed_delta = zlib.compress(residual, self.level)
            candidate_bytes = len(compressed_delta)
            # Use a complete frame whenever the delta is larger or not exact.
            if candidate_exact and len(compressed_delta) < len(payload):
                kind, payload = delta_kind, compressed_delta

        reference_sequence = sequence - 1 if kind in (DELTA64, XOR, XOR_SHUFFLE) else NO_REFERENCE
        packet = HEADER.pack(
            b"ACT1", 1, kind, 0, sequence, reference_sequence,
            len(payload), zlib.crc32(raw),
        ) + payload
        self.reference = raw if differential else None
        self.sequence += 1
        return packet, {
            "sequence": sequence,
            "kind": kind,
            "refresh": refresh,
            "delta_candidate_bytes": candidate_bytes,
            "delta_candidate_exact": candidate_exact,
            "payload_bytes": len(payload),
            "packet_bytes": len(packet),
        }


class Decoder:
    def __init__(self, tensor_bytes):
        self.tensor_bytes = tensor_bytes
        self.reference = None
        self.sequence = -1

    def decode(self, packet):
        if len(packet) < HEADER.size:
            raise ValueError("Truncated packet")
        magic, version, kind, flags, sequence, refseq, length, checksum = HEADER.unpack_from(packet)
        if magic != b"ACT1" or version != 1 or flags != 0:
            raise ValueError("Invalid header")
        if kind not in range(6) or length != len(packet) - HEADER.size:
            raise ValueError("Invalid kind or payload length")
        if sequence <= self.sequence:
            raise ValueError("Duplicate or out-of-order packet")
        dependent = kind in (DELTA64, XOR, XOR_SHUFFLE)
        if dependent and (
            self.reference is None or refseq != self.sequence or sequence != refseq + 1
        ):
            raise ValueError("Missing reference: wait for a complete frame")
        if not dependent and refseq != NO_REFERENCE:
            raise ValueError("Unexpected reference on a complete frame")
        payload = packet[HEADER.size:]
        try:
            data = payload if kind == RAW else zlib.decompress(payload)
        except zlib.error as error:
            raise ValueError("Invalid compressed payload") from error
        expected = self.tensor_bytes * 2 if kind == DELTA64 else self.tensor_bytes
        if len(data) != expected:
            raise ValueError("Incorrect decompressed tensor size")
        if kind in (FULL_SHUFFLE, XOR_SHUFFLE):
            data = unshuffle(data)
        if kind in (XOR, XOR_SHUFFLE):
            raw = np.bitwise_xor(
                np.frombuffer(data, np.uint8),
                np.frombuffer(self.reference, np.uint8),
            ).tobytes()
        elif kind == DELTA64:
            previous = np.frombuffer(self.reference, dtype="<f4").astype(np.float64)
            raw = (previous + np.frombuffer(data, dtype="<f8")).astype("<f4").tobytes()
        else:
            raw = data
        if zlib.crc32(raw) != checksum:
            raise ValueError("Reconstructed tensor checksum mismatch")
        self.reference, self.sequence = raw, sequence
        return raw


def benchmark(arrays, method, fps, metadata, rounds):
    shape = arrays.shape[1:]
    tensor_bytes = arrays[0].nbytes
    refresh_frames = max(1, round(5 * fps))
    session = {
        "version": 1, "dtype": "<f4", "shape": list(shape),
        "model_sha256": metadata["model_sha256"],
        "split_layer": metadata["split"]["layer"],
        "sampling_fps": fps, "refresh_frames": refresh_frames,
        "zlib_level": 1, "zlib_window_bits": 15,
    }
    session_json = json.dumps(session, separators=(",", ":"), sort_keys=True).encode()
    session_packet = struct.pack("!4sI", b"ACST", len(session_json)) + session_json
    session_bytes = len(session_packet)
    decoded_session = json.loads(session_packet[8:])
    decoder_tensor_bytes = int(np.prod(decoded_session["shape"])) * np.dtype(decoded_session["dtype"]).itemsize
    assert decoder_tensor_bytes == tensor_bytes
    frames = [frame.astype("<f4", copy=False).tobytes() for frame in arrays]
    encoder_rounds, decoder_rounds = [], []
    last_rows = []
    for _ in range(rounds):
        encoder = Encoder(method, refresh_frames)
        decoder = Decoder(decoder_tensor_bytes)
        encode_ns, decode_ns, rows = [], [], []
        for raw in frames:
            start = time.perf_counter_ns()
            packet, row = encoder.encode(raw)
            encode_ns.append(time.perf_counter_ns() - start)
            start = time.perf_counter_ns()
            restored = decoder.decode(packet)
            decode_ns.append(time.perf_counter_ns() - start)
            if restored != raw:
                raise AssertionError("Lossless round trip failed")
            row.update(method=method, sampling_fps=fps)
            rows.append(row)
        encoder_rounds.append(sum(encode_ns) / len(frames) / 1e6)
        decoder_rounds.append(sum(decode_ns) / len(frames) / 1e6)
        last_rows = rows
    total = session_bytes + sum(r["packet_bytes"] for r in last_rows)
    raw_total = session_bytes + len(frames) * (HEADER.size + tensor_bytes)
    summary = {
        "method": method, "sampling_fps": fps, "frames": len(frames),
        "raw_tensor_bytes_per_frame": tensor_bytes,
        "session_header_bytes": session_bytes,
        "frame_header_bytes": HEADER.size,
        "payload_bytes": sum(r["payload_bytes"] for r in last_rows),
        "total_bytes": total,
        "mean_bytes_per_frame_including_session": total / len(frames),
        "saving_vs_raw_percent": 100 * (1 - total / raw_total),
        "selected_delta_frames": sum(r["kind"] in (DELTA64, XOR, XOR_SHUFFLE) for r in last_rows),
        "scheduled_refresh_frames": sum(r["refresh"] for r in last_rows),
        "full_frames": sum(r["kind"] not in (DELTA64, XOR, XOR_SHUFFLE) for r in last_rows),
        "candidate_delta_frames": sum(r["delta_candidate_bytes"] is not None for r in last_rows),
        "mean_candidate_delta_bytes": statistics.mean(
            r["delta_candidate_bytes"] for r in last_rows if r["delta_candidate_bytes"] is not None
        ) if any(r["delta_candidate_bytes"] is not None for r in last_rows) else None,
        "kind_counts": dict(collections.Counter(r["kind"] for r in last_rows)),
        "encoder_ms_per_frame_median_round_mean": statistics.median(encoder_rounds),
        "decoder_ms_per_frame_median_round_mean": statistics.median(decoder_rounds),
        "minimum_persistent_reference_bytes_per_side": tensor_bytes if "delta" in method or "xor" in method else 0,
        "roundtrip_bit_exact_all_frames_all_rounds": True,
    }
    return summary, last_rows


def float32_subtraction_diagnostic(arrays):
    reference = arrays[:-1]
    restored = (reference + (arrays[1:] - reference)).astype("<f4")
    expected = arrays[1:].astype("<f4")
    return {
        "value_count": expected.size,
        "different_float32_words": int(np.count_nonzero(restored.view("<u4") != expected.view("<u4"))),
        "max_absolute_reconstruction_error": float(np.max(np.abs(restored.astype(np.float64) - expected))),
        "scope": "one-step subtraction/addition with original previous frame; not a predictive codec",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds must be positive")
    metadata = json.loads((args.input_dir / "result.json").read_text())
    model_path = args.input_dir / "model.h5"
    metadata["model_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
    data_path = args.input_dir / "activations.npy"
    arrays = np.load(data_path, allow_pickle=False)
    if arrays.dtype != np.float32 or arrays.ndim != 4 or len(arrays) < 2 or not np.isfinite(arrays).all():
        raise ValueError("Expected at least two finite float32 activation tensors")
    if list(arrays.shape[1:]) != metadata["split"]["activation_shape_without_batch"]:
        raise ValueError("Activation shape disagrees with metadata")
    if metadata["preprocessing"]["sampling_fps"] != 5:
        raise ValueError("This first comparison expects extraction at 5 fps")
    summaries, rows, diagnostics = [], [], {}
    for stride in (1, 5):
        sample = arrays[::stride]
        fps = 5 / stride
        diagnostics[str(fps)] = float32_subtraction_diagnostic(sample)
        for method in METHODS:
            summary, frame_rows = benchmark(sample, method, fps, metadata, args.rounds)
            summaries.append(summary)
            rows.extend(frame_rows)
            print(f'{fps:g} fps {method:24s} {summary["total_bytes"]:9d} bytes '
                  f'{summary["saving_vs_raw_percent"]:6.2f}% saved '
                  f'{summary["selected_delta_frames"]} delta frames')
    report = {
        "input_activation_file_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "input_video_sha256": metadata["video_sha256"],
        "model_sha256": metadata["model_sha256"],
        "split": metadata["split"],
        "platform": {"python": platform.python_version(), "machine": platform.machine(),
                     "numpy": np.__version__, "zlib": zlib.ZLIB_RUNTIME_VERSION},
        "rounds": args.rounds, "results": summaries,
        "float32_subtraction_diagnostic": diagnostics,
        "limitations": [
            "One video and one split; descriptive measurements, not general performance evidence.",
            "Application stream bytes include session, packet headers, zlib wrappers, checksums, and refreshes.",
            "TCP/IP, Wi-Fi, MQTT/HTTP/WebSocket overhead, retries, and connection setup are not measured.",
            "Python CPU codec timings exclude tensor extraction, inference, input/output files, and network.",
            "Persistent reference size excludes codec workspace, temporary arrays, and interpreter memory.",
            "Decoder is checked against original bytes for every frame in every round; no quantization.",
            "XOR is a bitwise residual, not arithmetic subtraction of activation values.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    with (args.output_dir / "frames.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# Confronto senza perdita sul video", "", "Byte del flusso applicativo; verifica byte per byte superata.", ""]
    for fps in (5.0, 1.0):
        lines += [f"## {fps:g} frame al secondo", "", "| Metodo | Byte totali | Risparmio sul completo | Delta scelti | Encode ms/frame PC | Decode ms/frame PC |", "|---|---:|---:|---:|---:|---:|"]
        for item in summaries:
            if item["sampling_fps"] == fps:
                lines.append(f'| {item["method"]} | {item["total_bytes"]:,} | {item["saving_vs_raw_percent"]:.2f}% | {item["selected_delta_frames"]} | {item["encoder_ms_per_frame_median_round_mean"]:.3f} | {item["decoder_ms_per_frame_median_round_mean"]:.3f} |')
        lines.append("")
    lines += ["## Limiti", ""] + [f"- {s}" for s in report["limitations"]]
    (args.output_dir / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
