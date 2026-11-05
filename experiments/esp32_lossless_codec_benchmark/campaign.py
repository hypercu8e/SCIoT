"""Run an isolated server, optional pacing proxy, hardware runner and final audit."""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
TOOLS=HERE/'results/build-tools/bin/python'

def wait_ready(port,processes):
    for _ in range(200):
        if any(p.poll() is not None for p in processes):raise RuntimeError('Server/proxy exited before ready')
        try:
            c=http.client.HTTPConnection('127.0.0.1',port,timeout=.3);c.request('GET','/infer');r=c.getresponse();r.read();c.close()
            if r.status==200:return
        except OSError:pass
        time.sleep(.1)
    raise TimeoutError('Server/proxy not ready')

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--port',default='/dev/ttyACM0');p.add_argument('--seed-backup',type=Path);p.add_argument('--rate',type=int,choices=(0,128,512),default=0);p.add_argument('--backend',choices=('python','native'),default='native');p.add_argument('--lossless-video-only',action='store_true');p.add_argument('--publish',type=Path);a=p.parse_args()
    run=a.run.resolve()
    if run.exists():raise ValueError('New run directory required')
    run.mkdir(parents=True)
    text=(HERE/'include/network.local.h').read_text()
    board_url=re.search(r'\bSERVER_URL\s*(?:=\s*)?"([^"]+)"',text)[1]
    from urllib.parse import urlparse
    board_port=urlparse(board_url).port or 80
    backend_port=board_port+2 if a.rate else board_port
    server_name='server_native.py' if a.backend=='native' else 'server.py'
    proof={str(q.relative_to(HERE)):hashlib.sha256(q.read_bytes()).hexdigest() for q in [HERE/server_name,HERE/'server.py',HERE/'protocol.py']+([HERE/'native_decoder.py',HERE/'include/rice_decoder.h'] if a.backend=='native' else [])}
    processes=[];logs=[];proxy_temp=None
    try:
        log=(run/'server.log').open('x');logs.append(log)
        server=subprocess.Popen([sys.executable,'-u',str(HERE/server_name),'--port',str(backend_port),'--output',str(run/'server')],stdout=log,stderr=log,cwd=ROOT);processes.append(server)
        wait_ready(backend_port,processes)
        if a.rate:
            proxy_temp=tempfile.NamedTemporaryFile(prefix='sciot-proxy-',suffix='.jsonl',mode='w',delete=False);logs.append(proxy_temp)
            processes.append(subprocess.Popen([sys.executable,'-u',str(HERE/'proxy.py'),'--port',str(board_port),'--upstream-port',str(backend_port),'--kbps',str(a.rate)],stdout=proxy_temp,stderr=proxy_temp,cwd=ROOT))
            wait_ready(board_port,processes)
        args=[str(TOOLS),'-u',str(HERE/'run_hardware.py'),'--port',a.port,'--run',str(run)]
        if a.rate:args.append('--bandwidth-only')
        elif a.lossless_video_only:args.append('--lossless-video-only')
        if a.seed_backup:args+=['--seed-backup',str(a.seed_backup.resolve())]
        subprocess.run(args,check=True,cwd=ROOT)
    finally:
        for process in reversed(processes):
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        for log in logs:log.close()
        if proxy_temp is not None:shutil.move(proxy_temp.name,run/'proxy.jsonl')
        (run/'backend-proof.json').write_text(json.dumps(dict(backend=a.backend,rate_kbps=a.rate,compiler=subprocess.check_output(['c++','--version'],text=True).splitlines()[0],source_sha256=proof),indent=2)+'\n')
    if a.publish:
        subprocess.run([sys.executable,str(HERE/'publish_report.py'),'--run',str(run),'--output',str(a.publish.resolve())],check=True,cwd=ROOT)
        plot_destination=a.publish.resolve()
    else:
        subprocess.run([sys.executable,str(HERE/'analyze.py'),'--run',str(run)],check=True,cwd=ROOT)
        plot_destination=run
    subprocess.run([str(TOOLS),str(HERE/'plot_report.py'),'--run',str(plot_destination)],check=True,cwd=ROOT)
if __name__=='__main__':main()
