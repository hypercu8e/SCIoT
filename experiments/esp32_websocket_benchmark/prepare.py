"""Recreate frozen private TFLM/ESP-NN/camera components; never copy credentials."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def inventory(folder):
    return {str(p.relative_to(folder)):sha(p) for p in folder.rglob('*') if p.is_file()
            and not any(x in p.parts for x in ('.git','__pycache__'))}

def check_network(path=None):
    path=path or HERE/'include/network.local.h'
    if not path.is_file():raise ValueError('Configure include/network.local.h locally')
    text=path.read_text();values={}
    for key in ('WIFI_SSID','WIFI_PASSWORD'):
        match=re.search(r'^\s*#define\s+'+key+r'\s+("(?:[^"\\]|\\.)*")\s*$',text,re.M)
        if not match:raise ValueError('Missing or malformed local Wi-Fi setting')
        values[key]=ast.literal_eval(match.group(1))
        if values[key].startswith('CONFIGURE_'):raise ValueError('Configure router credentials locally before acquisition')
    if not 1<=len(values['WIFI_SSID'].encode())<=32 or len(values['WIFI_PASSWORD'].encode())>64:
        raise ValueError('Invalid Wi-Fi configuration lengths')

def prepare():
    if inventory(HERE/'vendor')!=json.loads((HERE/'vendor-sha256.json').read_text()):raise ValueError('WebSocket vendor sources changed')
    source=ROOT/'experiments/esp32_nopad_benchmark/idf/components'
    expected=json.loads((HERE/'component-sha256.json').read_text())
    if inventory(source)!=expected:raise ValueError('Frozen TFLM/ESP-NN sources changed')
    camera=ROOT/'src/client/esp32-s3-eye-multiclient/components/esp32-camera'
    if inventory(camera)!=json.loads((HERE/'camera-sha256.json').read_text()):raise ValueError('Frozen camera sources changed')
    jpeg=ROOT/'src/client/esp32-s3-eye-multiclient/managed_components/espressif__esp_jpeg'
    if inventory(jpeg)!=json.loads((HERE/'jpeg-sha256.json').read_text()):raise ValueError('Frozen JPEG sources changed')
    target=HERE/'idf/components';manifest=HERE/'artifacts/patched-components.json'
    if target.exists():
        if not manifest.exists() or inventory(target)!=json.loads(manifest.read_text()):raise ValueError('Private components changed; refusing overwrite')
    else:
        shutil.copytree(HERE/'vendor/esp_websocket_client',target/'esp_websocket_client')
        shutil.copytree(source,target,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','__pycache__'))
        shutil.copytree(camera,target/'esp32-camera',ignore=shutil.ignore_patterns('.git','__pycache__'))
        shutil.copytree(jpeg,target/'esp_jpeg',ignore=shutil.ignore_patterns('.git','__pycache__'))
        subprocess.run(['patch','--batch','--fuzz=0','-p1','-i',str(HERE/'esp-nn-strip.patch')],cwd=target,check=True)
        manifest.parent.mkdir(exist_ok=True);manifest.write_text(json.dumps(inventory(target),indent=2)+'\n')
    subprocess.run([str(ROOT/'.venv/bin/python'),str(HERE/'make_nopad.py')],check=True)
    subprocess.run([str(ROOT/'.venv/bin/python'),str(HERE/'make_scores.py')],check=True)
    original=json.loads((ROOT/'experiments/esp32_representation_benchmark/artifacts/manifest.json').read_text())['models']['int8']
    (HERE/'artifacts/model-registry.json').write_text(json.dumps({'suffix_sha256':original['suffix']['sha256'], 'prefixes':[{'path':'int8-prefix-nopad.tflite','sha256':sha(HERE/'artifacts/int8-prefix-nopad.tflite')}]},indent=2)+'\n')
    if not (HERE/'include/network.local.h').exists():
        shutil.copyfile(HERE/'include/network.local.example.h',HERE/'include/network.local.h')
        (HERE/'include/network.local.h').chmod(0o600)
    print('Frozen components and local model prepared; credentials not copied')

if __name__=='__main__':prepare()
