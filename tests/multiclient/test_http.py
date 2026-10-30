import asyncio
import json
import threading
import time
import unittest
import zlib

from server.multiclient.http import create_app
from server.multiclient.protocol import HEADER, REQUEST_MAGIC, parse


async def post(app, path, body, headers=()):
    messages = []
    received = False
    async def receive():
        nonlocal received
        if not received:
            received = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        await asyncio.Event().wait()
    async def send(message):
        messages.append(message)
    scope = {'type':'http', 'asgi':{'version':'3.0'}, 'http_version':'1.1',
             'method':'POST', 'scheme':'http', 'path':path, 'raw_path':path.encode(),
             'query_string':b'', 'headers':headers, 'server':('test',80), 'client':('test',1)}
    await app(scope, receive, send)
    return messages[0]['status'], dict(messages[0]['headers']), b''.join(m.get('body',b'') for m in messages[1:])


def body(value=0):
    activation = bytes([value])*4608
    return HEADER.pack(REQUEST_MAGIC,1,1,42,0,0,4608,zlib.crc32(activation))+activation


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_posts_correlate_and_reject_malformed(self):
        gate = threading.Event()
        def engine(data):
            if data[-1] == 1:
                gate.wait(2)
            return data[32:]
        app = create_app(lambda:engine,'hash')
        async with app.router.lifespan_context(app):
            sessions = {}
            for cid in ['a','b']:
                status,_,data = await post(app,'/api/v2/registration',json.dumps({'client_id':cid,'model_sha256':'hash'}).encode())
                self.assertEqual(status,200)
                sessions[cid]=json.loads(data)['session_id']
            def headers(cid,seq):
                return [(b'x-client-id',cid.encode()),(b'x-session-id',sessions[cid].encode()),
                        (b'x-request-id',str(seq).encode()),(b'x-model-sha256',b'hash')]
            a = asyncio.create_task(post(app,'/api/v2/infer',body(1),headers('a',0)))
            while app.state.service.running is None:
                await asyncio.sleep(.001)
            b = asyncio.create_task(post(app,'/api/v2/infer',body(2),headers('b',0)))
            while not app.state.service.queue:
                await asyncio.sleep(.001)
            gate.set()
            for cid,task,value in [('a',a,1),('b',b,2)]:
                status,reply,data=await task
                self.assertEqual(status,200)
                self.assertEqual(reply[b'x-client-id'],cid.encode())
                self.assertEqual(data,bytes([value])*4608)
            status,_,_=await post(app,'/api/v2/infer',body(1),headers('a',0))
            self.assertEqual(status,409)
            status,_,_=await post(app,'/api/v2/infer',b'x'*5000,headers('a',1))
            self.assertEqual(status,413)
            status,_,_=await post(app,'/api/v2/infer',body(3),headers('a',2))
            self.assertEqual(status,200)

    def test_crc_rejects_corruption(self):
        invalid=bytearray(body());invalid[-1]=1
        with self.assertRaises(ValueError):parse(invalid)
