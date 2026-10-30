"""Reuse the archived models and frozen inputs; no conversion or calibration."""
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'esp32_representation_benchmark'

def main():
    source=BASE/'artifacts';out=HERE/'artifacts';out.mkdir(exist_ok=True)
    manifest=json.loads((source/'manifest.json').read_text())
    for mode in ('prefix','suffix'):
        name=f'int8-{mode}.tflite'
        if hashlib.sha256((source/name).read_bytes()).hexdigest()!=manifest['models']['int8'][mode]['sha256']:
            raise ValueError('Model hash mismatch')
    for name in ('manifest.json','inputs.npz','int8-prefix.tflite','int8-suffix.tflite',
                 'quality-inputs.bin','quality-inputs.npy','quality-inputs.json'):
        shutil.copy2(source/name,out/name)
    quality=json.loads((out/'quality-inputs.json').read_text())
    if hashlib.sha256((out/'quality-inputs.bin').read_bytes()).hexdigest()!=quality['input_sha256']:
        raise ValueError('Quality input hash mismatch')
    include=HERE/'include';include.mkdir(exist_ok=True)
    local=include/'network.local.h'
    if not local.exists():
        import re
        text=(BASE/'include/network.local.h').read_text()
        text=re.sub(r':\d+/infer',':8783/infer',text)
        local.write_text(text)
    print('Frozen INT8 models and inputs verified and copied; local credentials excluded from Git')

if __name__=='__main__':main()
