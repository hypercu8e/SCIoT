"""Real TCP server/proxy integration with frozen suffix and session recovery."""
import http.client
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import numpy as np
from native import Native
from host_encoder import packet
from protocol import REPLY,NAMES
HERE=Path(__file__).resolve().parent

def freeport():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def await_server(port,process):
    for _ in range(200):
        if process.poll() is not None:raise RuntimeError('Server exited')
        try:
            c=http.client.HTTPConnection('127.0.0.1',port,timeout=.2);c.request('GET','/infer');r=c.getresponse();r.read();c.close()
            if r.status==200:return
        except OSError:pass
        time.sleep(.05)
    raise TimeoutError('Server not ready')

class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (HERE/'artifacts/manifest.json').exists():raise unittest.SkipTest('Prepare frozen artifacts first')
        cls.temp=tempfile.TemporaryDirectory();cls.port=freeport();cls.logs=open(Path(cls.temp.name)/'server.log','w+')
        cls.proc=subprocess.Popen([sys.executable,str(HERE/getattr(cls,'server_script','server.py')),'--port',str(cls.port),'--output',str(Path(cls.temp.name)/'server')],stdout=cls.logs,stderr=cls.logs)
        await_server(cls.port,cls.proc)
        cls.manifest=json.loads((HERE/'artifacts/manifest.json').read_text());cls.native=Native()
    @classmethod
    def tearDownClass(cls):cls.proc.terminate();cls.proc.wait(timeout=10);cls.logs.close();cls.temp.cleanup()
    def post(self,body,port=None):
        c=http.client.HTTPConnection('127.0.0.1',port or self.port,timeout=10)
        c.request('POST','/infer',body,{'X-Model-SHA256':self.manifest['models']['int8']['prefix']['sha256'],'Content-Type':'application/octet-stream'})
        r=c.getresponse();data=r.read();status=r.status;c.close();return status,data
    def test_lossless_suffix_and_reconnect(self):
        x=np.full(4608,-20,np.int8);expected=None
        for config in range(4):
            for seq in range(3):
                body=packet(x,config,seq,x if seq else None,session=100+config,native=self.native)
                status,data=self.post(body);self.assertEqual(status,200)
                self.assertEqual(REPLY.unpack_from(data)[4:7],(config,seq,seq))
                if expected is None:expected=data[48:]
                self.assertEqual(data[48:],expected)
        # New connection alone cannot resume missing state. A new full session can.
        self.assertEqual(self.post(packet(x,3,1,x,session=999,native=self.native))[0],400)
        self.assertEqual(self.post(packet(x,3,session=1000,native=self.native))[0],200)
        bad=bytearray(packet(x,0,session=1001,native=self.native));bad[-1]^=1
        self.assertEqual(self.post(bad)[0],400)
        self.assertEqual(self.post(packet(x,0,session=1002,native=self.native))[0],200)
    def test_paced_proxy(self):
        x=np.full(4608,-20,np.int8)
        for rate in (128,512):
            port=freeport();log=open(Path(self.temp.name)/f'proxy-{rate}.log','w+')
            proc=subprocess.Popen([sys.executable,str(HERE/'proxy.py'),'--port',str(port),'--upstream-port',str(self.port),'--kbps',str(rate)],stdout=log,stderr=log)
            try:
                await_server(port,proc);body=packet(x,0,session=2000+rate,native=self.native)
                start=time.perf_counter();status,_=self.post(body,port);elapsed=time.perf_counter()-start
                self.assertEqual(status,200);self.assertGreaterEqual(elapsed,len(body)*8/(rate*1000)*.95)
                time.sleep(.05);log.seek(0);rows=[json.loads(s) for s in log if s.startswith('{')]
                row=next(r for r in rows if r['event']=='paced')
                self.assertLessEqual(row['effective_kbps'],rate*1.05);self.assertGreater(row['effective_kbps'],rate*.8)
            finally:proc.terminate();proc.wait(timeout=5);log.close()

class NativeIntegrationTests(IntegrationTests):
    server_script='server_native.py'

if __name__=='__main__':unittest.main()
