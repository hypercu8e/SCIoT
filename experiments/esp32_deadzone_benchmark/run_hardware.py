"""Backup/verify, flash, capture, and ALWAYS restore a single exclusively owned board.

Run outside the device/network sandbox, from the repository root. Firmware must
already be built. Raw logs/flash contain local data and remain ignored by Git.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
TOOLS=HERE/'results/build-tools/bin/python'


def command(args, log, env=None):
    with log.open('xb') as stream:
        subprocess.run(list(map(str,args)),stdout=stream,stderr=subprocess.STDOUT,check=True,env=env)


def capture(port, log, timeout, camera_only=False,video_only=False):
    import serial
    link=serial.Serial();link.port=port;link.baudrate=115200;link.timeout=.25;link.dtr=False;link.rts=False
    link.open();pending=bytearray();started=False;deadline=time.monotonic()+timeout
    try:
        with log.open('xb') as stream:
            while time.monotonic()<deadline:
                block=link.read(4096)
                if not block:continue
                stream.write(block);stream.flush();pending.extend(block)
                while b'\n' in pending:
                    line,_,rest=pending.partition(b'\n');pending=bytearray(rest)
                    try:row=json.loads(line)
                    except (ValueError,UnicodeError):continue
                    if row.get('event')=='ready' and not started:
                        link.write(b'c' if camera_only else b'v' if video_only else b'g');link.flush();started=True
                    if row.get('event') in ('boot','kernel_check','sequence_start','throughput','transport_error','error','done'):
                        print(json.dumps(row),flush=True)
                    if row.get('event')=='error':raise RuntimeError('Device failure; see device.log')
                    if row.get('event')=='done':return
            raise TimeoutError('Incomplete hardware capture; original flash will be restored')
    finally:link.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--timeout',type=int,default=3600)
    p.add_argument('--camera-only',action='store_true',help='Diagnostic run: 30 raw camera frames plus their originals')
    p.add_argument('--video-only',action='store_true',help='Complete 12-mode, 2-round hardware video campaign, without live camera')
    p.add_argument('--seed-backup',type=Path,help='Previously verified full image; refreshed and reverified against all 8 MB')
    args=p.parse_args();run=args.run.resolve()
    if args.camera_only and args.video_only:raise ValueError('Choose one stage')
    if run.exists() and any(p.name not in ('server','server.log') for p in run.iterdir()):
        raise ValueError('Run directory may contain only the newly started server')
    # Refuse an occupied device or a missing ready server before resetting anything.
    import serial
    occupied=subprocess.run(['fuser',args.port],capture_output=True)
    if occupied.returncode==0:raise RuntimeError('Serial port is in use')
    if occupied.returncode!=1:raise RuntimeError('Unable to verify serial-port ownership')
    import re
    url=re.search(r'\bSERVER_URL\s*(?:=\s*)?"([^"]+)"',(HERE/'include/network.local.h').read_text()).group(1)
    from urllib.parse import urlparse
    parsed=urlparse(url)
    with socket.create_connection((parsed.hostname,parsed.port or 80),timeout=3):pass
    firmware=HERE/'idf/.pio/build/deadzone'
    for name in ('bootloader.bin','partitions.bin','firmware.bin'):
        if not (firmware/name).is_file():raise ValueError('Build firmware first')
    run.mkdir(parents=True,exist_ok=True)
    tool=[TOOLS,HERE/'flash_ops.py']
    try:
        install=tool+['install','--port',args.port,'--run',run]
        if args.seed_backup:install+=['--seed-backup',args.seed_backup.resolve()]
        command(install,run/'install.log')
        metadata=json.loads((run/'hardware.json').read_text())
        print(json.dumps({'event':'firmware_installed_backup_verified','sha256':metadata['backup_sha256']}),flush=True)
        metadata['stage']='camera-smoke' if args.camera_only else 'video' if args.video_only else 'full'
        (run/'hardware.json').write_text(json.dumps(metadata,indent=2)+'\n')
        capture(args.port,run/'device.log',args.timeout,args.camera_only,args.video_only)
        metadata['capture_complete']=True
        (run/'hardware.json').write_text(json.dumps(metadata,indent=2)+'\n')
    finally:
        if not (run/'hardware.json').exists():
            raise RuntimeError('Backup verification failed before any firmware write; inspect install.log')
        print(json.dumps({'event':'restoring_original_flash'}),flush=True)
        command(tool+['restore','--port',args.port,'--run',run],run/'restore.log')
        metadata=json.loads((run/'hardware.json').read_text())
        # Read original firmware startup without sending application commands.
        link=serial.Serial();link.port=args.port;link.baudrate=115200;link.timeout=.25;link.dtr=False;link.rts=False
        link.open()
        try:
            link.rts=True;time.sleep(.2);link.rts=False
            deadline=time.monotonic()+8
            with (run/'restored-boot.log').open('xb') as stream:
                while time.monotonic()<deadline:
                    block=link.read(4096)
                    if block:stream.write(block)
        finally:link.close()
        (run/'hardware.json').write_text(json.dumps(metadata,indent=2)+'\n')
        print(json.dumps({'event':'original_restored_and_verified','sha256':metadata['backup_sha256']}),flush=True)


if __name__=='__main__':main()
