"""Export only small, audited results; never flash images or local credentials."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
HERE=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('New output directory required')
    subprocess.run([sys.executable,str(HERE/'analyze.py'),'--run',str(a.run)],check=True)
    s=json.loads((a.run/'summary.json').read_text());h=json.loads((a.run/'hardware.json').read_text())
    tests=(HERE/'results/tests.txt').read_text();assert tests.rstrip().endswith('OK')
    assert h.get('capture_complete') and s['restored_verified'] and s['lossless_exact']
    boot=(a.run/'restored-boot.log').read_text(errors='replace')
    if 'sciot_esp32_client' not in boot or 'fomo_224' not in boot:raise ValueError('Original firmware startup not identified')
    a.output.mkdir(parents=True)
    for name in ('summary.json','report.md','frames.csv','tradeoff.png','tradeoff.svg'):
        if (a.run/name).exists():shutil.copyfile(a.run/name,a.output/name)
    shutil.copyfile(HERE/'results/tests.txt',a.output/'tests.txt')
    shutil.copyfile(a.run/'build-verification.json',a.output/'build-verification.json')
    sources=list(HERE.glob('*.py'))+[HERE/'include/codec.h',HERE/'include/legacy_codec.h',HERE/'include/rice_decoder.h',HERE/'idf/src/main.cpp',HERE/'idf/platformio.ini',HERE/'idf/src/CMakeLists.txt',HERE/'README.md']
    build_proof=json.loads((a.run/'build-verification.json').read_text())
    verification=dict(h,original_boot_verified=True,measured_build_source_sha256=build_proof['source_sha256'],source_sha256={str(p.relative_to(HERE)):sha(p) for p in sources},evidence_sha256={n:sha(a.run/n) for n in ('device.log','install.log','restore.log','restored-boot.log')})
    for source,name in [(a.run/'serial-recovery.json','serial-recovery.json'),(a.run/'backend-proof.json','backend-proof.json'),(HERE/'results/preliminary-diagnostics.json','preliminary-diagnostics.json')]:
        if source.exists():shutil.copyfile(source,a.output/name)
    (a.output/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    print(json.dumps({'published':str(a.output),'measured':s['measured']}))
if __name__=='__main__':main()
