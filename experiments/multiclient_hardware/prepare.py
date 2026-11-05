"""Identify and snapshot two idle boards before starting campaign.py."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from campaign import BOARDS, HERE, ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--seed-root',type=Path)
    a=p.parse_args()
    run=a.run.resolve()
    run.mkdir(parents=True,exist_ok=False)
    for port,mac in BOARDS.values():
        if not os.access(port,os.R_OK|os.W_OK):
            raise RuntimeError('Serial permission unavailable: '+port)
        if subprocess.run(['fuser',port],capture_output=True).returncode==0:
            raise RuntimeError('Device occupied: '+port)
    def backup(item):
        name,(port,mac)=item
        directory=run/name;directory.mkdir()
        args=[sys.executable,str(HERE/'flash_board.py'),'backup','--port',port,'--mac',mac,'--directory',str(directory)]
        if a.seed_root:
            args+=['--seed',str(a.seed_root.resolve()/name/'original-flash.bin')]
        with (directory/'backup.log').open('x') as log:
            subprocess.run(args,stdout=log,stderr=log,check=True,cwd=ROOT)
        return json.loads((directory/'hardware.json').read_text())
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(backup,BOARDS.items()):
            print(json.dumps(result),flush=True)
    sources=list((ROOT/'src/server/multiclient').glob('*.py'))+list((ROOT/'src/client/esp32-s3-eye-multiclient/src').glob('*'))+list(HERE.glob('*.py'))
    for source in sources:
        dest=run/'sources'/source.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(source.read_bytes())
    (run/'source-sha256.json').write_text(json.dumps({str(q.relative_to(ROOT)):hashlib.sha256(q.read_bytes()).hexdigest() for q in sources},indent=2)+'\n')
    (run/'git-head.txt').write_text(subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=ROOT))


if __name__=='__main__':
    main()
