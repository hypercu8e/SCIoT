"""Describe the frozen prefix using the same local TensorFlow schema as replay."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL','3')
from tensorflow.lite.python import schema_py_generated as schema

ROOT=Path(__file__).resolve().parents[2]

DEFAULT=ROOT/'experiments/esp32_representation_benchmark/artifacts/int8-prefix.tflite'

def describe(path=DEFAULT):
    data=path.read_bytes();model=schema.Model.GetRootAsModel(data,0)
    if model.SubgraphsLength()!=1:raise ValueError('Expected one straight-line subgraph')
    graph=model.Subgraphs(0)
    names={v:k for k,v in vars(schema.BuiltinOperator).items() if isinstance(v,int)}
    types={v:k for k,v in vars(schema.TensorType).items() if isinstance(v,int)}
    sizes={'INT8':1,'INT32':4,'FLOAT32':4}
    def tensor(index):
        t=graph.Tensors(index);shape=[int(v) for v in t.ShapeAsNumpy()]
        return dict(index=index,name=t.Name().decode(),shape=shape,dtype=types[t.Type()],
                    bytes=math.prod(shape)*sizes[types[t.Type()]],
                    constant=model.Buffers(t.Buffer()).DataLength()>0)
    nodes=[]
    for index in range(graph.OperatorsLength()):
        op=graph.Operators(index);name=names[model.OperatorCodes(op.OpcodeIndex()).BuiltinCode()]
        inputs=[tensor(int(i)) for i in op.InputsAsNumpy() if i>=0]
        outputs=[tensor(int(i)) for i in op.OutputsAsNumpy()]
        macs=None
        if name=='CONV_2D':macs=math.prod(outputs[0]['shape'])*math.prod(inputs[1]['shape'][1:])
        if name=='DEPTHWISE_CONV_2D':macs=math.prod(outputs[0]['shape'])*math.prod(inputs[1]['shape'][1:3])
        nodes.append(dict(index=index,op=name,inputs=inputs,outputs=outputs,macs=macs))
    return dict(model_sha256=hashlib.sha256(data).hexdigest(),nodes=nodes)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model',type=Path,default=DEFAULT);a=p.parse_args()
    a.output.write_text(json.dumps(describe(a.model),indent=2)+'\n')
