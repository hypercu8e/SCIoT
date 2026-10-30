"""Copy the verified official component revisions locally for PlatformIO.

External component paths produce colliding object basenames with PlatformIO.
Never modify the reference experiment's component sources.
"""
from pathlib import Path
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
REFERENCE=HERE.parents[2]/'experiments/esp32_representation_benchmark/idf'
subprocess.run(['python3',str(REFERENCE/'fetch_components.py')],check=True)
for source in (REFERENCE/'components').iterdir():
    if not source.is_dir():continue
    target=HERE/'components'/source.name
    if target.exists():
        raise SystemExit(f'Refusing to overwrite {target}; inspect existing sources')
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('.git','__pycache__'))
    print(source.name)
