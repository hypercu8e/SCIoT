import asyncio
import threading
import time
import unittest

from server.multiclient.service import Service, ServiceError


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.001)


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.gate = threading.Event()
        self.calls = []
        def engine(body):
            self.calls.append(body)
            if body == b'hold':
                self.gate.wait(2)
            if body == b'error':
                raise RuntimeError('test')
            return body
        self.service = Service(lambda: engine, 'hash', queue_size=1, timeout=.5)
        await self.service.start()

    async def asyncTearDown(self):
        self.gate.set()
        await self.service.close()

    def job(self, cid, sequence=0):
        session = self.service.register(cid, 'hash')
        return self.service.reserve(cid, session, sequence, 'hash')

    async def test_fifo_capacity_and_independent_identity(self):
        a = asyncio.create_task(self.service.infer(self.job('a'), b'hold'))
        await until(lambda: self.service.running is not None)
        b = asyncio.create_task(self.service.infer(self.job('b'), b'B'))
        await until(lambda: len(self.service.queue) == 1)
        with self.assertRaises(ServiceError) as error:
            self.job('c')
        self.assertEqual(error.exception.status, 429)
        self.gate.set()
        self.assertEqual(await a, b'hold')
        self.assertEqual(await b, b'B')
        self.assertEqual(self.calls, [b'hold', b'B'])

    async def test_replacement_during_running_keeps_physical_slot(self):
        old = self.job('a')
        task = asyncio.create_task(self.service.infer(old, b'hold'))
        await until(lambda: self.service.running is old)
        session = self.service.register('a', 'hash')
        with self.assertRaises(ServiceError) as error:
            await task
        self.assertEqual(error.exception.status, 410)
        with self.assertRaises(ServiceError) as error:
            self.service.reserve('a', session, 0, 'hash')
        self.assertEqual(error.exception.status, 409)
        self.gate.set()
        await until(lambda: self.service.running is None)
        new = self.service.reserve('a', session, 0, 'hash')
        self.assertEqual(await self.service.infer(new, b'new'), b'new')
        self.assertEqual(self.service.clients['a'].session, session)

    async def test_queued_expiration_does_not_invoke(self):
        self.service.timeout = .04
        a = asyncio.create_task(self.service.infer(self.job('a'), b'hold'))
        await until(lambda: self.service.running is not None)
        b = asyncio.create_task(self.service.infer(self.job('b'), b'B'))
        results = await asyncio.gather(a, b, return_exceptions=True)
        self.assertTrue(all(isinstance(r, ServiceError) and r.status == 504 for r in results))
        self.assertEqual(len(self.service.queue), 0)
        self.assertEqual(self.calls, [b'hold'])
        self.assertIsNotNone(self.service.clients['a'].pending)

    async def test_failure_releases_slot_and_worker_survives(self):
        job = self.job('a')
        with self.assertRaises(ServiceError) as error:
            await self.service.infer(job, b'error')
        self.assertEqual(error.exception.status, 500)
        self.assertEqual(await self.service.infer(self.job('b'), b'ok'), b'ok')

    async def test_duplicate_and_receiving_limits(self):
        self.service.max_receiving = 1
        a = self.job('a')
        with self.assertRaises(ServiceError) as error:
            self.job('b')
        self.assertEqual(error.exception.status, 429)
        self.service.cancel(a, 400, 'invalid')
        with self.assertRaises(ServiceError) as error:
            self.service.reserve('a', a.session_id, 0, 'hash')
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.service.receiving, 0)

    async def test_idle_cleanup_and_client_limit(self):
        self.service.max_clients = 1
        self.service.register('a', 'hash')
        with self.assertRaises(ServiceError):
            self.service.register('b', 'hash')
        self.service.idle = .001
        await asyncio.sleep(.005)
        self.service.purge()
        self.service.register('b', 'hash')
        self.assertEqual(set(self.service.clients), {'b'})

    async def test_cancellation_removes_queued_request(self):
        a = asyncio.create_task(self.service.infer(self.job('a'), b'hold'))
        await until(lambda: self.service.running is not None)
        b = asyncio.create_task(self.service.infer(self.job('b'), b'B'))
        await until(lambda: len(self.service.queue) == 1)
        b.cancel()
        await asyncio.gather(b, return_exceptions=True)
        self.assertEqual(len(self.service.queue), 0)
        self.gate.set()
        await a


if __name__ == '__main__':
    unittest.main()
