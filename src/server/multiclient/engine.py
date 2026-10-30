"""Frozen INT8 suffix; constructed and called exclusively by the worker thread."""
import hashlib
import json
from pathlib import Path
import time

from .protocol import parse, response


class Suffix:
    def __init__(self, artifacts):
        import numpy as np
        import tensorflow as tf
        from .fomo import decode
        self.np, self.decode = np, decode
        directory = Path(artifacts)
        manifest = json.loads((directory / 'manifest.json').read_text())
        models = manifest['models']['int8']
        for name in ('prefix', 'suffix'):
            data = (directory / f'int8-{name}.tflite').read_bytes()
            if hashlib.sha256(data).hexdigest() != models[name]['sha256']:
                raise ValueError(f'{name} hash mismatch')
        for key in ('shape', 'dtype', 'scales', 'zero_points'):
            if models['prefix']['output'][key] != models['suffix']['input'][key]:
                raise ValueError('Boundary mismatch')
        self.runtime = tf.lite.Interpreter(model_content=data, num_threads=1,
            experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
        self.runtime.allocate_tensors()
        self.input = self.runtime.get_input_details()[0]
        self.output = self.runtime.get_output_details()[0]
        for detail, shape in ((self.input, [1, 24, 24, 8]), (self.output, [1, 12, 12, 3])):
            if detail['dtype'] != np.int8 or detail['shape'].tolist() != shape:
                raise ValueError('Unexpected suffix tensors')
        self.runtime.set_tensor(self.input['index'], np.zeros(self.input['shape'], dtype=np.int8))
        self.runtime.invoke()

    def __call__(self, body):
        start = time.perf_counter_ns()
        frame, iteration, activation = parse(body)
        values = self.np.frombuffer(activation, dtype=self.np.int8).reshape(self.input['shape'])
        self.runtime.set_tensor(self.input['index'], values)
        prepared = time.perf_counter_ns()
        self.runtime.invoke()
        invoked = time.perf_counter_ns()
        raw = self.runtime.get_tensor(self.output['index'])
        scale, zero = self.output['quantization']
        scores = (raw.astype(self.np.float32)-zero)*scale
        self.decode(scores)
        if not self.np.isfinite(scores).all():
            raise ValueError('Nonfinite output')
        payload = scores.astype('<f4').tobytes()
        done = time.perf_counter_ns()
        return response(frame, iteration, payload, (prepared-start)//1000,
                        (invoked-prepared)//1000, (done-invoked)//1000)
