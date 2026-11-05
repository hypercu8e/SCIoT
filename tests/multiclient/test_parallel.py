import asyncio
import io
import json
import threading
import unittest

from server.multiclient.service import Service, ServiceError
from test_service import until


class ParallelTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_owners_fifo_limit_and_shutdown(self):
        gate = threading.Event()
        owners, calls = [], []
        def factory():
            owner = threading.get_ident()
            owners.append(owner)
            def engine(body):
                self.assertEqual(owner, threading.get_ident())
                calls.append(body)
                if body.startswith(b'hold'):
                    gate.wait(3)
                return body
            return engine
        metrics = io.StringIO()
        service = Service(factory, 'hash', inference_workers=2, metrics=metrics)
        await service.start()
        def job(cid):
            return service.reserve(cid, service.register(cid, 'hash'), 0, 'hash')
        tasks = []
        try:
            for cid in ('hold1', 'hold2'):
                tasks.append(asyncio.create_task(service.infer(job(cid), cid.encode())))
            await until(lambda: len(service.active) == 2 and len(calls) == 2)
            self.assertEqual(len(set(owners)), 2)
            for cid in ('third', 'fourth'):
                tasks.append(asyncio.create_task(service.infer(job(cid), cid.encode())))
                await until(lambda: len(service.queue) == len(tasks)-2)
            self.assertEqual(len(service.active), 2)
            gate.set()
            self.assertEqual(await asyncio.gather(*tasks), [b'hold1', b'hold2', b'third', b'fourth'])
            # Assignment order is FIFO; native thread scheduling need not be.
            assigned = [json.loads(line)['client_id'] for line in metrics.getvalue().splitlines()
                        if json.loads(line)['event'] == 'worker_started']
            self.assertEqual(assigned, ['hold1', 'hold2', 'third', 'fourth'])
        finally:
            gate.set()
            await service.close()

    async def test_late_requests_keep_slots_and_close_waits(self):
        gate = threading.Event()
        def factory():
            def engine(body):
                gate.wait(3)
                return body
            return engine
        service = Service(factory, 'hash', inference_workers=2, timeout=.05)
        await service.start()
        tasks = []
        for cid in ('a', 'b'):
            session = service.register(cid, 'hash')
            tasks.append(asyncio.create_task(service.infer(service.reserve(cid, session, 0, 'hash'), b'x')))
        await until(lambda: len(service.active) == 2)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self.assertTrue(all(isinstance(r, ServiceError) and r.status == 504 for r in results))
        self.assertEqual(len(service.active), 2)
        closer = asyncio.create_task(service.close())
        await asyncio.sleep(.01)
        self.assertFalse(closer.done())
        gate.set()
        await closer
        self.assertFalse(service.active)
        self.assertTrue(all(c.pending is None for c in service.clients.values()))

    async def test_start_failure_and_limits(self):
        for count in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                Service(lambda: None, 'hash', inference_workers=count)
        calls = 0
        def factory():
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('failed initialization')
            return lambda body: body
        service = Service(factory, 'hash', inference_workers=3)
        with self.assertRaises(RuntimeError):
            await service.start()
        self.assertTrue(all(executor._shutdown for executor in service.executors))

    async def test_replacement_and_failure_do_not_block_other_worker(self):
        gate = threading.Event()
        def factory():
            def engine(body):
                if body == b'hold':
                    gate.wait(3)
                if body == b'error':
                    raise RuntimeError('inference error')
                return body
            return engine
        service = Service(factory, 'hash', inference_workers=2)
        await service.start()
        def job(cid):
            return service.reserve(cid, service.register(cid, 'hash'), 0, 'hash')
        try:
            old = job('a')
            task = asyncio.create_task(service.infer(old, b'hold'))
            await until(lambda: bool(service.active))
            session = service.register('a', 'hash')
            with self.assertRaises(ServiceError) as error:
                await task
            self.assertEqual(error.exception.status, 410)
            with self.assertRaises(ServiceError):
                service.reserve('a', session, 0, 'hash')
            with self.assertRaises(ServiceError) as error:
                await service.infer(job('b'), b'error')
            self.assertEqual(error.exception.status, 500)
            self.assertEqual(await service.infer(job('c'), b'free'), b'free')
            self.assertIs(service.clients['a'].pending, old)
            gate.set()
            await until(lambda: not service.active)
            fresh = service.reserve('a', session, 0, 'hash')
            self.assertEqual(await service.infer(fresh, b'new'), b'new')
        finally:
            gate.set()
            await service.close()
