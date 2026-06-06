from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class QueueTicket:
    wait_ms: float


class SchedulerFull(Exception):
    pass


class RequestScheduler:
    def __init__(self, max_in_flight: int, max_queue: int, queue_timeout_seconds: float):
        self._sem = asyncio.Semaphore(max_in_flight)
        self._max_queue = max_queue
        self._timeout = queue_timeout_seconds
        self._waiting = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> QueueTicket:
        async with self._lock:
            if self._waiting >= self._max_queue:
                raise SchedulerFull("request queue is full")
            self._waiting += 1
        start = time.monotonic()
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._timeout)
        except TimeoutError as exc:
            raise SchedulerFull("request timed out waiting for execution slot") from exc
        finally:
            async with self._lock:
                self._waiting -= 1
        return QueueTicket(wait_ms=round((time.monotonic() - start) * 1000, 2))

    def release(self) -> None:
        self._sem.release()

    @asynccontextmanager
    async def slot(self):
        ticket = await self.acquire()
        try:
            yield ticket
        finally:
            self.release()
