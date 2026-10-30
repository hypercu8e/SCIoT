"""One-client INT8 suffix server for the raw/zlib hardware experiment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from http.server import BaseHTTPRequestHandler,HTTPServer

os.environ.setdefault('CUDA_VISIBLE_DEVICES','-1')
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL','3')
os.environ.setdefault('TF_NUM_INTRAOP_THREADS','1')
os.environ.setdefault('TF_NUM_INTEROP_THREADS','1')
import numpy as np
import tensorflow as tf
from protocol import MAX_BODY,RESPONSE,RESPONSE_MAGIC,VERSION,parse_request
HERE=Path(__file__).resolve().parent
sys.path.append(str(HERE.parent/'esp32_representation_benchmark'))
from fomo_quality import decode


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8783);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists() and any(args.output.iterdir()):raise ValueError('Output must be empty')
    args.output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((HERE/'artifacts/manifest.json').read_text())
    models=manifest['models']['int8']
    binary=(HERE/'artifacts/int8-suffix.tflite').read_bytes()
    if hashlib.sha256(binary).hexdigest()!=models['suffix']['sha256']:raise ValueError('Wrong suffix')
    runtime=tf.lite.Interpreter(model_content=binary,num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    runtime.allocate_tensors();inspec=runtime.get_input_details()[0];outspec=runtime.get_output_details()[0]
    runtime.set_tensor(inspec['index'],np.zeros(inspec['shape'],dtype=np.int8));runtime.invoke()
    counter=0

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_POST(self):
            nonlocal counter
            start=time.perf_counter_ns()
            try:
                self.connection.settimeout(15)
                length=int(self.headers.get('Content-Length','-1'))
                if self.path!='/infer' or not 32<=length<=MAX_BODY:raise ValueError('Wrong path/size')
                if self.headers.get('X-Model-SHA256')!=models['prefix']['sha256']:raise ValueError('Wrong model')
                body=self.rfile.read(length);received=time.perf_counter_ns()
                request=parse_request(body);decompressed=time.perf_counter_ns()
                values=np.frombuffer(request['activation'],dtype=np.int8).reshape(inspec['shape'])
                runtime.set_tensor(inspec['index'],values);prepared=time.perf_counter_ns()
                runtime.invoke();invoked=time.perf_counter_ns()
                scale,zero=outspec['quantization']
                output=(runtime.get_tensor(outspec['index']).astype(np.float32)-zero)*scale
                detections=decode(output)
                payload=output.astype('<f4').tobytes();completed=time.perf_counter_ns()
                if len(payload)!=1728 or not np.isfinite(output).all():raise ValueError('Invalid output')
                decode_us=(prepared-received)//1000;invoke_us=(invoked-prepared)//1000;post_us=(completed-invoked)//1000
                response=RESPONSE.pack(RESPONSE_MAGIC,VERSION,request['frame'],request['iteration'],432,decode_us,invoke_us,post_us)+payload
                self.send_response(200);self.send_header('Content-Type','application/octet-stream')
                self.send_header('Content-Length',str(len(response)));self.send_header('Connection','close')
                response_headers=sum(map(len,self._headers_buffer))+2
                self.end_headers();self.wfile.write(response);self.wfile.flush();sent=time.perf_counter_ns()
                counter+=1;name=f'{counter:04d}-{request["mode"]}-{request["frame"]}-{request["iteration"]}'
                base=args.output/name
                Path(str(base)+'.request.bin').write_bytes(body)
                Path(str(base)+'.response.bin').write_bytes(response)
                row={k:request[k] for k in ('mode','frame','iteration','wire_bytes')}
                row.update(request=name,body_bytes=len(body),response_body_bytes=len(response),
                    request_http_header_bytes=len(self.raw_requestline)+2+sum(len(k.encode('latin1'))+len(v.encode('latin1'))+4 for k,v in self.headers.raw_items()),
                    response_http_header_bytes=response_headers,body_read_us=(received-start)//1000,
                    decompression_and_validation_us=(decompressed-received)//1000,decode_us=decode_us,
                    invoke_us=invoke_us,post_us=post_us,handler_through_response_us=(sent-start)//1000,
                    fomo_detections=detections,activation_sha256=hashlib.sha256(request['activation']).hexdigest())
                with (args.output/'server.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')
                print(json.dumps({k:v for k,v in row.items() if k!='fomo_detections'}),flush=True)
            except (ValueError,KeyError,TimeoutError) as error:self.send_error(400,str(error))

    server=HTTPServer(('0.0.0.0',args.port),Handler)
    print(json.dumps({'event':'ready','port':args.port,'experiment':manifest['experiment_sha256'],'protocol':VERSION}),flush=True)
    server.serve_forever()

if __name__=='__main__':main()
