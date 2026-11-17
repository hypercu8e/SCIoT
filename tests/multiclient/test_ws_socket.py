"""Real RFC fragmentation and close behavior on a local TCP listener."""
import asyncio
import json
import socket
import threading
import unittest

import uvicorn
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from server.multiclient.http import create_app
from server.multiclient.websocket import pack
from test_http import body


class RealSocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();self.listener=listener
        self.url=f'ws://127.0.0.1:{listener.getsockname()[1]}/api/v2/ws'
        self.app=create_app(lambda:lambda data:data[32:],'hash')
        self.server=uvicorn.Server(uvicorn.Config(self.app,ws='websockets',ws_max_size=4656,
            ws_max_queue=1,ws_per_message_deflate=False,log_level='error'))
        self.thread=threading.Thread(target=self.server.run,kwargs={'sockets':[listener]},daemon=True);self.thread.start()
        async with asyncio.timeout(5):
            while not self.server.started:await asyncio.sleep(.01)

    async def asyncTearDown(self):
        self.server.should_exit=True
        await asyncio.to_thread(self.thread.join,5)
        self.assertFalse(self.thread.is_alive())
        self.listener.close()

    async def test_fragmented_request_and_size_limit(self):
        async with connect(self.url,compression=None) as ws:
            await ws.send(json.dumps(dict(version=1,client_id='socket',model_sha256='hash')))
            session=json.loads(await ws.recv())['session_id'];self.assertEqual(len(session),32)
            packet=pack(1,0,body(9));await ws.send([packet[:1],packet[1:33],packet[33:]])
            self.assertEqual((await ws.recv())[16:],bytes([9])*4608)
            await ws.send(packet+b'x')
            with self.assertRaises(ConnectionClosed) as raised:await ws.recv()
            self.assertEqual(raised.exception.rcvd.code,1009)

    async def test_disconnect_releases_connection(self):
        for _ in range(3):
            async with connect(self.url) as ws:
                await ws.send(json.dumps(dict(version=1,client_id='socket',model_sha256='hash')))
                self.assertIn('session_id',json.loads(await ws.recv()))
        async with asyncio.timeout(2):
            while self.app.state.ws_connections:await asyncio.sleep(.01)
