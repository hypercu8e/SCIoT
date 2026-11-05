"""Application-level paced upload proxy; not a Wi-Fi or packet-loss emulator."""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
import time

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8787);p.add_argument('--upstream-port',type=int,default=8786);p.add_argument('--kbps',type=int,required=True);a=p.parse_args()
    if a.kbps<=0:p.error('positive rate required')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def forward(self):
            self.connection.settimeout(60);up=http.client.HTTPConnection('127.0.0.1',a.upstream_port,timeout=60)
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<=n<=8272:self.send_error(400);return
                up.putrequest(self.command,self.path)
                for k,v in self.headers.items():
                    if k.lower() not in ('host','connection','transfer-encoding'):up.putheader(k,v)
                up.putheader('Connection','close');up.endheaders()
                start=time.perf_counter();sent=0
                while sent<n:
                    data=self.rfile.read(min(256,n-sent))
                    if not data:raise ConnectionError('truncated upload')
                    sent+=len(data);time.sleep(max(0,start+sent*8/(a.kbps*1000)-time.perf_counter()));up.send(data)
                elapsed=time.perf_counter()-start
                response=up.getresponse();data=response.read(8193)
                if len(data)>8192:raise ValueError('response limit')
                self.send_response(response.status)
                for k,v in response.getheaders():
                    if k.lower() not in ('connection','content-length','transfer-encoding','date','server'):self.send_header(k,v)
                self.send_header('Content-Length',str(len(data)));self.send_header('Connection','close');self.end_headers();self.wfile.write(data)
                if n:print(json.dumps(dict(event='paced',bytes=n,kbps=a.kbps,elapsed_s=elapsed,effective_kbps=n*8/elapsed/1000)),flush=True)
            except (OSError,ValueError) as e:self.send_error(502,str(e))
            finally:up.close()
        do_GET=forward;do_POST=forward
    print(json.dumps(dict(event='ready',port=a.port,kbps=a.kbps)),flush=True)
    HTTPServer(('0.0.0.0',a.port),Handler).serve_forever()
if __name__=='__main__':main()
