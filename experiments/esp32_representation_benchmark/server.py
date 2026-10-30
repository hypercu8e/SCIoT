"""One-client HTTP suffix server with raw captures and per-request phase times."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ.setdefault('CUDA_VISIBLE_DEVICES', '-1')
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
os.environ.setdefault('TF_NUM_INTRAOP_THREADS', '1')
os.environ.setdefault('TF_NUM_INTEROP_THREADS', '1')
import numpy as np
import tensorflow as tf
from protocol import MAX_BODY, MODES, RESPONSE, RESPONSE_MAGIC, parse_request
from fomo_quality import decode as decode_fomo

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--activations-only', action='store_true', help='Reject diagnostic images in measured traffic')
    p.add_argument('--decode-fomo', action='store_true', help='Include FOMO object postprocessing in server timing')
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((HERE/'artifacts/manifest.json').read_text())
    runtimes = {}
    for mode in MODES.values():
        binary = (HERE/f'artifacts/{mode}-suffix.tflite').read_bytes()
        if hashlib.sha256(binary).hexdigest() != manifest['models'][mode]['suffix']['sha256']:
            raise ValueError('Suffix hash mismatch')
        r = tf.lite.Interpreter(model_content=binary, num_threads=1,
             experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
        r.allocate_tensors()
        runtimes[mode] = r
        r.set_tensor(r.get_input_details()[0]['index'], np.zeros(r.get_input_details()[0]['shape'], r.get_input_details()[0]['dtype']))
        r.invoke()
    counter = 0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            nonlocal counter
            start = time.perf_counter_ns()
            try:
                length = int(self.headers.get('Content-Length', '-1'))
                if self.path != '/infer' or not 32 <= length <= MAX_BODY:
                    raise ValueError('Unsupported path/length')
                body = self.rfile.read(length)
                received = time.perf_counter_ns()
                request = parse_request(body)
                if args.activations_only and request['image']:
                    raise ValueError('Diagnostic images are forbidden in this run')
                mode = request['mode']
                if self.headers.get('X-Model-SHA256') != manifest['models'][mode]['prefix']['sha256']:
                    raise ValueError('Wrong model hash')
                r = runtimes[mode]
                spec = r.get_input_details()[0]
                values = np.frombuffer(request['activation'], dtype=spec['dtype']).reshape(spec['shape'])
                if mode == 'float32' and not np.isfinite(values).all():
                    raise ValueError('Nonfinite activations')
                r.set_tensor(spec['index'], values)
                prepared = time.perf_counter_ns()
                r.invoke()
                invoked = time.perf_counter_ns()
                outspec = r.get_output_details()[0]
                output = r.get_tensor(outspec['index'])
                if mode == 'int8':
                    scale, zero = outspec['quantization']
                    output = (output.astype(np.float32)-zero)*scale
                payload = output.astype('<f4').tobytes()
                if len(payload) != 432*4 or not np.isfinite(output).all():
                    raise ValueError('Invalid model output')
                detections=decode_fomo(output) if args.decode_fomo else None
                completed = time.perf_counter_ns()
                decode_us = (prepared-received)//1000
                invoke_us = (invoked-prepared)//1000
                post_us = (completed-invoked)//1000
                response = RESPONSE.pack(RESPONSE_MAGIC,1,request['frame'],request['iteration'],
                                         432,decode_us,invoke_us,post_us)+payload
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(len(response)))
                self.send_header('Connection', 'close')
                response_header_bytes=sum(map(len,self._headers_buffer))+2
                self.end_headers()
                self.wfile.write(response)
                self.wfile.flush()
                sent = time.perf_counter_ns()
                counter += 1
                name = f'{counter:04d}-{mode}-{request["frame"]}-{request["iteration"]}'
                # Artifact writes occur after response flush, outside model timers.
                (args.output/f'{name}.request.bin').write_bytes(body)
                (args.output/f'{name}.response.bin').write_bytes(response)
                row = {'request': name, 'mode': mode, 'frame':request['frame'],
                       'iteration':request['iteration'], 'body_bytes':len(body),
                       'response_body_bytes':len(response), 'image_bytes':len(request['image']),
                       'request_http_header_bytes':len(self.raw_requestline)+2+sum(len(k.encode('latin1'))+len(v.encode('latin1'))+4 for k,v in self.headers.raw_items()),
                       'response_http_header_bytes':response_header_bytes,
                       'activation_bytes':len(request['activation']), 'body_read_us':(received-start)//1000,
                       'decode_us':decode_us,'invoke_us':invoke_us,'post_us':post_us,
                       'handler_through_response_us':(sent-start)//1000,
                       'fomo_detections':detections,
                       'activation_sha256':hashlib.sha256(request['activation']).hexdigest()}
                with (args.output/'server.jsonl').open('a') as f:
                    f.write(json.dumps(row)+'\n')
                print(json.dumps({k:v for k,v in row.items() if k != 'activation_sha256'}),flush=True)
            except (ValueError, KeyError) as e:
                self.send_error(400,str(e))

    server=HTTPServer(('0.0.0.0',args.port),Handler)
    print(json.dumps({'event':'ready','port':args.port,'experiment':manifest['experiment_sha256'],
                     'server':'HTTPServer, serial requests, one TF thread, warmed suffixes'}),flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
