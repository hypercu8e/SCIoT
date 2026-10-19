"""Exercise SCIoT's original HTTP routes, parser, suffix and split selection on PC.

One real loopback server and a software client; writable state is isolated.
Uses the original RGB model, not the separate grayscale experimental candidate.
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src/server"
ENDPOINTS = {"registration": "/api/registration", "device_input": "/api/device_input",
             "device_inference_result": "/api/device_inference_result",
             "offloading_layer": "/api/offloading_layer"}


def serve(out):
    sys.path.insert(0, str(ROOT / "src"))
    from server.logger.log_config import LoggerConfig

    LoggerConfig.LOG_FOLDER = str(out / "logs")
    from server.commons import EvaluationFiles, InputDataFiles, OffloadingDataFiles
    from server.communication.http_server import HttpServer
    from server.communication.request_handler import RequestHandler
    from server.edge.edge_initialization import Edge
    from server.logger.log import logger

    logger.setLevel("ERROR")
    state = out / "state"
    state.mkdir()
    for attr, filename in (("data_file_path_device", "device_inference_times.json"),
                           ("data_file_path_edge", "edge_inference_times.json"),
                           ("data_file_path_sizes", "layer_sizes.json")):
        shutil.copyfile(SRC / filename, state / filename)
        setattr(OffloadingDataFiles, attr, str(state / filename))
    EvaluationFiles.evaluation_file_path = str(state / "evaluations.csv")
    InputDataFiles.input_data_file_path = str(state / "input_data.png")
    original_inference = Edge.run_inference

    def observed_inference(index, values):
        result = original_inference(index, values)
        np.save(out / "server_prediction.npy", result)
        return result

    Edge.run_inference = staticmethod(observed_inference)

    class LocalClockHttpServer(HttpServer):
        def _sync_with_ntp(self):
            return 0.0  # Both processes use the same PC clock; no external NTP.

    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        instance = LocalClockHttpServer("127.0.0.1", port, ENDPOINTS, "unused-local-clock", 96, 96, 58, RequestHandler())
        (out / "ready.json").write_text(json.dumps({"port": port, "pid": os.getpid()}))
        import uvicorn

        uvicorn.Server(uvicorn.Config(instance.app, log_level="error")).run(sockets=[listener])


def request(base, endpoint, body=None, json_body=False):
    headers = {"Content-Type": "application/json" if json_body else "application/octet-stream"}
    req = Request(base + endpoint, data=body, headers=headers)
    with urlopen(req, timeout=60) as response:
        return json.loads(response.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--image", type=Path, default=ROOT / "canCoke.jpeg")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if args.serve:
        serve(out)
        return
    if out.exists() and any(out.iterdir()):
        parser.error("Use an empty output directory")
    out.mkdir(parents=True, exist_ok=True)
    import tensorflow as tf

    model_path = SRC / "models/test/test_model/test_model.h5"
    model = tf.keras.models.load_model(model_path, compile=False)
    cut = model.get_layer("block_2_add")
    prefix = tf.keras.Model(model.input, cut.output)
    image = Image.open(args.image).convert("RGB")
    side = min(image.size)
    left, top = (image.width - side) // 2, (image.height - side) // 2
    image = image.crop((left, top, left + side, top + side)).resize((96, 96), Image.Resampling.LANCZOS)
    rgb = np.asarray(image, dtype=np.uint8)
    values = rgb.astype(np.float32)[None] / np.float32(255)
    reference = model(values, training=False).numpy()
    activation = prefix(values, training=False).numpy().astype("<f4")
    # Original protocol indexes executable layers, excluding InputLayer.
    split_index = model.layers.index(cut) - 1
    timings = np.zeros(split_index + 1, dtype="<f4")  # Protocol fixture, not ESP32 timing.
    rgb565 = (((rgb[..., 0].astype(np.uint16) >> 3) << 11)
              | ((rgb[..., 1].astype(np.uint16) >> 2) << 5)
              | (rgb[..., 2].astype(np.uint16) >> 3)).astype(">u2").tobytes()
    tracked = [SRC / name for name in ("device_inference_times.json", "edge_inference_times.json",
                                      "layer_sizes.json", "evaluations/evaluations.csv")]
    before = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="-1", TF_CPP_MIN_LOG_LEVEL="3",
               TF_NUM_INTRAOP_THREADS="1", TF_NUM_INTEROP_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
    with (out / "server.log").open("w") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve",
                                    "--output-dir", str(out)], env=env, stdout=log, stderr=log)
        try:
            deadline, connected = time.monotonic() + 60, False
            while not connected:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f"Server did not start; see {out / 'server.log'}")
                if (out / "ready.json").exists():
                    ready = json.loads((out / "ready.json").read_text())
                    base = f"http://127.0.0.1:{ready['port']}"
                    try:
                        request(base, ENDPOINTS["offloading_layer"])
                        connected = True
                    except URLError:
                        pass
                if not connected:
                    time.sleep(.05)
            registration = request(base, ENDPOINTS["registration"], b'{"device_id":"device_01"}', True)
            assert registration["device"] == "device_01"
            assert request(base, ENDPOINTS["device_input"], rgb565)["message"] == "Success"
            payload = (struct.pack("<d9s4siI", time.time(), b"device_01", b"0001", split_index, activation.nbytes)
                       + activation.tobytes() + struct.pack("<i", timings.nbytes) + timings.tobytes())
            result = request(base, ENDPOINTS["device_inference_result"], payload)
            assert result["message"] == "Success"
            decision = request(base, ENDPOINTS["offloading_layer"])["offloading_layer_index"]
            assert 0 <= decision < len(model.layers) - 1
            prediction = np.load(out / "server_prediction.npy", allow_pickle=False).reshape(reference.shape)
            np.testing.assert_allclose(prediction, reference, rtol=1e-4, atol=1e-5)
            assert (out / "state/input_data.png").exists()
            assert (out / "state/evaluations.csv").exists()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    after = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in tracked}
    assert before == after
    summary = {
        "scope": "Actual SCIoT HTTP routes + RequestHandler + Edge suffix + split selection, two PC processes",
        "model": str(model_path.relative_to(ROOT)), "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "input_shape": list(values.shape), "output_shape": list(prediction.shape),
        "keras_split_layer": cut.name, "wire_split_index_excluding_input": split_index,
        "registration_image_inference_and_decision_passed": True,
        "max_prediction_error_vs_full_keras": float(np.max(np.abs(prediction - reference))),
        "rtol": 1e-4, "atol": 1e-5, "returned_split_index": decision,
        "server_pid": ready["pid"], "client_pid": os.getpid(),
        "original_profiles_and_evaluations_unchanged": before == after,
        "limits": ["HTTP only; not MQTT/WebSocket", "Original RGB model, not grayscale candidate",
                   "Local clock override replaces NTP; startup Edge.initialization not exercised",
                   "Copied profiles and zero device times are fixtures; split optimality/performance not evaluated",
                   "Prediction observed inside server; original HTTP response only confirms success",
                   "No ESP32, Wi-Fi or compression integration"],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
