"""All registry mutations run on one asyncio loop; each engine belongs to one dedicated thread."""
import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import time
import uuid


class ServiceError(Exception):
    def __init__(self, status, reason):
        super().__init__(reason)
        self.status, self.reason = status, reason


@dataclass
class Client:
    session: str
    touched: float
    sequence: int = -1
    pending: object = None


@dataclass
class Job:
    client_id: str
    session_id: str
    request_id: int
    entered: float
    deadline: float
    future: object
    state: str = 'receiving'
    queued: float = 0
    started: float = 0
    body: bytes = b''


class Service:
    def __init__(self, factory, model_hash, *, max_clients=32, queue_size=8,
                 max_receiving=8, timeout=10., idle=60., metrics=None, inference_workers=1):
        if min(max_clients, queue_size, max_receiving, timeout, idle) <= 0:
            raise ValueError('Limits must be positive')
        if not isinstance(inference_workers, int) or isinstance(inference_workers, bool) or inference_workers < 1:
            raise ValueError('inference_workers must be a positive integer')
        self.factory, self.model_hash = factory, model_hash
        self.max_clients, self.queue_size = max_clients, queue_size
        self.max_receiving, self.timeout, self.idle = max_receiving, timeout, idle
        self.clients, self.queue = {}, deque()
        self.receiving = 0
        self.active = {}
        self.wake = asyncio.Event()
        self.executors = [ThreadPoolExecutor(max_workers=1, thread_name_prefix=f'sciot-inference-{i}')
                          for i in range(inference_workers)]
        self.metrics = metrics
        self.closed = False

    def emit(self, event, job=None, **data):
        row = {'event': event, 'monotonic': time.monotonic(), **data}
        if job:
            row.update(client_id=job.client_id, session_id=job.session_id,
                       request_id=job.request_id)
        if self.metrics:
            self.metrics.write(json.dumps(row) + '\n')
            self.metrics.flush()

    @property
    def running(self):
        """Compatibility view: first active job, or None."""
        return next(iter(self.active.values()), None)

    async def start(self):
        self.engines = []
        try:
            for executor in self.executors:
                self.engines.append(await asyncio.get_running_loop().run_in_executor(executor, self.factory))
        except BaseException:
            for executor in self.executors:
                executor.shutdown(wait=True)
            self.engines.clear()
            raise
        self.workers = [asyncio.create_task(self.work(i)) for i in range(len(self.engines))]
        self.cleaner = asyncio.create_task(self.cleanup())

    async def close(self):
        self.closed = True
        for client in list(self.clients.values()):
            if client.pending:
                self.cancel(client.pending, 503, 'server_shutdown')
        self.wake.set()
        self.cleaner.cancel()
        await asyncio.gather(self.cleaner, return_exceptions=True)
        await asyncio.gather(*self.workers)
        for executor in self.executors:
            executor.shutdown(wait=True)
        self.engines.clear()

    def purge(self):
        now = time.monotonic()
        for cid, client in list(self.clients.items()):
            if client.pending is None and now - client.touched >= self.idle:
                del self.clients[cid]
        for job in list(self.queue):
            if now >= job.deadline:
                self.cancel(job, 504, 'deadline_exceeded')

    async def cleanup(self):
        previous_time, previous_cpu = time.monotonic(), time.process_time()
        while True:
            await asyncio.sleep(min(1., self.idle))
            self.purge()
            try:
                rss = int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
            except (OSError, ValueError, IndexError):
                rss = None
            now, cpu = time.monotonic(), time.process_time()
            cpu_cores = (cpu-previous_cpu)/(now-previous_time)
            previous_time, previous_cpu = now, cpu
            self.emit('resources', cpu_cores=cpu_cores, active_workers=len(self.active), rss_bytes=rss, clients=len(self.clients),
                      queue_depth=len(self.queue), receiving=self.receiving,
                      running=self.running is not None)

    def register(self, cid, model_hash):
        self.purge()
        if not isinstance(cid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', cid):
            raise ServiceError(400, 'invalid_client_id')
        if model_hash != self.model_hash:
            raise ServiceError(422, 'model_mismatch')
        if cid not in self.clients and len(self.clients) >= self.max_clients:
            raise ServiceError(429, 'client_capacity')
        old = self.clients.get(cid)
        pending = old.pending if old else None
        if pending:
            self.cancel(pending, 410, 'session_replaced')
        session = uuid.uuid4().hex
        self.clients[cid] = Client(session, time.monotonic(),
                                   pending=pending if pending and pending.state == 'running' else None)
        self.emit('registration', client_id=cid, session_id=session)
        return session

    def reserve(self, cid, session, sequence, model_hash, entered=None):
        self.purge()
        if self.closed:
            raise ServiceError(503, 'server_shutdown')
        client = self.clients.get(cid)
        if client is None or client.session != session:
            raise ServiceError(410, 'invalid_session')
        if model_hash != self.model_hash:
            raise ServiceError(422, 'model_mismatch')
        if not isinstance(sequence, int) or not 0 <= sequence < 2**64:
            raise ServiceError(400, 'invalid_request_id')
        if client.pending or sequence <= client.sequence:
            raise ServiceError(409, 'busy_or_duplicate')
        if self.receiving >= self.max_receiving or len(self.queue) >= self.queue_size:
            raise ServiceError(429, 'capacity')
        now = time.monotonic() if entered is None else entered
        job = Job(cid, session, sequence, now, now + self.timeout,
                  asyncio.get_running_loop().create_future())
        client.sequence, client.pending, client.touched = sequence, job, time.monotonic()
        self.receiving += 1
        self.emit('reserved', job)
        return job

    def release(self, job):
        client = self.clients.get(job.client_id)
        # Object identity protects a newer session/job from old completions.
        if client and client.pending is job:
            client.pending = None
            client.touched = time.monotonic()

    def cancel(self, job, status, reason):
        if not job.future.done():
            job.future.set_result(ServiceError(status, reason))
            self.emit('terminal', job, status=status, reason=reason,
                      elapsed_us=int((time.monotonic()-job.entered)*1e6))
        if job.state == 'receiving':
            self.receiving -= 1
        if job.state == 'queued':
            self.queue.remove(job)
        if job.state != 'running':
            job.state = 'finished'
            self.release(job)

    async def infer(self, job, body):
        if job.state != 'receiving' or job.future.done():
            result = job.future.result()
            raise result
        self.receiving -= 1
        job.state = 'queued'
        if len(self.queue) >= self.queue_size:
            job.state = 'finished'
            self.release(job)
            self.cancel(job, 429, 'queue_full')
        else:
            job.body, job.queued = body, time.monotonic()
            self.queue.append(job)
            self.emit('admitted', job, queue_depth=len(self.queue), request_body_bytes=len(body),
                      reception_us=int((job.queued-job.entered)*1e6))
            self.wake.set()
        try:
            async with asyncio.timeout_at(job.deadline):
                result = await asyncio.shield(job.future)
        except TimeoutError:
            self.cancel(job, 504, 'deadline_exceeded')
            raise ServiceError(504, 'deadline_exceeded') from None
        except asyncio.CancelledError:
            self.cancel(job, 499, 'client_disconnected')
            raise
        if isinstance(result, ServiceError):
            raise result
        return result

    async def work(self, worker_id):
        while not self.closed:
            await self.wake.wait()
            self.wake.clear()
            while self.queue and not self.closed:
                job = self.queue[0]
                if time.monotonic() >= job.deadline:
                    self.cancel(job, 504, 'deadline_exceeded')
                    continue
                self.queue.popleft()
                self.active[worker_id] = job
                self.emit("worker_started", job, worker_id=worker_id, active_workers=len(self.active))
                job.state, job.started = 'running', time.monotonic()
                try:
                    result = await asyncio.get_running_loop().run_in_executor(self.executors[worker_id], self.engines[worker_id], job.body)
                except Exception as error:
                    self.emit('engine_error', job, error_type=type(error).__name__)
                    self.cancel(job, 500, 'inference_failed')
                else:
                    client = self.clients.get(job.client_id)
                    if not client or client.session != job.session_id:
                        self.cancel(job, 410, 'session_replaced')
                    elif time.monotonic() >= job.deadline:
                        self.cancel(job, 504, 'deadline_exceeded')
                    elif not job.future.done():
                        job.future.set_result(result)
                        self.emit('terminal', job, worker_id=worker_id, status=200, response_body_bytes=len(result),
                                  queue_us=int((job.started-job.queued)*1e6),
                                  worker_us=int((time.monotonic()-job.started)*1e6),
                                  elapsed_us=int((time.monotonic()-job.entered)*1e6))
                finally:
                    self.emit('worker_finished', job, worker_id=worker_id, worker_us=int((time.monotonic()-job.started)*1e6))
                    job.state = 'finished'
                    del self.active[worker_id]
                    self.release(job)
