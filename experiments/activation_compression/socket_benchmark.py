"""Replay recorded activations over TCP to a separate Keras suffix server.

Isolated CPU experiment: no changes to SCIoT's firmware or wire protocol.
"""

import argparse
import csv
import hashlib
import json
import os
import platform
import socket
import struct
import subprocess
import sys
import time
import zlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from compare import HEADER, NO_REFERENCE, RAW
from compare_lossy import output_stats
from lossy_codec import (
    DELTA_COMPRESSED,
    Decoder,
    Encoder,
    Session,
    quantize,
    reconstruct,
)

LENGTH = struct.Struct("!I")
ACK = struct.Struct("!4sIQQ32s")  # sequence, decode ns, inference ns, tensor SHA256
MAX_MESSAGE = 4 * 1024 * 1024
PROTOCOL = "activation-tcp-v1"
METHODS = ("raw", "independent", "temporal")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def receive_exact(connection, size):
    result = bytearray()
    while len(result) < size:
        chunk = connection.recv(size - len(result))
        if not chunk:
            raise EOFError("Connection closed before message completion")
        result.extend(chunk)
    return bytes(result)


def send_message(connection, data):
    if not 0 < len(data) <= MAX_MESSAGE:
        raise ValueError("Message outside experimental size limit")
    connection.sendall(LENGTH.pack(len(data)) + data)
    return LENGTH.size + len(data)


def receive_message(connection):
    size = LENGTH.unpack(receive_exact(connection, LENGTH.size))[0]
    if not 0 < size <= MAX_MESSAGE:
        raise ValueError("Message outside experimental size limit")
    return receive_exact(connection, size)


def json_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class WireCodec:
    """Keep existing AQST/AQF1 compression and use ACT1 raw as the control."""

    def __init__(self, session, method):
        if method not in METHODS or (method != "raw" and session.method != method):
            raise ValueError("Method disagrees with codec session")
        if session.tensor_bytes > MAX_MESSAGE - HEADER.size:
            raise ValueError("Tensor exceeds experimental size limit")
        self.session, self.method = session, method
        self.encoder, self.decoder = Encoder(session), Decoder(session)
        self.sent_sequence, self.received_sequence = 0, -1

    def encode(self, frame):
        if self.method != "raw":
            return self.encoder.encode(frame)
        if frame.shape != self.session.shape or frame.dtype != np.float32:
            raise ValueError("Invalid raw activation shape or dtype")
        if not np.isfinite(frame).all():
            raise ValueError("Nonfinite raw activations")
        raw = frame.astype("<f4", copy=False).tobytes()
        sequence = self.sent_sequence
        packet = HEADER.pack(b"ACT1", 1, RAW, 0, sequence, NO_REFERENCE,
                             len(raw), zlib.crc32(raw)) + raw
        self.sent_sequence += 1
        return packet, {"sequence": sequence, "kind": RAW}

    def decode(self, packet):
        if len(packet) < HEADER.size:
            raise ValueError("Truncated frame")
        fields = HEADER.unpack_from(packet)
        sequence, kind = fields[4], fields[2]
        # TCP is ordered and reliable; missing application messages are errors.
        if sequence != self.received_sequence + 1:
            raise ValueError("Nonconsecutive frame sequence")
        if self.received_sequence == -1 and kind == DELTA_COMPRESSED:
            raise ValueError("A connection must start with a complete frame")
        if self.method == "raw":
            raw = packet[HEADER.size:]
            expected = (b"ACT1", 1, RAW, 0, sequence, NO_REFERENCE,
                        self.session.tensor_bytes, zlib.crc32(raw))
            if fields != expected or len(raw) != self.session.tensor_bytes:
                raise ValueError("Invalid raw frame or checksum")
            frame = np.frombuffer(raw, dtype="<f4").reshape(self.session.shape)
            if not np.isfinite(frame).all():
                raise ValueError("Nonfinite raw activations")
        else:
            _, frame = self.decoder.decode(packet)
        self.received_sequence = sequence
        return sequence, frame


def serve_connection(connection, model_hash, split_layer, shape, predict):
    hello_packet = receive_message(connection)
    hello = json.loads(hello_packet)
    if hello["protocol"] != PROTOCOL:
        raise ValueError("Unsupported transport protocol")
    session = Session.from_packet(bytes.fromhex(hello["codec_session_hex"]))
    if (session.model_sha256 != model_hash or session.split_layer != split_layer
            or session.shape != tuple(shape)):
        raise ValueError("Model, split or tensor shape disagrees with server")
    codec = WireCodec(session, hello["method"])
    send_message(connection, json_bytes({"protocol": PROTOCOL, "ready": True}))
    while True:
        # An empty connection at the next message boundary is normal shutdown.
        if not connection.recv(1, socket.MSG_PEEK):
            return
        packet = receive_message(connection)
        start = time.perf_counter_ns()
        sequence, frame = codec.decode(packet)
        decode_ns = time.perf_counter_ns() - start
        start = time.perf_counter_ns()
        output = np.asarray(predict(frame), dtype="<f4")
        inference_ns = time.perf_counter_ns() - start
        if not np.isfinite(output).all():
            raise ValueError("Nonfinite suffix output")
        # Hashing/response serialization are outside decode and inference timing,
        # but inside the round trip measured by the client.
        response = ACK.pack(b"ACK1", sequence, decode_ns, inference_ns,
                            hashlib.sha256(frame.tobytes()).digest()) + output.tobytes()
        send_message(connection, response)


def load_predictor(model_path, split_layer):
    import tensorflow as tf

    tf.config.threading.set_intra_op_parallelism_threads(1)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    model = tf.keras.models.load_model(model_path, compile=False)
    cut = model.get_layer(split_layer)
    index = model.layers.index(cut)
    before = {layer.name for layer in model.layers[:index + 1]}
    frontier = {tensor._keras_history.layer.name
                for layer in model.layers[index + 1:]
                for tensor in tf.nest.flatten(layer.input)
                if tensor._keras_history.layer.name in before}
    if frontier != {cut.name}:
        raise ValueError(f"Split requires multiple boundary tensors: {frontier}")
    suffix = tf.keras.Model(cut.output, model.output)
    shape = tuple(int(n) for n in cut.output.shape[1:])

    @tf.function(input_signature=[tf.TensorSpec([1, *shape], tf.float32)])
    def run(batch):
        return suffix(batch, training=False)

    def predict(frame):
        return run(frame[None]).numpy()[0]

    predict(np.zeros(shape, dtype=np.float32))  # tracing/warmup outside frame timing
    return shape, predict, tf.__version__


def server(args):
    shape, predict, tensorflow_version = load_predictor(args.model, args.split_layer)
    model_hash = digest(args.model.read_bytes())
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.host, args.port))
        listener.listen(4)
        listener.settimeout(args.timeout)
        ready = {"host": args.host, "port": listener.getsockname()[1],
                 "pid": os.getpid(), "model_sha256": model_hash, "shape": shape,
                 "tensorflow": tensorflow_version}
        if args.ready_file:
            temporary = args.ready_file.with_suffix(".tmp")
            temporary.write_bytes(json_bytes(ready))
            temporary.replace(args.ready_file)
        print(json.dumps(ready), flush=True)
        count = 0
        while not args.max_connections or count < args.max_connections:
            connection, _ = listener.accept()
            with connection:
                connection.settimeout(args.timeout)
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                try:
                    serve_connection(connection, model_hash, args.split_layer, shape, predict)
                except (ValueError, KeyError, TypeError, EOFError, OSError) as error:
                    print(f"Rejected connection: {error}", file=sys.stderr, flush=True)
            count += 1


def load_inputs(input_dir):
    metadata = json.loads((input_dir / "result.json").read_text())
    arrays = np.load(input_dir / "activations.npy", allow_pickle=False)
    outputs = np.load(input_dir / "outputs.npy", allow_pickle=False)
    if (arrays.dtype != np.float32 or arrays.ndim != 4 or len(arrays) < 2
            or not np.isfinite(arrays).all()
            or list(arrays.shape[1:]) != metadata["split"]["activation_shape_without_batch"]
            or outputs.dtype != np.float32 or len(outputs) != len(arrays)
            or not np.isfinite(outputs).all()):
        raise ValueError("Input arrays disagree with extraction metadata")
    if digest((input_dir / "model.h5").read_bytes()) != metadata["model_sha256"]:
        raise ValueError("Model hash disagrees with extraction metadata")
    return metadata, arrays, outputs


def replay(host, port, arrays, metadata, method, step, reconnect_at, timeout=30):
    session = Session(tuple(arrays.shape[1:]), step,
                      "independent" if method == "raw" else method,
                      max(1, round(5 * metadata["preprocessing"]["sampling_fps"])),
                      metadata["model_sha256"], metadata["split"]["layer"],
                      metadata["preprocessing"]["sampling_fps"])
    expected = arrays if method == "raw" else reconstruct(quantize(arrays, step), step)
    connection, rows, outputs = None, [], []
    sent_bytes = received_bytes = connections = handshake_sent = handshake_received = 0
    connection_setup_ms = []
    try:
        for index, frame in enumerate(arrays):
            new_connection = index == 0 or index == reconnect_at
            if new_connection:
                if connection is not None:
                    connection.close()
                start = time.perf_counter_ns()
                connection = socket.create_connection((host, port), timeout=timeout)
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                codec = WireCodec(session, method)  # reset both sequence and reference
                hello = json_bytes({"protocol": PROTOCOL, "method": method,
                                    "codec_session_hex": session.to_packet().hex()})
                count = send_message(connection, hello)
                sent_bytes += count
                handshake_sent += count
                reply = receive_message(connection)
                received_bytes += LENGTH.size + len(reply)
                handshake_received += LENGTH.size + len(reply)
                if json.loads(reply) != {"protocol": PROTOCOL, "ready": True}:
                    raise ValueError("Server did not accept session")
                connection_setup_ms.append((time.perf_counter_ns() - start) / 1e6)
                connections += 1
            start = time.perf_counter_ns()
            packet, info = codec.encode(frame)
            encoded = time.perf_counter_ns()
            sent = send_message(connection, packet)
            reply = receive_message(connection)
            finished = time.perf_counter_ns()
            if len(reply) < ACK.size:
                raise ValueError("Truncated server acknowledgement")
            magic, sequence, decode_ns, inference_ns, frame_hash = ACK.unpack_from(reply)
            if (magic != b"ACK1" or sequence != info["sequence"]
                    or frame_hash.hex() != digest(expected[index].astype("<f4").tobytes())):
                raise AssertionError("Server reconstructed a different tensor")
            output = np.frombuffer(reply[ACK.size:], dtype="<f4").copy()
            if not len(output) or not np.isfinite(output).all():
                raise ValueError("Invalid server output")
            received = LENGTH.size + len(reply)
            sent_bytes += sent
            received_bytes += received
            outputs.append(output)
            rows.append({
                "frame": index, "sequence": sequence, "connection": connections,
                "first_on_connection": new_connection, "kind": info["kind"],
                "request_bytes": sent, "response_bytes": received,
                "encode_ms": (encoded - start) / 1e6,
                "request_roundtrip_ms": (finished - encoded) / 1e6,
                "encode_plus_roundtrip_ms": (finished - start) / 1e6,
                "server_decode_ms": decode_ns / 1e6,
                "server_suffix_ms": inference_ns / 1e6,
            })
    finally:
        if connection is not None:
            connection.close()
    metrics = {}
    for field in ("encode_ms", "request_roundtrip_ms", "encode_plus_roundtrip_ms",
                  "server_decode_ms", "server_suffix_ms"):
        values = [row[field] for row in rows]
        metrics[field] = {"mean": float(np.mean(values)), "p50": float(np.median(values)),
                          "p95": float(np.percentile(values, 95))}
    return {
        "method": method, "frames": len(arrays), "connections": connections,
        "client_application_bytes": sent_bytes, "server_application_bytes": received_bytes,
        "handshake_client_bytes": handshake_sent, "handshake_server_bytes": handshake_received,
        "connection_and_handshake_ms": connection_setup_ms,
        "selected_delta_frames": sum(row["kind"] == DELTA_COMPRESSED for row in rows)
        if method == "temporal" else 0,
        "tensor_hash_verified_every_frame": True, "timing": metrics,
        "output_sha256": digest(np.asarray(outputs, dtype="<f4").tobytes()),
    }, rows, np.asarray(outputs, dtype="<f4")


def write_report(report, path):
    lines = ["# Prova TCP delle attivazioni su PC", "", f"Data UTC: {report['created_utc']}", "",
             "Client e server sono processi distinti sullo stesso PC, collegati via TCP loopback.",
             "Il client riproduce attivazioni registrate; il server esegue il suffisso Keras.",
             "Nessuna modifica al protocollo SCIoT. Nessuna misura ESP32, camera, Wi-Fi o energia.", "",
             (f"Passo: {report['step']}; frame: {report['frames']}; "
             f"riconnessione prima del frame {report['reconnect_at']} (indice da zero)."), "",
             "Ogni riga è una ripetizione; l'ordine ruota per ridurre gli effetti di riscaldamento.", "",
             ("| Giro | Metodo | Byte client | Byte server | Codifica media ms | "
             "Codifica + RTT p50 ms | p95 ms |"),
             "|---:|---|---:|---:|---:|---:|---:|"]
    for result in report["results"]:
        timing = result["timing"]
        lines.append(f"| {result['round']} | {result['method']} | "
                     f"{result['client_application_bytes']} | {result['server_application_bytes']} | "
                     f"{timing['encode_ms']['mean']:.3f} | "
                     f"{timing['encode_plus_roundtrip_ms']['p50']:.3f} | "
                     f"{timing['encode_plus_roundtrip_ms']['p95']:.3f} |")
    lines += ["", "## Verifiche", "",
              "- SHA256 del tensore ricostruito verificato dal client per ogni risposta.",
              "- Uscite raw confrontate con quelle salvate dall'estrazione: rtol=1e-5, atol=1e-6.",
              "- Uscite indipendenti e temporali identiche byte per byte a pari passo in ogni giro.",
              "- Nuova sessione e primo completo dopo ogni riconnessione; sequenze ripartono da zero.",
              "- Metriche delle celle rispetto al raw nel JSON; nessuna accuratezza su annotazioni.", "",
              "## Conteggi e tempi", "",
              ("I byte applicativi comprendono handshake, frame, risposte e prefissi di lunghezza di 4 byte "
              "del nostro formato. Escludono header TCP/IP, ACK TCP, ritrasmissioni e chiusura."),
              ("Il server restituisce tutta la griglia di uscita e l'hash del tensore: questo "
              "traffico di risposta va considerato separatamente dal risparmio in salita."),
              ("RTT comprende invio, decodifica, inferenza, hash, risposta e ricezione. "
              "Codifica + RTT esclude handshake, verifica locale, file, camera e prefisso della rete."),
              ("Caricamento modello e prima compilazione del suffisso sono esclusi; il traffico "
              "è sequenziale senza attesa per riprodurre i fps. I fps descrivono il video campionato."),
              ("La riconnessione è una chiusura volontaria tra frame confermati: non misura "
              "perdita di pacchetti, interruzioni durante un frame o riconnessione automatica."),
              ("I risultati usano gli input locali identificati dagli hash nel JSON; non si "
              "assume uguaglianza numerica con esecuzioni storiche su altri tensori."), ""]
    path.write_text("\n".join(lines))


def run_comparison(args):
    metadata, arrays, original_outputs = load_inputs(args.input_dir)
    if args.rounds < 1 or not 0 < args.reconnect_at < len(arrays):
        raise ValueError("Need positive rounds and a reconnect index inside the sequence")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    ready_file = args.output_dir / "server-ready.json"
    if ready_file.exists():
        ready_file.unlink()
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="-1", TF_CPP_MIN_LOG_LEVEL="3",
               OMP_NUM_THREADS="1", TF_ENABLE_ONEDNN_OPTS="0")
    command = [sys.executable, str(Path(__file__).resolve()), "server", "--model",
               str((args.input_dir / "model.h5").resolve()), "--split-layer",
               metadata["split"]["layer"], "--port", "0", "--ready-file", str(ready_file.resolve()),
               "--max-connections", str(2 * len(METHODS) * args.rounds)]
    results, rows = [], []
    with (args.output_dir / "server.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, env=env)
        try:
            deadline = time.monotonic() + 60
            while not ready_file.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f"Server did not start; see {log.name}")
                time.sleep(0.05)
            ready = json.loads(ready_file.read_text())
            for iteration in range(args.rounds):
                outputs_by_method = {}
                order = METHODS[iteration % len(METHODS):] + METHODS[:iteration % len(METHODS)]
                current_results = []
                for method in order:
                    result, frame_rows, outputs = replay(
                        ready["host"], ready["port"], arrays, metadata, method,
                        args.step, args.reconnect_at)
                    outputs = outputs.reshape(original_outputs.shape)
                    outputs_by_method[method] = outputs
                    result.update(round=iteration + 1)
                    current_results.append(result)
                    rows.extend(dict(row, method=method, round=iteration + 1) for row in frame_rows)
                np.testing.assert_allclose(outputs_by_method["raw"], original_outputs,
                                           rtol=1e-5, atol=1e-6)
                if outputs_by_method["independent"].tobytes() != outputs_by_method["temporal"].tobytes():
                    raise AssertionError("Compressed methods produced different suffix outputs")
                raw = next(row for row in current_results if row["method"] == "raw")
                independent = next(row for row in current_results if row["method"] == "independent")
                for result in current_results:
                    result["output_error_vs_raw"] = output_stats(
                        outputs_by_method["raw"], outputs_by_method[result["method"]], [0.5])
                    result["upload_saving_vs_raw_percent"] = 100 * (
                        1 - result["client_application_bytes"] / raw["client_application_bytes"])
                    result["upload_saving_vs_independent_percent"] = 100 * (
                        1 - result["client_application_bytes"] / independent["client_application_bytes"])
                    result["same_step_output_bit_exact_between_compressed_methods"] = True
                results.extend(current_results)
                print(f"Round {iteration + 1}: all tensors, suffix outputs and reconnects verified", flush=True)
            if process.wait(timeout=10) != 0:
                raise RuntimeError(f"Server failed; see {log.name}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    report = {
        "created_utc": datetime.now(UTC).isoformat(), "protocol": PROTOCOL,
        "scope": "PC CPU / TCP loopback / activation replay / Keras suffix in separate process",
        "frames": len(arrays), "rounds": args.rounds, "step": args.step,
        "reconnect_at": args.reconnect_at, "sampling_fps": metadata["preprocessing"]["sampling_fps"],
        "input_metadata": metadata,
        "input_hashes": {name: digest((args.input_dir / name).read_bytes())
                         for name in ("model.h5", "activations.npy", "outputs.npy", "result.json")},
        "source_hashes": {name: digest(Path(__file__).with_name(name).read_bytes())
                          for name in ("socket_benchmark.py", "lossy_codec.py", "compare.py", "compare_lossy.py")},
        "environment": {"python": sys.version, "numpy": np.__version__, "platform": platform.platform(),
                        "server_tensorflow": ready["tensorflow"],
                        "client_pid": os.getpid(), "server_pid": ready["pid"],
                        "server_tensorflow_env": {key: env[key] for key in (
                            "CUDA_VISIBLE_DEVICES", "TF_CPP_MIN_LOG_LEVEL", "OMP_NUM_THREADS",
                            "TF_ENABLE_ONEDNN_OPTS")}},
        "raw_outputs_match_extraction_all_rounds": True,
        "independent_temporal_outputs_bit_exact_all_rounds": True,
        "results": results,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    with (args.output_dir / "frames.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_report(report, args.output_dir / "report.md")
    print(args.output_dir / "report.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("server", help="Run the suffix receiver")
    serve.add_argument("--model", type=Path, required=True)
    serve.add_argument("--split-layer", default="block_2_add")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--ready-file", type=Path)
    serve.add_argument("--max-connections", type=int, default=0)
    serve.add_argument("--timeout", type=float, default=60)
    client = commands.add_parser("client", help="Replay one mode to an existing server")
    client.add_argument("--host", default="127.0.0.1")
    client.add_argument("--port", type=int, default=8765)
    client.add_argument("--input-dir", type=Path, required=True)
    client.add_argument("--method", choices=METHODS, required=True)
    client.add_argument("--step", type=float, default=0.001)
    client.add_argument("--reconnect-at", type=int, default=73)
    run = commands.add_parser("run", help="Start separate server and compare all modes")
    run.add_argument("--input-dir", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    run.add_argument("--step", type=float, default=0.001)
    run.add_argument("--rounds", type=int, default=3)
    run.add_argument("--reconnect-at", type=int, default=73)
    args = parser.parse_args()
    if args.command == "server":
        server(args)
    elif args.command == "run":
        run_comparison(args)
    else:
        metadata, arrays, _ = load_inputs(args.input_dir)
        result, _, _ = replay(args.host, args.port, arrays, metadata, args.method,
                              args.step, args.reconnect_at)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
