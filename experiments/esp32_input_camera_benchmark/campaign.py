"""Input/camera experiment. Every installed board is restored in finally."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'experiments/multiclient_hardware'))
from campaign import Board, BOARDS
sys.path.insert(0,str(HERE))

NAMES=['reference_hold','lut_hold','reference_early','lut_early','gray_early']

def execute(run,local_only=False,http_smoke_only=False,lut_hold_only=False):
    events=(run/'campaign.jsonl').open('x')
    def emit(event,**kw):
        row=dict(event=event,monotonic=time.monotonic(),**kw)
        events.write(json.dumps(row)+'\n');events.flush()
        (run/'progress.json').write_text(json.dumps(row,indent=2)+'\n')
        print(json.dumps(row),flush=True)
    def flash(operation,name):
        port,mac=BOARDS[name]
        with (run/name/f'{operation}-{time.time_ns()}.log').open('x') as log:
            subprocess.run([sys.executable,str(HERE/'flash_board.py'),operation,'--port',port,
                '--mac',mac,'--directory',str(run/name)],cwd=ROOT,stdout=log,stderr=log,check=True)
    boards={};installed=set();server=None;complete=False
    def install(name):
        installed.add(name);flash('install',name)
        boards[name]=Board(name,run);boards[name].reset()
        if not boards[name].ready.wait(60): raise TimeoutError('Firmware not ready '+name)
    def wait(stage,names,command,timeout):
        before={n:boards[n].snapshot()['counts'].get('sample',0) for n in names}
        lo=time.monotonic();emit('stage_started',stage=stage,boards=names)
        for n in names: boards[n].start(command)
        last=lo
        while True:
            now=time.monotonic();states={n:boards[n].snapshot() for n in names}
            if server.poll() is not None: raise RuntimeError('Server exited')
            for name in names:
                rawpath=run/name/'serial.log'
                with rawpath.open('rb') as raw:
                    raw.seek(max(0,rawpath.stat().st_size-32768))
                    if b'task_wdt:' in raw.read(): raise RuntimeError('Watchdog output invalidates stage '+stage)
            if any(v['errors'] or v['counts'].get('rejected',0) for v in states.values()):
                raise RuntimeError('Device error/rejection '+json.dumps(states))
            if all(v['done'] for v in states.values()):
                emit('stage_completed',stage=stage,started=lo,elapsed=now-lo,
                     samples={n:v['counts'].get('sample',0)-before[n] for n,v in states.items()},expected_camera_frames=200 if local_only else 20 if http_smoke_only else 1000,transport='local_no_http' if local_only else 'http_v2')
                return
            if now-lo>timeout: raise TimeoutError(stage)
            if now-last>30:
                emit('progress',stage=stage,elapsed=round(now-lo),samples={n:v['counts'].get('sample',0)-before[n] for n,v in states.items()});last=now
            time.sleep(.5)
    def configure(names,variant):
        for n in names: boards[n].link.write(str(variant).encode());boards[n].link.flush()
        time.sleep(.3)
    def stop(signum,frame): raise KeyboardInterrupt('Restoring after signal')
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    try:
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',8000))==0: raise RuntimeError('Port 8000 occupied')
        subprocess.run(['adb','reverse','tcp:8000','tcp:8000'],check=True)
        env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),TF_CPP_MIN_LOG_LEVEL='3',CUDA_VISIBLE_DEVICES='-1')
        log=(run/'server-process.log').open('x')
        server=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-u',str(ROOT/'experiments/multiclient_hardware/audit_server.py'),'--output',str(run/'server')],env=env,cwd=ROOT,stdout=log,stderr=log)
        import urllib.request
        for _ in range(200):
            if server.poll() is not None: raise RuntimeError('Server startup failed')
            try:
                urllib.request.urlopen('http://127.0.0.1:8000/openapi.json',timeout=.3).close();break
            except OSError: time.sleep(.1)
        else: raise TimeoutError('Server startup')
        install('A')
        b=boards['A'];b.link.write(b'v');b.link.flush()
        deadline=time.monotonic()+180
        while b.snapshot()['counts'].get('validation_done',0)==0:
            if b.snapshot()['errors']: raise RuntimeError('Input validation failed')
            if time.monotonic()>deadline: raise TimeoutError('Input validation')
            time.sleep(.5)
        emit('input_validation_completed')
        b.reset()
        if not b.ready.wait(60): raise TimeoutError('Reset after validation')
        # Rotate and reverse order to avoid a fixed drift/variant association.
        orders=((0,1),(1,0),(0,1)) if lut_hold_only else ((0,1,2,3),(3,2,1,0),(1,0,3,2))
        for rep,order in enumerate(orders,1):
            for variant in order:
                if local_only:
                    b.reset()
                    if not b.ready.wait(60): raise TimeoutError('Reset before local stage')
                configure(['A'],variant)
                prefix='smoke' if http_smoke_only else 'single'
                wait(f'{prefix}_r{rep}_{NAMES[variant]}',['A'],'d' if local_only else 's' if http_smoke_only else 'g',650)
        if http_smoke_only:
            from analyze import summarize
            summary=dict(scope='short_http_smoke_20_frames',candidate=None,stages=summarize(run))
            (run/'smoke-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
            complete=True
            emit('measurements_complete',candidate=None,scope='short_http_smoke_20_frames')
            return
        from analyze import summarize, choose
        partial=summarize(run)
        candidate=choose(partial,variants=(1,)) if lut_hold_only else choose(partial)
        (run/'selection.json').write_text(json.dumps(dict(candidate=candidate,statistics=partial),indent=2)+'\n')
        emit('candidate_selected',candidate=candidate)
        if not lut_hold_only:
            configure(['A'],4)
            wait('gray_exploratory',['A'],'d' if local_only else 'g',650)
        if candidate is not None and not local_only:
            install('B')
            for variant in (0,candidate):
                configure(['A','B'],variant)
                wait(f'two_{NAMES[variant]}',['A','B'],'g',900)
            confirmed=True
            if lut_hold_only:
                from analyze import confirm_two
                confirmation=confirm_two(summarize(run),candidate)
                (run/'confirmation.json').write_text(json.dumps(confirmation,indent=2)+'\n')
                confirmed=all(v['passed'] for v in confirmation.values())
                emit('two_board_confirmation',passed=confirmed,boards=confirmation)
            if confirmed:
                configure(['A','B'],candidate)
                wait('two_one_hour',['A','B'],'h',3900)
        scope='lut_hold_http_campaign' if lut_hold_only else 'local_no_http_200_frames' if local_only else 'full_http_campaign'
        complete=True;emit('measurements_complete',candidate=candidate,scope=scope)
    except BaseException as e:
        emit('campaign_error',error=repr(e));raise
    finally:
        # Quiesce both devices before sequential flash restoration. Otherwise
        # the second board can keep sending after its serial log is closed.
        for board in boards.values():
            try:
                board.reset()
                emit('quiesce_reset',board=board.name)
            except BaseException as e:
                emit('quiesce_failed',board=board.name,error=repr(e))
        for board in boards.values():
            try: board.close()
            except BaseException as e: emit('serial_close_failed',board=board.name,error=repr(e))
        failures={}
        for name in sorted(installed):
            try:
                flash('restore',name)
                import serial
                link=serial.Serial();link.port=BOARDS[name][0];link.baudrate=115200;link.timeout=.2;link.dtr=False;link.rts=False;link.open()
                try:
                    link.rts=True;time.sleep(.2);link.rts=False
                    deadline=time.monotonic()+8
                    with (run/name/'restored-boot.log').open('xb') as boot:
                        while time.monotonic()<deadline: boot.write(link.read(4096))
                finally: link.close()
                emit('original_restored',board=name)
            except BaseException as e: failures[name]=repr(e);emit('restore_failed',board=name,error=repr(e))
        if server and server.poll() is None:
            server.terminate()
            try: server.wait(timeout=15)
            except subprocess.TimeoutExpired: server.kill();server.wait()
        (run/'completion.json').write_text(json.dumps(dict(measurements_complete=complete,restore_failures=failures),indent=2)+'\n')
        events.close()
        if failures: raise RuntimeError('Restore needs attention '+json.dumps(failures))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True)
    modes=p.add_mutually_exclusive_group()
    modes.add_argument('--local-only',action='store_true')
    modes.add_argument('--http-smoke-only',action='store_true',help='three short HTTP repetitions per RGB565 variant; no candidate selection or promotion')
    modes.add_argument('--lut-hold-only',action='store_true',help='full original/LUT comparison, then two boards and one hour only if criteria pass')
    a=p.parse_args()
    for name in BOARDS:
        data=json.loads((a.run/name/'hardware.json').read_text())
        if not data['backup_verified']: raise RuntimeError('Unverified backup')
    execute(a.run.resolve(),a.local_only,a.http_smoke_only,a.lut_hold_only)
