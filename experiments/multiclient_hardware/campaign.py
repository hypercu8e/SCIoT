"""Authorized two-board campaign; restore both original images in finally.

Use build-tools Python (serial/esptool); server uses the repository TensorFlow venv.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import serial

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BOARDS = {name: (f'/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_{mac.upper()}-if00', mac)
          for name, mac in [('A', '24:ec:4a:0e:b7:6c'), ('B', '24:ec:4a:0e:c3:14')]}


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2)+'\n')
    temporary.replace(path)


class Board:
    def __init__(self, name, root):
        self.name = name
        self.port, self.mac = BOARDS[name]
        self.root = root
        self.link = serial.Serial()
        self.link.port = self.port
        self.link.baudrate = 115200
        self.link.timeout = .1
        self.link.dtr = self.link.rts = False
        self.link.open()
        self.ready = threading.Event()
        self.done = threading.Event()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.counts = Counter()
        self.errors = []
        self.last_sample = None
        self.done_row = None
        self.raw = (root/name/'serial.log').open('xb')
        self.events = (root/name/'events.jsonl').open('x')
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        pending = bytearray()
        try:
            while not self.stop.is_set():
                block = self.link.read(4096)
                if not block:
                    continue
                self.raw.write(block)
                self.raw.flush()
                pending.extend(block)
                while b'\n' in pending:
                    line, _, rest = pending.partition(b'\n')
                    pending = bytearray(rest)
                    try:
                        row = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    now = time.monotonic()
                    self.events.write(json.dumps(dict(host_monotonic=now, row=row))+'\n')
                    self.events.flush()
                    event = row.get('event', 'unknown')
                    with self.lock:
                        self.counts[event] += 1
                        if event == 'sample':
                            self.last_sample = now
                        if event == 'error':
                            self.errors.append(row)
                        if event == 'ready':
                            self.ready.set()
                        if event == 'done':
                            self.done_row = row
                            self.done.set()
        except BaseException as error:
            with self.lock:
                self.errors.append(dict(event='serial_failure', message=str(error)))

    def reset(self):
        self.ready.clear()
        self.done.clear()
        self.link.rts = True
        time.sleep(.2)
        self.link.rts = False

    def start(self, command):
        if not self.ready.wait(45):
            raise RuntimeError(f'{self.name}: firmware not ready; inspect serial log')
        self.done.clear()
        self.link.write(command.encode())
        self.link.flush()

    def snapshot(self):
        with self.lock:
            return dict(counts=dict(self.counts), errors=list(self.errors),
                        last_sample=self.last_sample, done=self.done.is_set(), done_row=self.done_row)

    def close(self):
        self.stop.set()
        self.thread.join(3)
        self.link.close()
        self.raw.close()
        self.events.close()


def flash(operation, name, run):
    port, mac = BOARDS[name]
    with (run/name/f'{operation}.log').open('x') as log:
        subprocess.run([sys.executable, str(HERE/'flash_board.py'), operation,
            '--port', port, '--mac', mac, '--directory', str(run/name)],
            stdout=log, stderr=log, check=True, cwd=ROOT)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--first-board', choices=('A', 'B'), default='A')
    p.add_argument('--single-only', action='store_true',
                   help='diagnostic: stop after the individual stages')
    a = p.parse_args()
    run = a.run.resolve()
    if (run/'campaign.jsonl').exists():
        raise RuntimeError('Campaign output already exists')
    for name in BOARDS:
        m = json.loads((run/name/'hardware.json').read_text())
        if not m['backup_verified'] or m['mac'] != BOARDS[name][1]:
            raise RuntimeError('Missing verified board backup')
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 8000)) == 0:
            raise RuntimeError('Port 8000 already in use')
    events = (run/'campaign.jsonl').open('x')
    def emit(event, **fields):
        row = dict(event=event, monotonic=time.monotonic(), **fields)
        events.write(json.dumps(row)+'\n')
        events.flush()
        print(json.dumps(row), flush=True)
        atomic_json(run/'progress.json', row)
    boards = {}
    installed = set()
    server = load = None
    success = False
    server_log = (run/'server-process.log').open('x')
    def stop_signal(signum, frame):
        raise KeyboardInterrupt(f'Signal {signum}; restoring boards')
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    def monitor(stage, names, timeout, reset_a=False):
        started = last_progress = time.monotonic()
        before = {n: boards[n].snapshot()['counts'].get('sample', 0) for n in names}
        reset_done = False
        while True:
            now = time.monotonic()
            states = {n: boards[n].snapshot() for n in names}
            if server.poll() is not None:
                raise RuntimeError('Server exited')
            if any(v['errors'] for v in states.values()):
                raise RuntimeError('Device error: '+json.dumps(states))
            if reset_a and not reset_done and now-started > 45:
                emit('reset_A_while_B_runs', B=boards['B'].snapshot())
                boards['A'].reset()
                boards['A'].start('s')
                reset_done = True
                emit('A_restarted', B=boards['B'].snapshot())
            if all(v['done'] for v in states.values()) and (not reset_a or reset_done):
                emit('stage_completed', stage=stage, elapsed=now-started,
                     samples={n: v['counts'].get('sample', 0)-before[n] for n,v in states.items()}, boards=states)
                return
            if now-started > timeout:
                raise TimeoutError('Stage timed out: '+stage)
            if now-last_progress >= 30:
                emit('progress', stage=stage, elapsed=round(now-started),
                     samples={n:v['counts'].get('sample', 0)-before[n] for n,v in states.items()},
                     errors={n:len(v['errors']) for n,v in states.items()})
                last_progress = now
            time.sleep(.5)
    try:
        env = dict(os.environ, PYTHONPATH=str(ROOT/'src'), TF_CPP_MIN_LOG_LEVEL='3', CUDA_VISIBLE_DEVICES='-1')
        server = subprocess.Popen([str(ROOT/'.venv/bin/python'), '-u', str(HERE/'audit_server.py'),
                                  '--output', str(run/'server')], cwd=ROOT, env=env, stdout=server_log, stderr=server_log)
        for _ in range(200):
            if server.poll() is not None:
                raise RuntimeError('Server failed startup')
            try:
                urllib.request.urlopen('http://127.0.0.1:8000/openapi.json', timeout=.3).close()
                break
            except OSError:
                time.sleep(.1)
        else:
            raise TimeoutError('Server not ready')
        emit('server_ready')
        # Both installations remain protected by finally, including partial writes.
        for name in BOARDS:
            installed.add(name)
            flash('install', name, run)
            emit('firmware_installed', board=name)
        for name in BOARDS:
            boards[name] = Board(name, run)
            boards[name].reset()
        for name in [a.first_board]+[n for n in BOARDS if n!=a.first_board]:
            boards[name].start('s')
            monitor('single_'+name, [name], 180)
        if a.single_only:
            emit('single_only_stop')
            return
        load_log = (run/'simulated-process.log').open('x')
        load = subprocess.Popen([str(ROOT/'.venv/bin/python'), '-u', 'tools/multiclient/load.py',
            '--clients', '1', '--duration', '150', '--rate', '10', '--output', str(run/'simulated')],
            cwd=ROOT, env=env, stdout=load_log, stderr=load_log)
        boards['A'].start('g')
        monitor('A_plus_simulated', ['A'], 600)
        if load.poll() is None:
            load.wait(timeout=180)
        if load.returncode != 0:
            raise RuntimeError('Simulated client failed')
        load_log.close()
        for b in boards.values():
            b.start('g')
        monitor('two_boards_1000', list(boards), 900)
        for b in boards.values():
            b.start('i')
        monitor('reboot_isolation', list(boards), 360, reset_a=True)
        for b in boards.values():
            b.start('h')
        monitor('two_boards_one_hour', list(boards), 3800)
        success = True
        emit('measurements_complete')
    except BaseException as error:
        emit('campaign_error', error=repr(error))
        raise
    finally:
        if load and load.poll() is None:
            load.terminate()
            load.wait(timeout=10)
        for b in boards.values():
            try:
                b.close()
            except Exception as error:
                emit('serial_close_failed', board=b.name, error=repr(error))
        # Independent restore attempts: failure on A must not skip B.
        failures = {}
        for name in sorted(installed):
            try:
                flash('restore', name, run)
                port, _ = BOARDS[name]
                link = serial.Serial()
                link.port=port;link.baudrate=115200;link.timeout=.2;link.dtr=False;link.rts=False
                link.open()
                try:
                    link.rts=True;time.sleep(.2);link.rts=False
                    until=time.monotonic()+8
                    with (run/name/'restored-boot.log').open('xb') as log:
                        while time.monotonic()<until:
                            log.write(link.read(4096))
                finally:
                    link.close()
                emit('original_restored', board=name)
            except BaseException as error:
                failures[name]=repr(error)
                emit('restore_failed', board=name, error=repr(error))
        if server and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill();server.wait()
        server_log.close()
        atomic_json(run/'completion.json', dict(measurements_complete=success, restore_failures=failures))
        events.close()
        if failures:
            raise RuntimeError('Restoration requires attention: '+json.dumps(failures))


if __name__ == '__main__':
    main()
