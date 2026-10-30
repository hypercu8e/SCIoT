"""Capture one complete run and send g only after firmware readiness."""
import argparse
import json
from pathlib import Path
import time

import serial


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True)
    p.add_argument('--log',type=Path,required=True)
    p.add_argument('--timeout',type=float,default=600)
    p.add_argument('--reset',action='store_true',help='Reset USB-JTAG board after opening serial, before collecting boot')
    args=p.parse_args()
    args.log.parent.mkdir(parents=True,exist_ok=True)
    if args.log.exists():
        raise ValueError('Refusing to overwrite existing capture')
    s=serial.Serial()
    s.port=args.port;s.baudrate=115200;s.timeout=0.25;s.dtr=False;s.rts=False
    s.open()
    if args.reset:
        s.reset_input_buffer()
        # Same USB-JTAG hard-reset sequence used by esptool; no flash writes.
        s.rts=True;time.sleep(.2);s.rts=False;time.sleep(.2)
    pending=bytearray();started=False
    deadline=time.monotonic()+args.timeout
    try:
        with args.log.open('xb') as f:
            while time.monotonic()<deadline:
                data=s.read(4096)
                if not data:
                    continue
                f.write(data);f.flush();pending.extend(data)
                while b'\n' in pending:
                    line,_,rest=pending.partition(b'\n');pending=bytearray(rest)
                    try:
                        row=json.loads(line.decode(errors='replace'))
                    except (ValueError,UnicodeError):
                        continue
                    print(json.dumps(row),flush=True)
                    if row.get('event')=='ready' and not started:
                        s.write(b'g');s.flush();started=True
                    if row.get('event')=='error':
                        return 2
                    if row.get('event')=='done':
                        return 0
        print('Capture timeout; incomplete log retained',flush=True)
        return 3
    finally:
        s.close()


if __name__=='__main__':
    raise SystemExit(main())
