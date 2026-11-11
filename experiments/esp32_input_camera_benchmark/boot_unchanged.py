"""Boot the backed-up, never flashed B board after a local-only campaign."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import serial

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    meta=json.loads((a.run/'B/hardware.json').read_text())
    if meta['mac']!='24:ec:4a:0e:c3:14' or not meta['backup_verified'] or 'installed_sha256' in meta:
        raise ValueError('B is not the expected unmodified, backed-up board')
    port=meta['port']
    if subprocess.run(['fuser',port],capture_output=True).returncode==0: raise RuntimeError('B port occupied')
    output=a.run/'B/unchanged-boot.log'
    with output.open('xb') as log:
        link=serial.Serial();link.port=port;link.baudrate=115200;link.timeout=.2;link.dtr=False;link.rts=False;link.open()
        try:
            link.rts=True;time.sleep(.2);link.rts=False
            until=time.monotonic()+8
            while time.monotonic()<until: log.write(link.read(4096))
        finally: link.close()
    if b'sciot_esp32_client' not in output.read_bytes(): raise RuntimeError('Original B boot unconfirmed')
    print('Unmodified original B firmware boot confirmed; no flash writes.')
if __name__=='__main__': main()
