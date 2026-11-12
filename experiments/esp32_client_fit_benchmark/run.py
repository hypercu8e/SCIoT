"""Client fit test on one board: phases N/R/N/R with the HTTP v2 server, verified backup and unconditional recovery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import serial
from esptool import cmds

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
COMMON=ROOT/'experiments/multiclient_hardware/flash_board.py'
SERVER=ROOT/'experiments/multiclient_hardware/audit_server.py'
MACS={'A':'24:ec:4a:0e:b7:6c','B':'24:ec:4a:0e:c3:14'}
PHASES=('N','R','N','R')
PHASE_SECONDS=1200
PANIC=(b'task_wdt:',b'Guru Meditation Error',b'Brownout detector',b'abort() was called',b'Rebooting...')
# The firmware stops (returns from app_main) after these: the phase cannot go on.
FATAL={'mode_timeout','reserve_unavailable','buffers','arena','allocate_tensors','kernel_probe_invoke',
       'optimized_kernel_not_reached','wifi_connection','registration','camera_init'}

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

def reset(link):
    link.rts=True;time.sleep(.2);link.rts=False

def boot_original(port,path):
    link=link_open(port)
    try:
        reset(link);end=time.monotonic()+8
        with path.open('xb') as log:
            while time.monotonic()<end:log.write(link.read(65536))
    finally:link.close()
    return b'sciot_esp32_client' in path.read_bytes()

def wait_server(process,port,deadline):
    while time.monotonic()<deadline:
        if process.poll() is not None:raise RuntimeError('Server exited during startup')
        try:
            with socket.create_connection(('127.0.0.1',port),timeout=1):return
        except OSError:time.sleep(.5)
    raise TimeoutError('Server not listening')

def phase(link,index,mode,raw,events,max_errors=None):
    """Reset, choose the mode, run 'g' once. Returns the phase outcome.
    With max_errors, the phase stops as failed at the first error beyond it."""
    reset(link);pending=bytearray();scan=b'';state='boot';deadline=time.monotonic()+PHASE_SECONDS;errors=0
    while time.monotonic()<deadline:
        data=link.read(65536)
        if not data:continue
        raw.write(data);raw.flush();scan=scan+data
        if any(v in scan for v in PANIC):return dict(phase=index,mode=mode,ok=False,reason='panic_or_reset')
        scan=scan[-128:];pending.extend(data)
        while b'\n' in pending:
            line,_,rest=pending.partition(b'\n');pending=bytearray(rest)
            if not line.startswith(b'{'):continue
            try:row=json.loads(line)
            except (ValueError,UnicodeError):return dict(phase=index,mode=mode,ok=False,reason='corrupt_json')
            events.write(json.dumps(dict(host_monotonic=time.monotonic(),phase=index,mode=mode,row=row))+'\n');events.flush()
            e=row['event']
            if e in ('reserve','registration','camera_init','done','wifi_disconnected') or (e=='error'):
                print(json.dumps({**row,"phase":index,"phase_mode":mode}),flush=True)
            if e=='error' and row.get('reason') in FATAL:return dict(phase=index,mode=mode,ok=False,reason=row['reason'])
            if e=='error':
                errors+=1
                if max_errors is not None and errors>max_errors:return dict(phase=index,mode=mode,ok=False,reason='too_many_errors')
            if e=='mode_prompt' and state=='boot':link.write(mode.encode());link.flush();state='mode'
            elif e=='ready' and state=='mode':link.write(b'g');link.flush();state='running'
            elif e=='registration' and state=='running':state='registered'
            elif e=='done' and state=='registered':state='done'
            elif e=='ready' and state=='done':return dict(phase=index,mode=mode,ok=True,reason=None)
    return dict(phase=index,mode=mode,ok=False,reason='timeout_in_'+state)

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    p.add_argument('--board',choices=MACS,default='B');p.add_argument('--seed',type=Path);p.add_argument('--port',type=int,default=8000)
    p.add_argument('--env',choices=('espnn','psramnet'),default='espnn');p.add_argument('--max-errors',type=int)
    a=p.parse_args();run=a.run.resolve();run.mkdir(parents=True,exist_ok=False)
    directory=run/'board';directory.mkdir()
    mac=MACS[a.board];port=f'/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_{mac.upper()}-if00'
    if not os.access(port,os.R_OK|os.W_OK):raise RuntimeError('Serial permission unavailable')
    if subprocess.run(['fuser',port],capture_output=True).returncode==0:raise RuntimeError('Serial occupied')
    sources=[HERE/f for f in ('run.py','analyze.py','README.md')]+list((HERE/'idf/src').glob('*'))
    sources+=[HERE/'idf'/f for f in ('CMakeLists.txt','sdkconfig.defaults','sdkconfig.defaults.psramnet','platformio.ini','partitions.csv','sdkconfig.'+a.env)]
    sources+=[SERVER,COMMON]
    hashes={}
    for source in sources:
        target=run/'sources'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target);hashes[str(source.relative_to(ROOT))]=sha(source)
    for component in (HERE/'idf/components').rglob('*'):
        if component.is_file() and '.git' not in component.parts:hashes[str(component.relative_to(ROOT))]=sha(component)
    firmware=run/'firmware';firmware.mkdir()  # contains Wi-Fi credentials: results/ is ignored by Git
    for name in ('bootloader.bin','partitions.bin','firmware.bin'):
        source=HERE/'idf/.pio/build'/a.env/name;shutil.copyfile(source,firmware/name)
        hashes[str(source.relative_to(ROOT))]=sha(source)
    (run/'source-sha256.json').write_text(json.dumps(hashes,indent=2)+'\n')
    (run/'git-state.txt').write_text(subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True))
    def common(operation):
        args=[sys.executable,str(COMMON),operation,'--port',port,'--mac',mac,'--directory',str(directory)]
        if operation=='backup' and a.seed:args+=['--seed',str(a.seed.resolve())]
        with (directory/(operation+'.log')).open('x') as log:
            subprocess.run(args,cwd=ROOT,stdout=log,stderr=log,check=True)
    def interrupted(signum,frame):raise KeyboardInterrupt('Signal received; restoring original flash')
    signal.signal(signal.SIGINT,interrupted);signal.signal(signal.SIGTERM,interrupted)
    touched=installed=False;link=server=None;error=None;restore_error=None;boot=False;outcomes=[]
    server_log=(run/'server-process.log').open('x')
    try:
        touched=True;common('backup');print('Backup verified',flush=True)
        installed=True
        with (directory/'install.log').open('x') as log:
            from contextlib import redirect_stdout,redirect_stderr
            with redirect_stdout(log),redirect_stderr(log):install(port,mac,directory,firmware)
        print('Fit-test firmware installed and verified',flush=True)
        env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),TF_CPP_MIN_LOG_LEVEL='3',CUDA_VISIBLE_DEVICES='-1')
        server=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-u',str(SERVER),'--output',str(run/'server'),'--port',str(a.port)],
                                cwd=ROOT,env=env,stdout=server_log,stderr=server_log)
        wait_server(server,a.port,time.monotonic()+120);print('Server listening',flush=True)
        link=link_open(port)
        with (directory/'serial.log').open('xb') as raw,(directory/'events.jsonl').open('x') as events:
            for index,mode in enumerate(PHASES,1):
                if server.poll() is not None:raise RuntimeError('Server exited')
                outcome=phase(link,index,mode,raw,events,a.max_errors);outcomes.append(outcome)
                print(json.dumps(dict(event='phase_end',**outcome)),flush=True)
                if outcome['reason'] in ('registration','wifi_connection'):
                    raise RuntimeError('Board cannot register: check firewall / SERVER_BASE_URL')
            reset(link)  # stop the client before the server and the log close
            end=time.monotonic()+2
            while time.monotonic()<end:raw.write(link.read(65536))
    except BaseException as exc:
        error=repr(exc);print('Run error: '+error,flush=True)
    finally:
        if link:
            try:link.close()
            except BaseException as exc:print('Serial close error: '+repr(exc),flush=True)
        if server and server.poll() is None:
            server.terminate()
            try:server.wait(timeout=15)
            except subprocess.TimeoutExpired:server.kill();server.wait()
        server_log.close()
        try:
            if installed:common('restore')
            if touched:boot=boot_original(port,directory/'restored-boot.log')
            if touched and not boot:raise RuntimeError('Original application boot unconfirmed')
        except BaseException as exc:restore_error=repr(exc)
        complete=len(outcomes)==len(PHASES)
        (run/'completion.json').write_text(json.dumps(dict(phases_attempted=len(outcomes),all_phases_attempted=complete,outcomes=outcomes,
            error=error,restore_error=restore_error,original_boot_confirmed=boot,board=a.board,env=a.env,max_errors=a.max_errors),indent=2)+'\n')
        print('Original firmware restored and boot confirmed' if not restore_error and boot else 'Restoration needs attention: '+str(restore_error),flush=True)
    if error or restore_error:raise RuntimeError(json.dumps(dict(error=error,restore_error=restore_error)))

if __name__=='__main__':main()
