"""Capture a bounded serial boot log after restoring the pre-test firmware."""
import argparse
import json
from pathlib import Path
import time
import serial


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=8)
    p.add_argument('--reset',action='store_true')
    args=p.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists():raise ValueError('Refusing to overwrite a serial capture')
    device=serial.Serial()
    device.port=args.port;device.baudrate=115200;device.timeout=.25
    device.dtr=False;device.rts=False;device.open()
    try:
        if args.reset:
            device.reset_input_buffer();device.rts=True;time.sleep(.2);device.rts=False;time.sleep(.2)
        deadline=time.monotonic()+args.seconds
        with args.output.open('xb') as output:
            while time.monotonic()<deadline:
                chunk=device.read(16384)
                if chunk:output.write(chunk);output.flush()
    finally:device.close()
    text=args.output.read_text(errors='replace')
    project='Project name:     sciot_esp32_client' in text
    version='App version:      0.1.0' in text
    model='model=fomo_224' in text
    print(json.dumps({'output':str(args.output),'original_project':project,
                      'original_version':version,'original_model':model}))
    return 0 if project and version and model else 2

if __name__=='__main__':raise SystemExit(main())
