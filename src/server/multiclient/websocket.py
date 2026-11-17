"""Bounded WebSocket transport over the shared v2 admission service."""
import asyncio
import json
import struct
import time

from fastapi import WebSocket, WebSocketDisconnect

from .protocol import BODY_BYTES, parse
from .service import ServiceError

ENVELOPE = struct.Struct('<4sBBHQ')
MAX_MESSAGE = ENVELOPE.size + BODY_BYTES


def pack(kind, sequence, body):
    return ENVELOPE.pack(b'SCW1', 1, kind, 0, sequence) + body


def unpack(data):
    if not isinstance(data, bytes) or len(data) != MAX_MESSAGE:
        raise ValueError('Invalid request size')
    magic, version, kind, reserved, sequence = ENVELOPE.unpack_from(data)
    if (magic, version, kind, reserved) != (b'SCW1', 1, 1, 0):
        raise ValueError('Invalid envelope')
    return sequence, data[ENVELOPE.size:]


def install(app, service):
    connections = set()
    app.state.ws_connections = connections

    @app.websocket('/api/v2/ws')
    async def websocket(ws: WebSocket):
        if len(connections) >= service.max_clients or service.closed:
            await ws.close(code=1013)
            return
        connections.add(ws)
        cid = session = model = None
        job = task = receive = None

        async def error(status, reason, sequence=None):
            await asyncio.wait_for(ws.send_json(dict(status=status, error=reason,
                session_id=session, request_id=None if sequence is None else str(sequence))), 3)

        try:
            await ws.accept()
            try:
                async with asyncio.timeout(3):
                    event = await ws.receive()
                text = event.get('text')
                if text is None or len(text.encode()) > 512:
                    raise ValueError('Invalid registration')
                data = json.loads(text)
                if type(data.get('version')) is not int or data['version'] != 1:
                    raise ValueError('Invalid version')
                cid, model = data['client_id'], data['model_sha256']
                session = service.register(cid, model)
            except ServiceError as exc:
                await error(exc.status, exc.reason)
                await ws.close(code=1008)
                return
            except (ValueError, TypeError, KeyError, AttributeError, TimeoutError):
                await error(400, 'invalid_registration')
                await ws.close(code=1008)
                return
            await asyncio.wait_for(ws.send_json(dict(version=1, client_id=cid,
                session_id=session, model_sha256=model, split='block_2_add',
                dtype='int8', activation_bytes=4608,
                request_deadline_ms=int(service.timeout*1000))), 3)
            receive = asyncio.create_task(ws.receive())
            overlaps = 0
            while True:
                watched = {receive} | ({task} if task else set())
                done, _ = await asyncio.wait(watched, timeout=service.idle,
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    await ws.close(code=1000)
                    return
                # Receive first: disconnect wins over a simultaneously completed inference.
                if receive in done:
                    event = receive.result()
                    receive = None
                    if event['type'] == 'websocket.disconnect':
                        return
                    sequence = None
                    try:
                        sequence, body = unpack(event.get('bytes'))
                        if task:
                            overlaps += 1
                            await error(409, 'busy_or_duplicate', sequence)
                            if overlaps >= 2:
                                await ws.close(code=1008)
                                return
                        else:
                            job = service.reserve(cid, session, sequence, model, time.monotonic())
                            try:
                                parse(body)
                            except ValueError:
                                service.cancel(job, 400, 'invalid_message')
                                job = None
                                raise
                            task = asyncio.create_task(service.infer(job, body))
                    except ServiceError as exc:
                        await error(exc.status, exc.reason, sequence)
                        if exc.status in (410, 422, 503):
                            await ws.close(code=1008)
                            return
                    except ValueError:
                        await error(400, 'invalid_message', sequence)
                        await ws.close(code=1008)
                        return
                    receive = asyncio.create_task(ws.receive())
                if task and task in done:
                    try:
                        output = task.result()
                        # Recheck session after awaiting worker completion.
                        client = service.clients.get(cid)
                        if client is None or client.session != session:
                            raise ServiceError(410, 'session_replaced')
                        await asyncio.wait_for(ws.send_bytes(pack(2, job.request_id, output)), 3)
                    except ServiceError as exc:
                        await error(exc.status, exc.reason, job.request_id)
                    finally:
                        task = job = None
                        overlaps = 0
        except (WebSocketDisconnect, OSError, TimeoutError):
            pass
        finally:
            for pending in (receive, task):
                if pending and not pending.done():
                    pending.cancel()
            await asyncio.gather(*(p for p in (receive, task) if p), return_exceptions=True)
            if job:
                service.cancel(job, 499, 'client_disconnected')
            connections.discard(ws)
