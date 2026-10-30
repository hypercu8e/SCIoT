"""Export reviewed small results only. Never export flash, credentials or packets."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import re

HERE=Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    summary=json.loads((args.run/'summary.json').read_text())
    hardware=json.loads((args.run/'hardware.json').read_text())
    tests=(HERE/'results/tests.txt').read_text()
    match=re.search(r'Ran (\d+) tests? ',tests)
    if not match or not tests.rstrip().endswith('OK'):
        raise ValueError('Native tests did not pass; refusing to publish')
    if not summary['verified'] or not hardware['restored'] or not hardware.get('capture_complete'):
        raise ValueError('Incomplete measurements or restoration')
    if hardware.get('stage','full')!=summary['stage'] or sha(args.run/'device.log')!=summary['device_log_sha256']:
        raise ValueError('Audit stage or device log differs from the measured run')
    boot=(args.run/'restored-boot.log').read_text(errors='replace')
    if 'sciot_esp32_client' not in boot or 'fomo_224' not in boot:
        raise ValueError('Original firmware boot not verified')
    if args.output.exists():raise ValueError('Refusing to overwrite a published report')
    args.output.mkdir(parents=True)
    for name in ('summary.json','frames.csv','report.md'):
        shutil.copy2(args.run/name,args.output/name)
    for name in ('tradeoff.png','tradeoff.svg'):
        if (args.run/name).exists():shutil.copy2(args.run/name,args.output/name)
    sources=[p for p in HERE.glob('*.py')]+[HERE/'include/codec.h',HERE/'idf/src/main.cpp',
        HERE/'idf/platformio.ini',HERE/'idf/sdkconfig.defaults',HERE/'idf/src/CMakeLists.txt',HERE/'README.md',
        HERE/'idf/fetch_components.py',HERE/'idf/fetch_miniz.py',HERE/'idf/CMakeLists.txt',HERE/'idf/partitions.csv']
    snapshot={str(p.relative_to(HERE)):sha(p) for p in sources}
    verification=dict(hardware,original_boot_verified=True,measured_requests=summary['measured_requests'],
        diagnostic_requests=summary['diagnostic_requests'],native_tests=f'{match.group(1)} passed',
        source_sha256=snapshot,evidence_sha256={name:sha(args.run/name) for name in
            ('device.log','install.log','restore.log','restored-boot.log')})
    (args.output/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    shutil.copy2(HERE/'results/tests.txt',args.output/'tests.txt')
    shutil.copy2(HERE/'results/build-verification.json',args.output/'build-verification.json')
    diagnostics=[]
    for name in ('2026-10-29-run2','2026-10-29-camera-check','2026-10-29-camera-check2','2026-10-29-camera-check3',
                 '2026-10-29-final','2026-10-29-camera-dma','2026-10-29-camera20'):
        folder=HERE/'results'/name
        if not (folder/'hardware.json').exists():continue
        meta=json.loads((folder/'hardware.json').read_text())
        events=[]
        for line in (folder/'device.log').read_text(errors='replace').splitlines():
            try:events.append(json.loads(line))
            except ValueError:pass
        diagnostics.append(dict(run=name,restored=meta['restored'],backup_sha256=meta['backup_sha256'],
            firmware_sha256=meta['firmware_sha256'],device_log_sha256=sha(folder/'device.log'),
            completed=bool(meta.get('capture_complete')),events=[r for r in events if r.get('event') in
                ('error','transport_error','health','done')]))
    (args.output/'preliminary-diagnostics.json').write_text(json.dumps(diagnostics,indent=2)+'\n')
    (args.output/'snapshot-sha256.txt').write_text(''.join(f'{digest}  {name}\n' for name,digest in sorted(snapshot.items())))
    print(json.dumps({'published':str(args.output),'measured_requests':summary['measured_requests']}))


if __name__=='__main__':main()
