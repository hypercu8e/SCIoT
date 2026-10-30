"""Fetch official components at immutable revisions; never overwrite changes."""
import json
from pathlib import Path
import subprocess

here = Path(__file__).resolve().parent
for name, spec in json.loads((here / 'components.json').read_text()).items():
    path = here / 'components' / name
    if not path.exists():
        subprocess.run(['git', 'clone', '--no-checkout', '--filter=blob:none', spec['url'], str(path)], check=True)
        subprocess.run(['git', '-C', str(path), 'checkout', '--detach', spec['commit']], check=True)
    actual = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != spec['commit']:
        raise ValueError(f'{name}: revision differs')
    subprocess.run(['git','-C',str(path),'diff','--exit-code','--quiet'],check=True)
    subprocess.run(['git','-C',str(path),'diff','--cached','--exit-code','--quiet'],check=True)
    print(name, actual, flush=True)
