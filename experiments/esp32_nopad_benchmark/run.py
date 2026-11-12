"""One-board PAD-free prefix comparison with verified flash backup and unconditional recovery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import serial
from esptool import cmds

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
COMMON=ROOT/'experiments/multiclient_hardware/flash_board.py'
MACS={'A':'24:ec:4a:0e:b7:6c','B':'24:ec:4a:0e:c3:14'}

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def install(port,mac,directory,firmware):
    meta=json.loads((directory/'hardware.json').read_text())
    if not meta['backup_verified'] or meta['mac']!=mac or sha(directory/'original-flash.bin')!=meta['backup_sha256']:
        raise ValueError('Backup not verified or changed')
    esp=cmds.detect_chip(port)
    try:
        actual=':'.join(f'{v:02x}' for v in esp.read_mac())
        if esp.CHIP_NAME!='ESP32-S3' or actual!=mac:raise ValueError('Board identity changed')
        esp=cmds.run_stub(esp);esp.change_baud(921600);cmds.attach_flash(esp)
        if (esp.flash_id()>>16)&255!=23:raise ValueError('Expected 8 MiB flash')
        parts=[(offset,str(firmware/name)) for offset,name in ((0,'bootloader.bin'),(0x8000,'partitions.bin'),(0x10000,'firmware.bin'))]
        meta.update(installed_sha256=sha(firmware/'firmware.bin'),restored=False)
        (directory/'hardware.json').write_text(json.dumps(meta,indent=2)+'\n')
        cmds.write_flash(esp,parts,compress=True);cmds.verify_flash(esp,parts)
    finally:esp._port.close()

def link_open(port):
    link=serial.Serial();link.port=port;link.baudrate=115200;link.timeout=.1
    link.dtr=False;link.rts=False;link.open();return link

def boot_original(port,path):
    link=link_open(port)
    try:
        link.rts=True;time.sleep(.2);link.rts=False
        end=time.monotonic()+8
        with path.open('xb') as log:
            while time.monotonic()<end:log.write(link.read(65536))
    finally:link.close()
    return b'sciot_esp32_client' in path.read_bytes()

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--board',choices=MACS,default='B');p.add_argument('--seed',type=Path)
    a=p.parse_args();run=a.run.resolve();run.mkdir(parents=True,exist_ok=False)
    directory=run/'board';directory.mkdir()
    mac=MACS[a.board];port=f'/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_{mac.upper()}-if00'
    if not os.access(port,os.R_OK|os.W_OK):raise RuntimeError('Serial permission unavailable')
    if subprocess.run(['fuser',port],capture_output=True).returncode==0:raise RuntimeError('Serial occupied')
    sources=list(HERE.glob('*.py'))+list(HERE.glob('*.md'))+list(HERE.glob('*.cpp'))+list((HERE/'idf/src').glob('*'))
    sources += [HERE/'idf'/f for f in ('CMakeLists.txt','sdkconfig.defaults','platformio.ini','partitions.csv')]
    sources += [ROOT/'experiments/esp32_representation_benchmark/include/generated/assets.h',
                HERE/'include/generated/nopad_model.h',HERE/'artifacts/int8-prefix-nopad.tflite']
    hashes={}
    for source in sources:
        target=run/'sources'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target);hashes[str(source.relative_to(ROOT))]=sha(source)
    for component in (HERE/'idf/components').rglob('*'):
        if component.is_file() and '.git' not in component.parts:hashes[str(component.relative_to(ROOT))]=sha(component)
    firmware=run/'firmware';firmware.mkdir()
    for name in ('bootloader.bin','partitions.bin','firmware.bin'):
        source=HERE/'idf/.pio/build/espnn'/name;shutil.copyfile(source,firmware/name)
        hashes[str(source.relative_to(ROOT))]=sha(source)
    (run/'source-sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    (run/'git-state.txt').write_text(subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True))
    env=dict(os.environ,TF_CPP_MIN_LOG_LEVEL='3',CUDA_VISIBLE_DEVICES='-1')
    subprocess.run([str(ROOT/'.venv/bin/python'),str(HERE/'describe_model.py'),'--output',str(run/'model-map.json')],cwd=ROOT,env=env,check=True)
    subprocess.run([str(ROOT/'.venv/bin/python'),str(HERE/'describe_model.py'),'--model',str(HERE/'artifacts/int8-prefix-nopad.tflite'),
                    '--output',str(run/'model-map-nopad.json')],cwd=ROOT,env=env,check=True)
    def common(operation):
        args=[sys.executable,str(COMMON),operation,'--port',port,'--mac',mac,'--directory',str(directory)]
        if operation=='backup' and a.seed:args+=['--seed',str(a.seed.resolve())]
        with (directory/(operation+'.log')).open('x') as log:
            subprocess.run(args,cwd=ROOT,stdout=log,stderr=log,check=True)
    def interrupted(signum,frame):raise KeyboardInterrupt('Signal received; restoring original flash')
    signal.signal(signal.SIGINT,interrupted);signal.signal(signal.SIGTERM,interrupted)
    touched=installed=complete=False;link=None;error=None;restore_error=None;boot=False
    try:
        touched=True;common('backup');print('Backup verified',flush=True)
        installed=True
        with (directory/'install.log').open('x') as log:
            from contextlib import redirect_stdout,redirect_stderr
            with redirect_stdout(log),redirect_stderr(log):install(port,mac,directory,firmware)
        print('PAD-free benchmark firmware installed and verified',flush=True)
        link=link_open(port);link.rts=True;time.sleep(.2);link.rts=False
        pending=bytearray();scan=b'';started=False;deadline=time.monotonic()+45
        with (directory/'serial.log').open('xb') as raw,(directory/'events.jsonl').open('x') as events:
            while time.monotonic()<deadline:
                data=link.read(65536)
                if not data:continue
                raw.write(data);raw.flush();scan=(scan+data)
                if any(v in scan for v in (b'task_wdt:',b'Guru Meditation Error',b'Brownout detector')):
                    raise RuntimeError('Watchdog/panic/brownout output invalidates run')
                scan=scan[-128:];pending.extend(data)
                while b'\n' in pending:
                    line,_,rest=pending.partition(b'\n');pending=bytearray(rest)
                    if not line.startswith(b'{'):continue
                    try:row=json.loads(line)
                    except (ValueError,UnicodeError):raise RuntimeError('Corrupt JSON event')
                    events.write(json.dumps(dict(host_monotonic=time.monotonic(),row=row))+'\n');events.flush()
                    if row['event']=='error':raise RuntimeError('Firmware error: '+json.dumps(row))
                    if row['event']=='ready' and not started:
                        link.write(b'g');link.flush();started=True;deadline=time.monotonic()+1200
                        print('Measurement started',flush=True)
                    if row['event'] in ('heap','activation_peak','block_done'):print(json.dumps(row),flush=True)
                    if row['event']=='internal_arena_unavailable':raise RuntimeError('Internal arena unavailable: '+json.dumps(row))
                    if row['event']=='done':complete=True;break
                if complete:break
            if not complete:raise TimeoutError('Firmware ready/profile deadline exceeded')
    except BaseException as exc:
        error=repr(exc);print('Run error: '+error,flush=True)
    finally:
        if link:
            try:link.close()
            except BaseException as exc:print('Serial close error: '+repr(exc),flush=True)
        try:
            if installed:common('restore')
            if touched:boot=boot_original(port,directory/'restored-boot.log')
            if touched and not boot:raise RuntimeError('Original application boot unconfirmed')
        except BaseException as exc:restore_error=repr(exc)
        (run/'completion.json').write_text(json.dumps(dict(measurements_complete=complete,error=error,restore_error=restore_error,original_boot_confirmed=boot,board=a.board),indent=2)+'\n')
        print('Original firmware restored and boot confirmed' if not restore_error and boot else 'Restoration needs attention: '+str(restore_error),flush=True)
    if error or restore_error:raise RuntimeError(json.dumps(dict(error=error,restore_error=restore_error)))

if __name__=='__main__':main()
