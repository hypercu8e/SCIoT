"""Explicit per-board backup/install/restore; verify before leaving the same connection."""
import argparse
import hashlib
import json
from pathlib import Path
from esptool import cmds
from esptool.util import FatalError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=('backup', 'install', 'restore'))
    p.add_argument('--port', required=True)
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--mac', required=True)
    p.add_argument('--seed', type=Path)
    a = p.parse_args()
    a.directory.mkdir(parents=True, exist_ok=True)
    meta = a.directory / 'hardware.json'
    backup = a.directory / 'original-flash.bin'
    esp = cmds.detect_chip(a.port)
    try:
        if esp.CHIP_NAME != 'ESP32-S3':
            raise RuntimeError('Unexpected chip')
        mac = ':'.join(f'{v:02x}' for v in esp.read_mac())
        if mac != a.mac.lower():
            raise RuntimeError('Board identity differs from selected USB device')
        esp = cmds.run_stub(esp)
        esp.change_baud(921600)
        cmds.attach_flash(esp)
        if (esp.flash_id() >> 16) & 255 != 23:
            raise RuntimeError('Expected 8 MiB flash')
        if a.operation == 'backup':
            if backup.exists() or meta.exists():
                raise RuntimeError('Refusing to overwrite backup')
            if a.seed:
                previous = json.loads((a.seed.parent/'hardware.json').read_text())
                seed = a.seed.read_bytes()
                if previous['mac'] != mac or len(seed) != 8388608 or hashlib.sha256(seed).hexdigest() != previous['backup_sha256']:
                    raise RuntimeError('Seed is not a verified backup of this board')
                backup.write_bytes(cmds.read_flash(esp, 0, 0x10000)+seed[0x10000:])
                try:
                    cmds.verify_flash(esp, [(0, str(backup))])
                except FatalError:
                    cmds.read_flash(esp, 0, 8388608, str(backup))
            else:
                cmds.read_flash(esp, 0, 8388608, str(backup))
            cmds.verify_flash(esp, [(0, str(backup))])
            if backup.stat().st_size != 8388608:
                raise RuntimeError('Incomplete flash backup')
            meta.write_text(json.dumps(dict(mac=mac, port=a.port, flash_bytes=8388608,
                backup_sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
                backup_verified=True, restored=False), indent=2)+'\n')
        else:
            data = json.loads(meta.read_text())
            if data['mac'] != mac or hashlib.sha256(backup.read_bytes()).hexdigest() != data['backup_sha256']:
                raise RuntimeError('Backup identity or digest differs')
            if a.operation == 'install':
                firmware = Path('src/client/esp32-s3-eye-multiclient/.pio/build/espnn')
                parts = [(n, str(firmware / f)) for n, f in
                         [(0, 'bootloader.bin'), (0x8000, 'partitions.bin'), (0x10000, 'firmware.bin')]]
                data.update(installed_sha256=hashlib.sha256((firmware/'firmware.bin').read_bytes()).hexdigest(), restored=False)
            else:
                parts = [(0, str(backup))]
            cmds.write_flash(esp, parts, compress=True)
            cmds.verify_flash(esp, parts)
            if a.operation == 'restore':
                data.update(restored=True, restored_digest_verified_before_boot=True)
            meta.write_text(json.dumps(data, indent=2)+'\n')
            # The capture process deliberately boots after opening USB serial.
    finally:
        esp._port.close()


if __name__ == '__main__':
    main()
