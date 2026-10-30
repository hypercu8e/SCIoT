"""HTTP v2 adapter. The event loop never executes TensorFlow inference."""
import asyncio
from contextlib import asynccontextmanager
import json
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from .protocol import BODY_BYTES, parse
from .service import Service, ServiceError


async def read_body(request, limit, deadline):
    data = bytearray()
    async with asyncio.timeout_at(deadline):
        async for chunk in request.stream():
            if len(data) + len(chunk) > limit:
                raise ServiceError(413, 'body_too_large')
            data.extend(chunk)
    return bytes(data)


def create_app(factory, model_hash, **limits):
    service = Service(factory, model_hash, **limits)

    @asynccontextmanager
    async def lifespan(app):
        await service.start()
        try:
            yield
        finally:
            await service.close()

    app = FastAPI(lifespan=lifespan)
    app.state.service = service

    @app.post('/api/v2/registration')
    async def registration(request: Request):
        reserved = False
        try:
            if service.receiving >= service.max_receiving:
                raise ServiceError(429, 'receiving_capacity')
            service.receiving += 1
            reserved = True
            body = await read_body(request, 512, time.monotonic()+3)
            data = json.loads(body)
            session = service.register(data['client_id'], data['model_sha256'])
            return {'client_id': data['client_id'], 'session_id': session,
                    'model_sha256': model_hash, 'split': 'block_2_add',
                    'dtype': 'int8', 'activation_bytes': 4608,
                    'request_deadline_ms': int(service.timeout*1000)}
        except ServiceError as error:
            service.emit('registration_rejected', status=error.status, reason=error.reason)
            return JSONResponse({'error': error.reason}, status_code=error.status)
        except TimeoutError:
            return JSONResponse({'error': 'body_timeout'}, status_code=408)
        except (ValueError, KeyError, TypeError):
            return JSONResponse({'error': 'invalid_registration'}, status_code=400)
        finally:
            if reserved:
                service.receiving -= 1

    @app.post('/api/v2/infer')
    async def infer(request: Request):
        entered, job = time.monotonic(), None
        headers = {name: request.headers.get(name, '') for name in
                   ('x-client-id', 'x-session-id', 'x-request-id')}
        # Echo only bounded identifiers, including error replies.
        headers = {k: v for k, v in headers.items() if len(v) <= 64}
        try:
            sequence = request.headers.get('x-request-id', '')
            if len(sequence) > 20 or not sequence.isascii() or not sequence.isdecimal():
                raise ServiceError(400, 'invalid_request_id')
            job = service.reserve(request.headers.get('x-client-id'),
                request.headers.get('x-session-id'), int(sequence),
                request.headers.get('x-model-sha256'), entered)
            body = await read_body(request, BODY_BYTES, min(job.deadline, entered+3))
            parse(body)
            task = asyncio.create_task(service.infer(job, body))
            try:
                while not task.done():
                    await asyncio.wait({task}, timeout=.1)
                    if not task.done() and await request.is_disconnected():
                        task.cancel()
                output = await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            return Response(output, media_type='application/octet-stream', headers=headers)
        except ServiceError as error:
            status, reason = error.status, error.reason
        except TimeoutError:
            status, reason = 408, 'body_timeout'
        except (ValueError, KeyError):
            status, reason = 400, 'invalid_message'
        except asyncio.CancelledError:
            if job:
                service.cancel(job, 499, 'client_disconnected')
            raise
        except Exception:
            status, reason = 400, 'request_disconnected_or_invalid'
        if job:
            service.cancel(job, status, reason)
        else:
            service.emit('rejected', status=status, reason=reason,
                         **{k.replace('x-', '').replace('-', '_'): v for k, v in headers.items()})
        return JSONResponse({'error': reason}, status_code=status, headers=headers)

    return app
