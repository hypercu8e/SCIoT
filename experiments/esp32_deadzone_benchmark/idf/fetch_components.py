"""Prepare local copies of the exact Espressif components used by the baseline."""
import json
from pathlib import Path
import shutil
import subprocess

here=Path(__file__).resolve().parent
baseline=here.parent.parent/'esp32_representation_benchmark/idf'
specs=json.loads((baseline/'components.json').read_text())
for name,spec in specs.items():
    path=here/'components'/name
    if not path.exists():
        source=baseline/'components'/name
        if source.exists():shutil.copytree(source,path)
        else:
            subprocess.run(['git','clone','--no-checkout','--filter=blob:none',spec['url'],str(path)],check=True)
            subprocess.run(['git','-C',str(path),'checkout','--detach',spec['commit']],check=True)
    if subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()!=spec['commit']:
        raise ValueError(f'{name}: wrong revision')
    subprocess.run(['git','-C',str(path),'diff','--exit-code','--quiet'],check=True)
    subprocess.run(['git','-C',str(path),'diff','--cached','--exit-code','--quiet'],check=True)
    print(name,spec['commit'])
