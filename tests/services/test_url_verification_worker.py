from __future__ import annotations

import asyncio

from src.services.url_verification_worker import AsyncVerificationWorker


def test_worker_sheds_when_backlog_exceeds_threshold() -> None:
    async def scenario() -> None:
        processed: list[str] = []
        gate = asyncio.Event()

        async def processor(item: str) -> None:
            processed.append(item)
            if item == "block":
                await gate.wait()

        worker = AsyncVerificationWorker(
            processor,
            max_queue_size=8,
            shed_threshold=2,
            concurrency=1,
            stats_history=3,
        )
        await worker.start()

        assert await worker.submit("block")
        assert await worker.submit("queued")

        results = [await worker.submit(f"shed-{i}") for i in range(3)]
        assert results == [False, False, False]
        assert worker.stats.shed == 3
        assert worker.stats.last_shed_reason == "threshold"
        assert list(worker.stats.shed_samples) == [
            "shed-0",
            "shed-1",
            "shed-2",
        ]

        gate.set()
        await asyncio.sleep(0)
        await worker.stop()

        assert processed[:2] == ["block", "queued"]

    asyncio.run(scenario())


def test_worker_sheds_when_queue_full() -> None:
    async def scenario() -> None:
        gate = asyncio.Event()

        async def processor(item: str) -> None:
            if item == "block":
                await gate.wait()

        worker = AsyncVerificationWorker(
            processor,
            max_queue_size=2,
            shed_threshold=4,
            concurrency=1,
        )
        await worker.start()

        assert await worker.submit("block")
        await asyncio.sleep(0)
        assert await worker.submit("queued-0")
        assert await worker.submit("queued-1")
        assert not await worker.submit("trigger-full")
        assert worker.stats.shed == 1
        assert worker.stats.last_shed_reason == "queue_full"
        assert list(worker.stats.shed_samples) == ["trigger-full"]

        gate.set()
        await asyncio.sleep(0)
        await worker.stop()

    asyncio.run(scenario())


def test_worker_accepts_after_backlog_clears() -> None:
    async def scenario() -> None:
        processed: list[str] = []
        gate = asyncio.Event()

        async def processor(item: str) -> None:
            processed.append(item)
            if item == "block":
                await gate.wait()

        worker = AsyncVerificationWorker(
            processor,
            max_queue_size=4,
            shed_threshold=2,
            concurrency=1,
        )
        await worker.start()

        assert await worker.submit("block")
        assert await worker.submit("queued")
        assert not await worker.submit("shed-candidate")

        gate.set()
        await asyncio.sleep(0.05)

        assert await worker.submit("late")
        await asyncio.sleep(0.05)
        await worker.stop()

        assert "late" in processed
        assert worker.stats.shed == 1

    asyncio.run(scenario())


def test_worker_recovers_after_long_running_backlog() -> None:
    async def scenario() -> None:
        processed: list[str] = []
        blocker = asyncio.Event()

        async def processor(item: str) -> None:
            processed.append(item)
            if item == "block":
                await blocker.wait()
            await asyncio.sleep(0.01)

        worker = AsyncVerificationWorker(
            processor,
            max_queue_size=4,
            shed_threshold=3,
            concurrency=1,
            stats_history=2,
        )
        await worker.start()

        assert await worker.submit("block")
        assert await worker.submit("queued-0")
        assert await worker.submit("queued-1")

        shed_results = [
            await worker.submit(f"shed-{i}")
            for i in range(3)
        ]
        assert shed_results == [False, False, False]
        assert worker.stats.shed == 3
        assert list(worker.stats.shed_samples) == ["shed-1", "shed-2"]

        backlog = await worker.backlog()
        assert backlog >= 3
        assert worker.stats.max_backlog >= backlog

        blocker.set()
        # Wait for the backlog to drain fully.
        for _ in range(50):
            if await worker.backlog() == 0:
                break
            await asyncio.sleep(0.01)

        assert await worker.submit("post-release")
        await asyncio.sleep(0.05)
        await worker.stop()

        assert "post-release" in processed

    asyncio.run(scenario())


def test_worker_captures_sync_processor_exception() -> None:
    async def scenario() -> None:
        handled: list[str] = []

        def processor(item: str) -> None:
            if item == "boom":
                raise RuntimeError("processor exploded")
            handled.append(item)

        worker = AsyncVerificationWorker(
            processor,
            max_queue_size=3,
            shed_threshold=2,
            concurrency=1,
        )
        await worker.start()

        assert await worker.submit("boom")
        assert await worker.submit("recover")

        await asyncio.sleep(0.05)
        await worker.stop()

        assert isinstance(worker.last_exception, RuntimeError)
        assert handled == ["recover"]
        assert worker.stats.accepted == 2

    asyncio.run(scenario())
