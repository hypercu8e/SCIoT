import asyncio
import json
import threading
import unittest

from server.multiclient.http import create_app
from server.multiclient.websocket import ENVELOPE, pack, unpack
from test_http import body


class Socket:
    def __init__(self, app):
        self.app = app
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()

    async def __aenter__(self):
        scope = dict(type='websocket', asgi={'version':'3.0'}, scheme='ws',
            path='/api/v2/ws', raw_path=b'/api/v2/ws', query_string=b'',
            headers=[], server=('test',80), client=('test',1), subprotocols=[])
        await self.incoming.put({'type':'websocket.connect'})
        self.task = asyncio.create_task(self.app(scope, self.incoming.get, self.outgoing.put))
        self.assert_event = await self.get()
        return self

    async def get(self):
        return await asyncio.wait_for(self.outgoing.get(), 2)

    async def send(self, data):
        await self.incoming.put({'type':'websocket.receive',
            **({'text':data} if isinstance(data,str) else {'bytes':data})})

    async def register(self, cid='a', model='hash'):
        await self.send(json.dumps(dict(version=1, client_id=cid, model_sha256=model)))
        return json.loads((await self.get())['text'])

    async def __aexit__(self, *args):
        await self.incoming.put({'type':'websocket.disconnect', 'code':1000})
        await asyncio.wait_for(self.task, 3)


class WSTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_and_consumed_sequence(self):
        app = create_app(lambda:lambda data:data[32:], 'hash')
        async with app.router.lifespan_context(app):
            async with Socket(app) as ws:
                registration = await ws.register()
                await ws.send(pack(1, 2**64-1, body(7)))
                reply = (await ws.get())['bytes']
                self.assertEqual(ENVELOPE.unpack_from(reply), (b'SCW1',1,2,0,2**64-1))
                self.assertEqual(reply[16:], bytes([7])*4608)
                await ws.send(pack(1,2**64-1,body()))
                error=json.loads((await ws.get())['text'])
                self.assertEqual(error['status'],409)
                self.assertEqual(error['session_id'],registration['session_id'])
            self.assertFalse(app.state.ws_connections)
            self.assertEqual(app.state.service.receiving,0)

    async def test_bad_crc_and_registration(self):
        app=create_app(lambda:lambda data:data,'hash')
        async with app.router.lifespan_context(app):
            async with Socket(app) as ws:
                self.assertEqual((await ws.register(model='wrong'))['status'],422)
                self.assertEqual((await ws.get())['type'],'websocket.close')
            async with Socket(app) as ws:
                await ws.register()
                invalid=bytearray(body());invalid[-1]^=1
                await ws.send(pack(1,0,invalid))
                self.assertEqual(json.loads((await ws.get())['text'])['status'],400)
                self.assertEqual((await ws.get())['type'],'websocket.close')
            self.assertEqual(app.state.service.receiving,0)

    async def test_disconnect_keeps_running_slot_across_registration(self):
        gate=threading.Event()
        def engine(data):
            gate.wait(2)
            return data
        app=create_app(lambda:engine,'hash',accepted_models={'hash','nopad'})
        async with app.router.lifespan_context(app):
            try:
                async with Socket(app) as ws:
                    await ws.register(model='nopad')
                    await ws.send(pack(1,0,body()))
                    async with asyncio.timeout(2):
                        while not app.state.service.running: await asyncio.sleep(.001)
                async with Socket(app) as ws:
                    await ws.register(model='hash')
                    await ws.send(pack(1,0,body()))
                    self.assertEqual(json.loads((await ws.get())['text'])['status'],409)
                    gate.set()
                    async with asyncio.timeout(2):
                        while app.state.service.running: await asyncio.sleep(.001)
                    await ws.send(pack(1,1,body()))
                    self.assertEqual((await ws.get())['bytes'][16:],body())
            finally:gate.set()

    def test_envelope_rejects_version_kind_and_size(self):
        for data in (b'',pack(2,0,body()),pack(1,0,body())+b'x'):
            with self.assertRaises(ValueError):unpack(data)
