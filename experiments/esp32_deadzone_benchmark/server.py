"""Single-worker SDZ1 server. Stateful inference and untimed raw diagnostics."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

for key, value in [('CUDA_VISIBLE_DEVICES', '-1'), ('TF_CPP_MIN_LOG_LEVEL', '3'),
                   ('TF_NUM_INTRAOP_THREADS', '1'), ('TF_NUM_INTEROP_THREADS', '1')]:
    os.environ.setdefault(key, value)
import numpy as np
import tensorflow as tf

from protocol import Decoder, MAX_BODY, REPLY, REPLY_MAGIC, VERSION, NAMES, crc

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'esp32_representation_benchmark'))
from fomo_quality import decode


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8785)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError('Output must be empty')
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((HERE / 'artifacts/manifest.json').read_text())
    model = manifest['models']['int8']
    binary = (HERE / 'artifacts/int8-suffix.tflite').read_bytes()
    if hashlib.sha256(binary).hexdigest() != model['suffix']['sha256']:
        raise ValueError('Wrong suffix')
    runtime = tf.lite.Interpreter(model_content=binary, num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    runtime.allocate_tensors()
    inspec, outspec = runtime.get_input_details()[0], runtime.get_output_details()[0]
    scale, zero = inspec['quantization']
    decoder = Decoder(scale, zero)
    runtime.set_tensor(inspec['index'], np.zeros(inspec['shape'], np.int8))
    runtime.invoke()
    counter = 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path!='/infer':
                self.send_error(404);return
            self.send_response(200)
            self.send_header('Content-Length','2')
            self.send_header('Connection','close')
            self.end_headers();self.wfile.write(b'OK')

        def do_POST(self):
            nonlocal counter
            try:
                self.connection.settimeout(60)
                length = int(self.headers.get('Content-Length', '-1'))
                if self.path != '/infer' or not 80 <= length <= MAX_BODY:
                    raise ValueError('Wrong path/body size')
                if self.headers.get('X-Model-SHA256') != model['prefix']['sha256']:
                    raise ValueError('Wrong model')
                body = self.rfile.read(length)
                received = time.perf_counter_ns()
                row = decoder.decode(body)
                runtime.set_tensor(inspec['index'], np.frombuffer(row['activation'], np.int8).reshape(inspec['shape']))
                prepared = time.perf_counter_ns()
                runtime.invoke()
                invoked = time.perf_counter_ns()
                output_scale, output_zero = outspec['quantization']
                output = (runtime.get_tensor(outspec['index']).astype(np.float32) - output_zero) * output_scale
                detections = decode(output)
                payload = output.astype('<f4').tobytes()
                completed = time.perf_counter_ns()
                timers = [(prepared-received)//1000, (invoked-prepared)//1000, (completed-invoked)//1000]
                response = REPLY.pack(REPLY_MAGIC, VERSION, row['device'], row['session'], row['config'],
                    row['seq'], row['frame'], *timers, row['state_crc'], crc(row['activation'])) + payload
                counter += 1
                name = f'{counter:06d}-{row["source"]}-{row["session"]}-{row["config"]}-{row["seq"]}'
                base = args.output / name
                # Persist before ACK: no unrecorded successful samples.
                Path(str(base)+'.request.bin').write_bytes(body)
                Path(str(base)+'.response.bin').write_bytes(response)
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(len(response)))
                self.send_header('Connection', 'close')
                response_headers = sum(map(len, self._headers_buffer)) + 2
                self.end_headers()
                self.wfile.write(response)
                self.wfile.flush()
                result = {k: v for k, v in row.items() if k not in ('symbols', 'state', 'activation')}
                result.update(name=name, mode_name=NAMES[row['config']], body_bytes=len(body),
                    response_body_bytes=len(response), request_http_header_bytes=len(self.raw_requestline)+2+
                    sum(len(k.encode('latin1'))+len(v.encode('latin1'))+4 for k,v in self.headers.raw_items()),
                    response_http_header_bytes=response_headers, decode_us=timers[0], invoke_us=timers[1],
                    post_us=timers[2], activation_crc=crc(row['activation']), fomo_detections=detections)
                with (args.output/'server.jsonl').open('a') as stream:
                    stream.write(json.dumps(result)+'\n')
            except (ValueError, KeyError, TimeoutError) as error:
                print(json.dumps({'event':'rejected','reason':str(error)}),flush=True)
                self.send_error(400, str(error))
            except (ConnectionError, OSError):
                # Client must begin a new session after an ambiguous response.
                pass

    server = HTTPServer(('0.0.0.0', args.port), Handler)
    print(json.dumps({'event': 'ready', 'port': args.port, 'experiment': manifest['experiment_sha256']}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
