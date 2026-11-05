"""Verify frozen provenance, all six codecs and identical lossless suffix outputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
for k,v in [('CUDA_VISIBLE_DEVICES','-1'),('TF_CPP_MIN_LOG_LEVEL','3'),('TF_NUM_INTRAOP_THREADS','1'),('TF_NUM_INTEROP_THREADS','1')]:os.environ.setdefault(k,v)
import numpy as np
import tensorflow as tf
from native import Native
from host_encoder import packet
from protocol import *
HERE=Path(__file__).resolve().parent

def runtime(name):
    r=tf.lite.Interpreter(model_path=str(HERE/'artifacts'/name),num_threads=1,experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    r.allocate_tensors();return r

def invoke(r,x):
    r.set_tensor(r.get_input_details()[0]['index'],x.reshape(r.get_input_details()[0]['shape']));r.invoke();return r.get_tensor(r.get_output_details()[0]['index'])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise ValueError('Use a new output directory')
    a.output.mkdir(parents=True)
    m=json.loads((HERE/'artifacts/manifest.json').read_text());original=json.loads((HERE.parent/'activation_compression/int8_2026-10-18/summary.json').read_text())
    assert hashlib.sha256((HERE.parent/'activation_compression/results/input/input_frames.npy').read_bytes()).hexdigest()==original['input_sha256']['input_frames.npy']
    for part in ('prefix','suffix'):
        assert hashlib.sha256((HERE/f'artifacts/int8-{part}.tflite').read_bytes()).hexdigest()==m['models']['int8'][part]['sha256']
    prefix,suffix=runtime('int8-prefix.tflite'),runtime('int8-suffix.tflite')
    scale,zero=prefix.get_output_details()[0]['quantization'];inscale,inzero=prefix.get_input_details()[0]['quantization']
    inputs=np.load(HERE/'artifacts/video-inputs.npy',allow_pickle=False)
    acts=np.array([invoke(prefix,np.clip(np.rint(x.astype(np.float64)/inscale+inzero),-128,127).astype(np.int8)).reshape(-1) for x in inputs])
    raw_outputs=[invoke(suffix,x).tobytes() for x in acts]
    np.save(a.output/'desktop-activations.npy',acts)
    native=Native();rows=[];lossy_states={}
    for c,name in enumerate(NAMES):
        decoder=Decoder(scale,zero);previous=None;lengths=[];times=[];changed=0;states=[];fallbacks=0
        for seq,x in enumerate(acts):
            t=time.perf_counter_ns();body=packet(x,c,seq,previous,native=native,scale=scale,zero=zero);times.append((time.perf_counter_ns()-t)/1e6)
            r=decoder.decode(body);out=invoke(suffix,np.frombuffer(r['activation'],np.int8)).tobytes()
            if c<4:assert r['activation']==x.tobytes() and out==raw_outputs[seq]
            else:states.append((f32_bytes(r['state']),r['activation'],out))
            changed+=out!=raw_outputs[seq];lengths.append(len(body)-80)
            fallbacks+=c in (2,3) and r['radius_bits']==0
            previous=r['state'] if c>=4 else x
        if c>=4:lossy_states[c]=states
        rows.append(dict(mode=name,payload_mean=float(np.mean(lengths)),payload_total=sum(lengths),application_total=sum(lengths)+80*len(lengths),host_encode_median_ms=float(np.median(times)),frames_with_changed_output=changed,raw_fallbacks=fallbacks,lossless=c<4))
    assert lossy_states[4]==lossy_states[5]
    selected=[r['mode'] for r in rows if r['mode'] in ('raw','zlib1') or (r['lossless'] and r['application_total']<146*(N+80))]
    result=dict(frames=146,provenance='desktop prefix, not ESP32 activations',experiment_sha256=m['experiment_sha256'],rows=rows,selected_lossless=selected,lossy_packing_identical=True,lossless_outputs_identical=True)
    (a.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    (a.output/'report.md').write_text('# Verifica PC dei codec INT8\n\nAttivazioni rigenerate sul desktop; tempi host non predicono ESP32. Tutti i percorsi lossless conservano byte e uscite del suffisso; il packing conserva esattamente il D+DZ4.\n\n|Metodo|Payload medio B|Fallback raw|Frame con uscita diversa dal raw|\n|---|---:|---:|---:|\n'+''.join(f"|{r['mode']}|{r['payload_mean']:.2f}|{r['raw_fallbacks']}|{r['frames_with_changed_output']}|\n" for r in rows)+'\nNessuna misura fisica effettuata da questo script.\n')
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
