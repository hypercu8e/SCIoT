"""Three independent camera/Wi-Fi memory-fit boots with verified flash backup and unconditional recovery."""
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

def capture(port,directory,round_number):
    link=link_open(port)
    pending=bytearray();scan=b'';started=False;complete=False;deadline=time.monotonic()+30
    try:
        link.rts=True;time.sleep(.2);link.rts=False
        with (directory/f'round-{round_number}.serial.log').open('xb') as raw, (directory/f'round-{round_number}.events.jsonl').open('x') as events:
            while time.monotonic()<deadline:
                data=link.read(65536)
                if not data:continue
                raw.write(data);raw.flush();scan+=data
                if any(x in scan for x in (b'task_wdt:',b'Guru Meditation Error',b'Brownout detector',b'abort() was called')):
                    raise RuntimeError('Device panic/watchdog/brownout')
                scan=scan[-128:];pending.extend(data)
                while b'\n' in pending:
                    line,_,rest=pending.partition(b'\n');pending=bytearray(rest)
                    if not line.startswith(b'{'):continue
                    try:row=json.loads(line)
                    except (ValueError,UnicodeError):raise RuntimeError('Corrupt device JSON')
                    events.write(json.dumps(dict(host_monotonic=time.monotonic(),row=row))+'\n');events.flush()
                    if row['event']=='error':raise RuntimeError('Firmware error: '+json.dumps(row))
                    if row['event']=='ready' and not started:
                        link.write(b'g');link.flush();started=True;deadline=time.monotonic()+600
                        print(f'Round {round_number} started',flush=True)
                    if row['event']=='sample' and (row['index']+1)%100==0:
                        print(f'Round {round_number}: {row["index"]+1}/1000 frames',flush=True)
                    if row['event'] in ('candidate_allocated','validation','done') or (row['event']=='memory' and row['stage']!='frame'):
                        print(json.dumps(dict(round=round_number,**row)),flush=True)
                    if row['event']=='done':complete=True;break
                if complete:break
            if not complete:raise TimeoutError('Boot or measurement deadline exceeded')
    finally:link.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--seed',type=Path);p.add_argument('--allocation',choices=('early','late'),default='late')
    a=p.parse_args()
    from prepare import prepare,check_network
    check_network();prepare()
    env=dict(os.environ,IDF_COMPONENT_MANAGER='0',PLATFORMIO_CORE_DIR=str(ROOT/'experiments/esp32_deadzone_benchmark/results/platformio-core'))
    env['PLATFORMIO_BUILD_FLAGS']='-DBENCH_ESP_NN=1 -DFIT_EARLY_ARENA='+('1' if a.allocation=='early' else '0')
    # Always rebuild before touching USB, so the private network header cannot be stale.
    buildlog=HERE/'artifacts/build.log'
    with buildlog.open('w') as log:
        subprocess.run([str(ROOT/'experiments/esp32_deadzone_benchmark/results/build-tools/bin/pio'),'run','-d',str(HERE/'idf')],env=env,cwd=ROOT,stdout=log,stderr=log,check=True)
    mac=MACS['B'];port=f'/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_{mac.upper()}-if00'
    if not os.access(port,os.R_OK|os.W_OK):raise RuntimeError('B USB serial unavailable')
    if subprocess.run(['fuser',port],capture_output=True).returncode==0:raise RuntimeError('Serial occupied')
    run=a.run.resolve();run.mkdir(parents=True,exist_ok=False);directory=run/'board';directory.mkdir()
    sources=list(HERE.glob('*.py'))+list(HERE.glob('*.md'))+list(HERE.glob('*.json'))+[HERE/'esp-nn-strip.patch']
    sources+=list((HERE/'idf/src').glob('*'))+[HERE/'idf'/f for f in ('CMakeLists.txt','sdkconfig.defaults','sdkconfig.espnn','platformio.ini','partitions.csv')]
    sources+=[HERE/'include/network.local.example.h',HERE/'include/generated/nopad_model.h',HERE/'artifacts/int8-prefix-nopad.tflite',
              HERE/'artifacts/patched-components.json',ROOT/'experiments/esp32_representation_benchmark/include/generated/assets.h',COMMON]
    hashes={}
    for source in sources:
        if not source.is_file():continue
        target=run/'sources'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target);hashes[str(source.relative_to(ROOT))]=sha(source)
    for source in (HERE/'idf/components').rglob('*'):
        if source.is_file() and not any(x in source.parts for x in ('.git','__pycache__')):hashes[str(source.relative_to(ROOT))]=sha(source)
    firmware=run/'firmware';firmware.mkdir()
    for name in ('bootloader.bin','partitions.bin','firmware.bin'):
        source=HERE/'idf/.pio/build/espnn'/name;shutil.copyfile(source,firmware/name);hashes[str(source.relative_to(ROOT))]=sha(source)
    shutil.copyfile(buildlog,run/'build.log')
    (run/'configuration.json').write_text(json.dumps(dict(allocation_order=a.allocation,build_flags=env['PLATFORMIO_BUILD_FLAGS']),indent=2)+'\n')
    (run/'source-sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    (run/'git-state.txt').write_text(subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True))
    def common(operation):
        args=[sys.executable,str(COMMON),operation,'--port',port,'--mac',mac,'--directory',str(directory)]
        if operation=='backup' and a.seed:args+=['--seed',str(a.seed.resolve())]
        with (directory/(operation+'.log')).open('x') as log:subprocess.run(args,cwd=ROOT,stdout=log,stderr=log,check=True)
    def interrupted(signum,frame):raise KeyboardInterrupt('Interrupted; restoring original flash')
    signal.signal(signal.SIGINT,interrupted);signal.signal(signal.SIGTERM,interrupted)
    touched=installed=False;rounds=0;error=restore_error=None;boot=False
    try:
        touched=True;common('backup');print('Backup verified',flush=True)
        installed=True
        with (directory/'install.log').open('x') as log:
            from contextlib import redirect_stdout,redirect_stderr
            with redirect_stdout(log),redirect_stderr(log):install(port,mac,directory,firmware)
        print('Memory-fit firmware installed and verified',flush=True)
        for r in range(1,4):capture(port,directory,r);rounds+=1
    except BaseException as exc:error=repr(exc);print('Run error: '+error,flush=True)
    finally:
        # A second interrupt must not abandon restoration in the middle of a flash write.
        signal.signal(signal.SIGINT,signal.SIG_IGN);signal.signal(signal.SIGTERM,signal.SIG_IGN)
        try:
            if installed:common('restore')
            if touched:boot=boot_original(port,directory/'restored-boot.log')
            if touched and not boot:raise RuntimeError('Original application boot unconfirmed')
        except BaseException as exc:restore_error=repr(exc)
        (run/'completion.json').write_text(json.dumps(dict(measurements_complete=rounds==3,rounds_completed=rounds,error=error,restore_error=restore_error,original_boot_confirmed=boot,board='B'),indent=2)+'\n')
        print('Original firmware restored and boot confirmed' if not restore_error and boot else 'Restoration needs attention: '+str(restore_error),flush=True)
    if error or restore_error:raise RuntimeError(json.dumps(dict(error=error,restore_error=restore_error)))

if __name__=='__main__':main()
