"""Freeze exact expected suffix scores from the already verified board activations."""
import hashlib
import json
from pathlib import Path
import sys
import zlib
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from server.multiclient.engine import Suffix
from server.multiclient.protocol import HEADER,REQUEST_MAGIC

def generate():
    archive=HERE/'canonical-activations.json';gold=json.loads(archive.read_text())
    blob=(HERE/'artifacts/int8-prefix-nopad.tflite').read_bytes()
    if hashlib.sha256(blob).hexdigest()!=gold['prefix_sha256']:raise ValueError('Canonical model mismatch')
    engine=Suffix(ROOT/'experiments/esp32_representation_benchmark/artifacts');outputs=[]
    for row in gold['canonicals']:
        a=bytes.fromhex(row['activation_hex']);body=HEADER.pack(REQUEST_MAGIC,1,1,row['frame'],0,0,4608,zlib.crc32(a))+a
        outputs.append(engine(body)[32:])
    if len(outputs)!=3 or any(len(o)!=1728 for o in outputs):raise ValueError('Invalid references')
    out=HERE/'include/generated/expected_scores.h'
    out.write_text('#pragma once\nstatic const unsigned char kExpectedScores[3][1728] = {\n'+',\n'.join('{'+','.join(str(b) for b in o)+'}' for o in outputs)+'\n};\n')
if __name__=='__main__':generate()
