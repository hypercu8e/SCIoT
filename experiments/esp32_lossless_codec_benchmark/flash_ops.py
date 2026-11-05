"""Esptool operations sharing ONE connection across each write/read and verify.

Avoids USB-JTAG close/reopen/reset accidentally running firmware between flash
snapshot and verification. Used only by the authorized hardware runner.
"""
import argparse
import hashlib
import json
from pathlib import Path

from esptool import cmds
from esptool.util import FatalError

HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=('install','restore'))
    p.add_argument('--port',required=True)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--seed-backup',type=Path)
    args=p.parse_args();run=args.run
    backup=run/'original-flash.bin';metadata_path=run/'hardware.json'
    esp=cmds.detect_chip(args.port)
    if esp.CHIP_NAME!='ESP32-S3':raise RuntimeError('Wrong chip')
    esp=cmds.run_stub(esp);esp.change_baud(921600);cmds.attach_flash(esp)
    try:
        if args.operation=='install':
            if backup.exists():raise ValueError('Refusing to overwrite backup')
            seed_sha=None
            if args.seed_backup:
                seed=args.seed_backup.read_bytes()
                if len(seed)!=8388608:raise ValueError('Wrong seed backup size')
                seed_sha=hashlib.sha256(seed).hexdigest()
                # Refresh boot/partition/NVS pages. Trust the reused remainder ONLY
                # after verifying the digest of the entire resulting 8 MB image.
                head=cmds.read_flash(esp,0,0x10000)
                backup.write_bytes(head+seed[0x10000:])
                try:cmds.verify_flash(esp,[(0,str(backup))])
                except FatalError:
                    cmds.read_flash(esp,0,8388608,str(backup))
            else:
                cmds.read_flash(esp,0,8388608,str(backup))
            if backup.stat().st_size!=8388608:raise ValueError('Wrong backup size')
            cmds.verify_flash(esp,[(0,str(backup))])
            firmware=HERE/'idf/.pio/build/lossless'
            metadata={'backup_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'flash_bytes':8388608,
                'firmware_sha256':hashlib.sha256((firmware/'firmware.bin').read_bytes()).hexdigest(),
                'backup_verified_before_flash':True,'same_connection_backup_verification':True,'restored':False}
            if seed_sha:metadata['seed_backup_sha256']=seed_sha
            metadata_path.write_text(json.dumps(metadata,indent=2)+'\n')
            print(json.dumps({'event':'backup_verified','sha256':metadata['backup_sha256']}),flush=True)
            parts=[(0,str(firmware/'bootloader.bin')),(0x8000,str(firmware/'partitions.bin')),(0x10000,str(firmware/'firmware.bin'))]
            cmds.write_flash(esp,parts,compress=True)
            cmds.verify_flash(esp,parts)
            cmds.reset_chip(esp,'hard-reset')
        else:
            metadata=json.loads(metadata_path.read_text())
            if hashlib.sha256(backup.read_bytes()).hexdigest()!=metadata['backup_sha256']:
                raise ValueError('Backup file changed')
            cmds.write_flash(esp,[(0,str(backup))],compress=True)
            cmds.verify_flash(esp,[(0,str(backup))])
            metadata.update(restored=True,restored_digest_verified_before_boot=True,same_connection_restore_verification=True)
            metadata_path.write_text(json.dumps(metadata,indent=2)+'\n')
            # Keep stub running until the parent opens serial and deliberately boots.
    finally:
        esp._port.close()


if __name__=='__main__':main()
