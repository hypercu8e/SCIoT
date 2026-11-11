"""Verified board backups plus frozen experimental sources and build manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--seed-root',type=Path);p.add_argument('--snapshot-only',action='store_true');a=p.parse_args()
    if not a.snapshot_only:
        args=[sys.executable,str(ROOT/'experiments/multiclient_hardware/prepare.py'),'--run',str(a.run)]
        if a.seed_root: args+=['--seed-root',str(a.seed_root)]
        subprocess.run(args,cwd=ROOT,check=True)
    for board in ('A','B'):
        m=json.loads((a.run/board/'hardware.json').read_text())
        if not m['backup_verified'] or hashlib.sha256((a.run/board/'original-flash.bin').read_bytes()).hexdigest()!=m['backup_sha256']: raise ValueError('Backup missing or changed')
    files=list(HERE.glob('*.py'))+list(HERE.glob('*.md'))+list((HERE/'idf/src').glob('*'))
    files += [HERE/'idf'/s for s in ('CMakeLists.txt','platformio.ini','partitions.csv','sdkconfig.defaults')]
    hashes={}
    for file in files:
        target=a.run/'experiment-sources'/file.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists(): raise FileExistsError(target)
        target.write_bytes(file.read_bytes());hashes[str(file.relative_to(ROOT))]=hashlib.sha256(file.read_bytes()).hexdigest()
    for file in (HERE/'idf/components').rglob('*'):
        if file.is_file() and '.git' not in file.parts:
            hashes[str(file.relative_to(ROOT))]=hashlib.sha256(file.read_bytes()).hexdigest()
    binary=HERE/'idf/.pio/build/espnn/firmware.bin'
    shutil.copyfile(binary,a.run/'firmware.bin')
    hashes[str(binary.relative_to(ROOT))]=hashlib.sha256(binary.read_bytes()).hexdigest()
    (a.run/'experiment-sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    subprocess.run(['adb','devices'],check=True,stdout=(a.run/'adb-devices.txt').open('x'))
    print('Verified backups, sources, component hashes and firmware snapshot saved.')
if __name__=='__main__': main()
