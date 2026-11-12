"""PC check: the rewritten prefix gives byte-identical outputs to the frozen one."""
import os
from pathlib import Path
import unittest
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL','3');os.environ.setdefault('CUDA_VISIBLE_DEVICES','-1')
import numpy as np
import tensorflow as tf
from tensorflow.lite.python import schema_py_generated as schema
from make_nopad import ROOT,SOURCE,build,op_name

RANDOM_INPUTS=500
SEED=20261111

def interpreter(data):
    runtime=tf.lite.Interpreter(model_content=data,num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    runtime.allocate_tensors();return runtime

def run(runtime,values):
    inp=runtime.get_input_details()[0];out=runtime.get_output_details()[0]
    runtime.set_tensor(inp['index'],values.reshape(inp['shape']));runtime.invoke()
    return runtime.get_tensor(out['index']).copy()

class NoPadModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=SOURCE.read_bytes();cls.rewritten=build()

    def test_structure(self):
        a=schema.ModelT.InitFromObj(schema.Model.GetRootAsModel(self.original,0))
        b=schema.ModelT.InitFromObj(schema.Model.GetRootAsModel(self.rewritten,0))
        names=[op_name(b,op) for op in b.subgraphs[0].operators]
        self.assertEqual(len(names),10);self.assertNotIn('PAD',names)
        self.assertEqual([op_name(a,op) for op in a.subgraphs[0].operators if op_name(a,op)!='PAD'],names)
        self.assertEqual(b.subgraphs[0].operators[4].builtinOptions.padding,schema.Padding.SAME)
        # Every constant buffer except the removed paddings is unchanged.
        ta={t.name:t for t in a.subgraphs[0].tensors};tb={t.name:t for t in b.subgraphs[0].tensors}
        self.assertEqual(set(ta)-set(tb),{n for n in ta if b'block_1_pad' in n})
        for name,t in tb.items():
            self.assertEqual(list(t.shape),list(ta[name].shape))
            qa,qb=ta[name].quantization,t.quantization
            if qa is not None and qa.scale is not None:
                self.assertEqual(list(qa.scale),list(qb.scale));self.assertEqual(list(qa.zeroPoint),list(qb.zeroPoint))
            da=a.buffers[ta[name].buffer].data;db=b.buffers[t.buffer].data
            self.assertEqual(None if da is None else bytes(da),None if db is None else bytes(db))

    def test_outputs_identical(self):
        ra,rb=interpreter(self.original),interpreter(self.rewritten)
        inp=ra.get_input_details()[0]
        data=np.load(ROOT/'experiments/esp32_representation_benchmark/artifacts/inputs.npz')
        inputs=[np.rint(v.astype(np.float64)/inp['quantization'][0]+inp['quantization'][1]).clip(-128,127).astype(np.int8)
                for v in data['frames']]
        rng=np.random.default_rng(SEED)
        inputs+=[rng.integers(-128,128,size=inp['shape'],dtype=np.int8) for _ in range(RANDOM_INPUTS)]
        self.assertEqual(len(inputs),3+RANDOM_INPUTS)
        for i,values in enumerate(inputs):
            a,b=run(ra,values),run(rb,values)
            self.assertEqual(a.tobytes(),b.tobytes(),f'input {i} differs')

if __name__=='__main__':unittest.main()
