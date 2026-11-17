"""Recreate private frozen components and apply the experiment-only patch."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / 'experiments/esp32_nopad_benchmark'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def prepare():
    manifest = json.loads((HERE / 'component-sha256.json').read_text())
    source = BASE / 'idf/components'
    actual = {str(p.relative_to(source)): sha(p) for p in source.rglob('*')
              if p.is_file() and not any(part in p.parts for part in ('.git', '__pycache__'))}
    if actual != manifest:
        raise ValueError('Frozen components differ from the successful no-PAD run')
    target = HERE / 'idf/components'
    if target.exists():
        # Refuse to overwrite any prior local edits; a prepared tree is reusable.
        saved = json.loads((HERE / 'artifacts/patched-components.json').read_text())
        current = {str(p.relative_to(target)): sha(p) for p in target.rglob('*')
                   if p.is_file() and not any(part in p.parts for part in ('.git', '__pycache__'))}
        if current != saved:
            raise ValueError('Prepared components changed; refusing overwrite')
    else:
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('.git'))
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(HERE / 'esp-nn-strip.patch')], cwd=target, check=True)
    (HERE / 'artifacts').mkdir(exist_ok=True)
    hashes = {str(p.relative_to(target)): sha(p) for p in target.rglob('*')
              if p.is_file() and not any(part in p.parts for part in ('.git', '__pycache__'))}
    (HERE / 'artifacts/patched-components.json').write_text(json.dumps(hashes, indent=2)+'\n')
    # Deterministic generator copied locally: no writes into the prior experiment.
    subprocess.run([str(ROOT / '.venv/bin/python'), str(HERE / 'make_nopad.py')], check=True)
    print('Frozen components verified, private patch and no-PAD assets ready')

if __name__ == '__main__':
    prepare()
