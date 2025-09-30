"""Async worker helper for URL verification load shedding.

This module provides the building blocks for the upcoming asynchronous
verification refactor.  It exposes a lightweight worker that executes
verifications in the background while monitoring backlog pressure so the
system can shed excess work before overwhelming downstream services.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Deque, Optional

__all__ = ["WorkerStats", "AsyncVerificationWorker"]

Processor = Callable[[Any], Awaitable[None] | None]


@dataclass(slots=True)
class WorkerStats:
    """Simple container for worker telemetry."""

    accepted: int = 0
    shed: int = 0
    max_backlog: int = 0
    last_shed_reason: Optional[str] = None
    sample_limit: int = 25
    shed_samples: Deque[Any] = field(init=False)

    def __post_init__(self) -> None:  # pragma: no cover - trivial
        self.shed_samples = deque(maxlen=self.sample_limit)


class AsyncVerificationWorker:
    """Asynchronous worker with load-shedding safeguards.

    The worker processes items using the provided ``processor`` coroutine (or
    synchronous function).  Incoming work is queued until the backlog crosses
    ``shed_threshold``, at which point new submissions are rejected to prevent
    runaway queue growth.
    """

    def __init__(
        self,
        processor: Processor,
        *,
        max_queue_size: int = 128,
        shed_threshold: Optional[int] = None,
        concurrency: int = 4,
        stats_history: int = 25,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be at least 1")
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")

        if shed_threshold is None:
            shed_threshold = max_queue_size - 1 if max_queue_size > 1 else 1
        else:
            shed_threshold = max(1, shed_threshold)

        self._queue: asyncio.Queue[Any] = asyncio.Queue(max_queue_size)
        self._shed_threshold = shed_threshold
        self._concurrency = concurrency
        self._processor = processor
        self._processor_is_async = inspect.iscoroutinefunction(processor)
        self._logger = logger or logging.getLogger(
            f"{__name__}.AsyncVerificationWorker"
        )

        self._state_lock = asyncio.Lock()
        self._inflight = 0
        self._running = False
        self._workers: list[asyncio.Task[None]] = []
        self._sentinel = object()
        self._last_exception: Optional[BaseException] = None

        self.stats = WorkerStats(sample_limit=stats_history)

    @property
    def shed_threshold(self) -> int:
        """Current backlog threshold that triggers load shedding."""

        return self._shed_threshold

    @property
    def last_exception(self) -> Optional[BaseException]:
        """Return the most recent processor exception, if any."""

        return self._last_exception

    async def start(self) -> None:
        """Start background worker tasks."""

        if self._running:
            return

        self._running = True
        self._workers = [
            asyncio.create_task(
                self._worker_loop(),
                name=f"verification-worker-{i}",
            )
            for i in range(self._concurrency)
        ]

    async def stop(self) -> None:
        """Stop workers and wait for all pending work to finish."""

        if not self._running:
            return

        self._running = False
        for _ in range(len(self._workers)):
            await self._queue.put(self._sentinel)

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

        await self._queue.join()

    async def submit(
        self, item: Any, *, shed_reason: Optional[str] = None
    ) -> bool:
        """Attempt to queue an item for processing.

        Returns ``True`` when the item is accepted.  When backlog pressure
        exceeds the configured threshold (or the queue is full), the item is
        rejected, ``False`` is returned, and the rejection is recorded in
        :attr:`stats`.
        """

        async with self._state_lock:
            backlog = self._queue.qsize() + self._inflight
            if backlog >= self._shed_threshold:
                self._record_shed(item, shed_reason or "threshold")
                return False

        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            async with self._state_lock:
                self._record_shed(item, "queue_full")
            return False

        async with self._state_lock:
            self.stats.accepted += 1
            backlog = self._queue.qsize() + self._inflight
            if backlog > self.stats.max_backlog:
                self.stats.max_backlog = backlog

        return True

    async def backlog(self) -> int:
        """Return the current backlog including in-flight work."""

        async with self._state_lock:
            return self._queue.qsize() + self._inflight

    async def _worker_loop(self) -> None:
        while True:
            item = await self._queue.get()
            if item is self._sentinel:
                self._queue.task_done()
                break

            async with self._state_lock:
                self._inflight += 1
                backlog = self._queue.qsize() + self._inflight
                if backlog > self.stats.max_backlog:
                    self.stats.max_backlog = backlog

            try:
                await self._run_processor(item)
            except Exception as exc:  # pragma: no cover - defensive logging
                self._last_exception = exc
                self._logger.exception(
                    "AsyncVerificationWorker processor error",
                    exc_info=exc,
                )
            finally:
                async with self._state_lock:
                    self._inflight -= 1

            self._queue.task_done()

    async def _run_processor(self, item: Any) -> None:
        if self._processor_is_async:
            await self._processor(item)  # type: ignore[arg-type]
            return

    # Run synchronous processor in a worker thread to avoid blocking
    # the event loop.
        await asyncio.to_thread(self._processor, item)

    def _record_shed(self, item: Any, reason: str) -> None:
        self.stats.shed += 1
        self.stats.last_shed_reason = reason
        self.stats.shed_samples.append(item)
