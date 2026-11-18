"""Compare transports on B with verified flash backup and unconditional recovery."""
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

def capture(port,directory,round_number,command=None):
    link=link_open(port)
    pending=bytearray();scan=b'';started=False;complete=False;deadline=time.monotonic()+30;camera_frames=1000
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
                        selected=command or "whchcwcwh"[round_number-1]
                        link.write(selected.encode());link.flush();started=True;deadline=time.monotonic()+1800
                        print(f'Round {round_number} started ({selected.strip()})',flush=True)
                    if row['event']=='frame_policy_config':camera_frames=row['camera_frames']
                    if row['event']=='sample' and (row['index']+1)%100==0:
                        print(f'Round {round_number}: {row["index"]+1}/{camera_frames} frames',flush=True)
                    if row['event'] in ('candidate_allocated','validation','done','xclk_phase_begin','xclk_ping_summary','xclk_gate') or (row['event']=='memory' and row['stage'] not in ('frame','network')):
                        print(json.dumps(dict(round=round_number,**row)),flush=True)
                    if row['event']=='done':complete=True;break
                if complete:break
            if not complete:raise TimeoutError('Boot or measurement deadline exceeded')
    finally:link.close()

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--seed',type=Path);p.add_argument('--allocation',choices=('early',),default='early');p.add_argument('--smoke',action='store_true')
    p.add_argument('--smoke-transport',choices=('ws','http-persistent','http-close'),help='Transport for a single smoke boot; requires --smoke')
    p.add_argument('--camera-off',action='store_true',help='Diagnostic smoke without initializing the camera; excludes camera measurements')
    p.add_argument('--camera-paused',action='store_true',help='HTTP smoke with camera initialized, then capture stopped while buffers remain allocated')
    p.add_argument('--activation-memory',choices=('internal','psram'),default='internal',help='PSRAM is an HTTP persistent smoke diagnostic only')
    p.add_argument('--xclk-diagnostic',action='store_true',help='Three independent x boots, ping baseline then XCLK on/off/on/off; no inference server needed')
    p.add_argument('--gate-camera',action='store_true',help='Experimental single-buffer camera: XCLK off during inference/network, on during acquisition')
    frame_policy = p.add_mutually_exclusive_group()
    frame_policy.add_argument('--frame-skip', choices=('baseline', 'shadow', 'active'),
                              help='One gated HTTP persistent boot with per-frame policy telemetry')
    frame_policy.add_argument('--frame-skip-replay', type=Path,
                              help='Run baseline and shadow/active for each distinct candidate in a replay summary')
    p.add_argument('--skip-metric', choices=('global', 'local'))
    p.add_argument('--skip-threshold', type=int)
    p.add_argument('--skip-refresh-ms', type=int)
    p.add_argument('--skip-camera-frames', type=int, help='Camera frames per frame-skip boot, default 1000')
    a=p.parse_args()
    skip_campaign = bool(a.frame_skip or a.frame_skip_replay)
    skip_values = (a.skip_metric, a.skip_threshold, a.skip_refresh_ms)
    if a.skip_camera_frames is not None and (not skip_campaign or not 100 <= a.skip_camera_frames <= 1000):
        p.error('--skip-camera-frames accepts 100..1000 in frame-skip runs')
    if skip_campaign and (a.smoke or a.smoke_transport or a.xclk_diagnostic or a.gate_camera or
                          a.camera_off or a.camera_paused or a.activation_memory != 'internal'):
        p.error('Frame-skip modes select gated HTTP persistent and cannot be combined with other run modes')
    if a.frame_skip in ('shadow', 'active'):
        if None in skip_values:
            p.error('Shadow/active requires --skip-metric, --skip-threshold and --skip-refresh-ms')
    elif any(value is not None for value in skip_values):
        p.error('Explicit skip settings require --frame-skip shadow or active')
    if a.smoke_transport and not a.smoke:p.error('--smoke-transport requires --smoke')
    if a.camera_off and not a.smoke:p.error('--camera-off requires --smoke')
    if a.camera_paused and (not a.smoke or a.smoke_transport!='http-persistent' or a.camera_off or a.activation_memory!='internal'):
        p.error('--camera-paused requires HTTP persistent smoke with internal activation memory and camera enabled')
    if a.activation_memory=='psram' and (not a.smoke or a.smoke_transport!='http-persistent' or a.camera_off):
        p.error('PSRAM diagnostic requires --smoke --smoke-transport http-persistent with camera enabled')
    if a.xclk_diagnostic and (a.smoke or a.smoke_transport or a.camera_off or a.camera_paused or a.activation_memory!='internal'):
        p.error('--xclk-diagnostic cannot be combined with transport/camera smoke options')
    if a.gate_camera and (a.xclk_diagnostic or a.camera_off or a.camera_paused or a.activation_memory!='internal'):
        p.error('--gate-camera requires camera enabled, internal activation memory, and no other camera diagnostic')
    smoke_command={'ws':'w','http-persistent':'h','http-close':'c'}[a.smoke_transport or 'ws']
    if a.camera_off:smoke_command=smoke_command.upper()
    if a.activation_memory=='psram':smoke_command='r'
    if a.camera_paused:smoke_command='p'
    commands='xxx' if a.xclk_diagnostic else smoke_command if a.smoke else 'whchcwcwh'
    if a.gate_camera:commands=commands.translate(str.maketrans('whc','123'))
    if skip_campaign:
        def frame_command(mode, metric, threshold, refresh):
            if (metric not in ('global', 'local') or type(threshold) is not int or
                    type(refresh) is not int or not 1 <= threshold <= 255 or not 1 <= refresh <= 5000):
                p.error('Expected global/local, threshold 1..255 and refresh 1..5000 ms')
            return f'F{mode[0]} {metric[0]} {threshold} {refresh} {a.skip_camera_frames or 1000}\n'

        baseline = frame_command('baseline', 'global', 1, 1500)
        if a.frame_skip_replay:
            data = json.loads(a.frame_skip_replay.read_text())['hardware_candidates']
            candidates = ((item['metric'], item['threshold'], item['refresh_ms']) for item in data.values())
            commands = [baseline]
            for candidate in dict.fromkeys(candidates):
                commands.extend(frame_command(mode, *candidate) for mode in ('shadow', 'active'))
        elif a.frame_skip == 'baseline':
            commands = [baseline]
        else:
            commands = [frame_command(a.frame_skip, *skip_values)]
    mac=MACS['B'];port=f'/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_{mac.upper()}-if00'
    if not os.access(port,os.R_OK|os.W_OK):raise RuntimeError('B USB serial unavailable')
    if subprocess.run(['fuser',port],capture_output=True).returncode==0:raise RuntimeError('Serial occupied')
    from prepare import prepare,check_network
    check_network();prepare()
    env=dict(os.environ,IDF_COMPONENT_MANAGER='0',PLATFORMIO_CORE_DIR=str((ROOT/'experiments/esp32_deadzone_benchmark/results/platformio-core').resolve()))
    env['PLATFORMIO_BUILD_FLAGS']='-DBENCH_ESP_NN=1 -DFIT_EARLY_ARENA='+('1' if a.allocation=='early' else '0')
    # Always rebuild before touching USB, so the private network header cannot be stale.
    buildlog=HERE/'artifacts/build.log'
    with buildlog.open('w') as log:
        subprocess.run([str(ROOT/'experiments/esp32_deadzone_benchmark/results/build-tools/bin/pio'),'run','-d',str(HERE/'idf')],env=env,cwd=ROOT,stdout=log,stderr=log,check=True)
    if not os.access(port,os.R_OK|os.W_OK):raise RuntimeError('B USB serial unavailable')
    if subprocess.run(['fuser',port],capture_output=True).returncode==0:raise RuntimeError('Serial occupied')
    run=a.run.resolve();run.mkdir(parents=True,exist_ok=False);directory=run/'board';directory.mkdir()
    sources=list(HERE.glob('*.py'))+list(HERE.glob('*.md'))+list(HERE.glob('*.json'))+[HERE/'esp-nn-strip.patch']
    sources+=list((HERE/'idf/src').glob('*'))+[HERE/'idf'/f for f in ('CMakeLists.txt','sdkconfig.defaults','sdkconfig.espnn','platformio.ini','partitions.csv')]
    sources+=[HERE/'include/network.local.example.h',HERE/'include/generated/nopad_model.h',HERE/'include/generated/expected_scores.h',HERE/'artifacts/model-registry.json',HERE/'artifacts/int8-prefix-nopad.tflite',
              HERE/'artifacts/patched-components.json',ROOT/'experiments/esp32_representation_benchmark/include/generated/assets.h',COMMON]
    hashes={}
    for source in sources:
        if not source.is_file():continue
        target=run/'sources'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target);hashes[str(source.relative_to(ROOT))]=sha(source)
    for source in (HERE/'idf/components').rglob('*'):
        if source.is_file() and not any(x in source.parts for x in ('.git','__pycache__')):hashes[str(source.relative_to(ROOT))]=sha(source)
    firmware=run/'firmware';firmware.mkdir()
    build_dir=Path(env.get('PLATFORMIO_BUILD_DIR', HERE/'idf/.pio/build')).resolve()
    for name in ('bootloader.bin','partitions.bin','firmware.bin'):
        source=build_dir/'espnn'/name
        shutil.copyfile(source,firmware/name)
        hashes['firmware/'+name]=sha(source)
    shutil.copyfile(buildlog,run/'build.log')
    if a.frame_skip_replay:
        shutil.copyfile(a.frame_skip_replay, run/'replay-summary.json')
    (run/'configuration.json').write_text(json.dumps(dict(allocation_order=a.allocation,build_flags=env['PLATFORMIO_BUILD_FLAGS'],commands=commands,camera_enabled=not a.camera_off,camera_paused=a.camera_paused,activation_memory=a.activation_memory,xclk_diagnostic=a.xclk_diagnostic,gate_camera=a.gate_camera or skip_campaign,frame_skip=skip_campaign),indent=2)+'\n')
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
        print('Transport firmware installed and verified',flush=True)
        for r,command in enumerate(commands,1):capture(port,directory,r,command);rounds+=1
    except BaseException as exc:error=repr(exc);print('Run error: '+error,flush=True)
    finally:
        # A second interrupt must not abandon restoration in the middle of a flash write.
        signal.signal(signal.SIGINT,signal.SIG_IGN);signal.signal(signal.SIGTERM,signal.SIG_IGN)
        try:
            if installed:common('restore')
            if touched:boot=boot_original(port,directory/'restored-boot.log')
            if touched and not boot:raise RuntimeError('Original application boot unconfirmed')
        except BaseException as exc:restore_error=repr(exc)
        (run/'completion.json').write_text(json.dumps(dict(measurements_complete=rounds==len(commands),rounds_completed=rounds,error=error,restore_error=restore_error,original_boot_confirmed=boot,board='B'),indent=2)+'\n')
        print('Original firmware restored and boot confirmed' if not restore_error and boot else 'Restoration needs attention: '+str(restore_error),flush=True)
    if error or restore_error:raise RuntimeError(json.dumps(dict(error=error,restore_error=restore_error)))

if __name__=='__main__':main()
