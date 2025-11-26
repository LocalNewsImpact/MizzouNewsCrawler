"""Tests for work-queue FastAPI async endpoints and non-blocking behavior.

These tests verify that the async endpoints properly use run_in_executor to
avoid blocking the event loop during slow database operations.
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def test_concurrent_requests_do_not_block():
    """Multiple concurrent requests should be handled without blocking.

    This test verifies the fix for the async/sync blocking bug where slow
    database queries would block the entire event loop, causing timeouts.
    """
    from src.services.work_queue import app, coordinator

    # Mock slow database operation (simulates 2-second query)
    original_request_work = coordinator.request_work

    def slow_request_work(*args, **kwargs):
        time.sleep(2)  # Simulate slow DB query
        return original_request_work(*args, **kwargs)

    with patch.object(coordinator, "request_work", side_effect=slow_request_work):
        with TestClient(app) as client:
            # Start first request (will take 2 seconds)
            start_time = time.time()

            # Use threading to simulate concurrent requests
            import threading

            results = []

            def make_request(worker_id):
                response = client.post(
                    "/work/request",
                    json={
                        "worker_id": worker_id,
                        "batch_size": 10,
                        "max_articles_per_domain": 3,
                    },
                )
                results.append((worker_id, response.status_code, time.time()))

            # Start 3 concurrent requests
            threads = []
            for i in range(3):
                thread = threading.Thread(target=make_request, args=(f"worker-{i}",))
                thread.start()
                threads.append(thread)

            # Wait for all to complete
            for thread in threads:
                thread.join(timeout=10)

            elapsed = time.time() - start_time

            # All 3 requests should complete
            assert len(results) == 3

            # With run_in_executor, requests run concurrently in thread pool
            # Total time should be ~2 seconds (one batch), not 6 seconds (sequential)
            # Allow some overhead for threading/test environment
            assert (
                elapsed < 4.0
            ), f"Requests blocked sequentially: {elapsed:.1f}s >= 4.0s"

            # All should succeed
            for worker_id, status_code, _ in results:
                assert status_code == 200, f"{worker_id} failed with {status_code}"


def test_health_check_responds_during_slow_request():
    """Health checks should respond even when work requests are slow.

    This verifies that the health endpoint is not blocked by slow work requests.
    """
    from src.services.work_queue import app, coordinator

    # Mock slow request_work (simulates 3-second query)
    def slow_request_work(*args, **kwargs):
        time.sleep(3)
        return MagicMock(items=[], worker_domains={}, status="no_work")

    with patch.object(coordinator, "request_work", side_effect=slow_request_work):
        with TestClient(app) as client:
            import threading

            health_results = []
            work_started = threading.Event()

            def slow_work_request():
                work_started.set()
                client.post(
                    "/work/request",
                    json={
                        "worker_id": "slow-worker",
                        "batch_size": 10,
                        "max_articles_per_domain": 3,
                    },
                )

            # Start slow work request in background
            work_thread = threading.Thread(target=slow_work_request)
            work_thread.start()

            # Wait for work request to start
            work_started.wait(timeout=1)
            time.sleep(0.2)  # Ensure it's in progress

            # Health check should still respond quickly
            start = time.time()
            response = client.get("/health")
            health_time = time.time() - start

            health_results.append((response.status_code, health_time))

            # Wait for work thread to complete
            work_thread.join(timeout=5)

            # Health check should respond quickly (< 1 second)
            status_code, health_time = health_results[0]
            assert status_code == 200
            assert (
                health_time < 1.0
            ), f"Health check blocked for {health_time:.2f}s (should be instant)"


@pytest.mark.asyncio
async def test_async_endpoint_uses_executor():
    """Verify that async endpoints use run_in_executor for blocking operations."""
    from src.services.work_queue import request_work

    # Mock the coordinator to track if we're in the right thread
    import threading

    main_thread_id = threading.get_ident()
    executor_thread_id = None

    def track_thread(*args, **kwargs):
        nonlocal executor_thread_id
        executor_thread_id = threading.get_ident()
        return MagicMock(items=[], worker_domains={}, status="no_work")

    with patch("src.services.work_queue.coordinator") as mock_coordinator:
        mock_coordinator.request_work = track_thread

        # Create mock request
        from src.services.work_queue import WorkRequest

        request = WorkRequest(
            worker_id="test-worker", batch_size=10, max_articles_per_domain=3
        )

        # Call async endpoint
        await request_work(request)

        # Verify coordinator.request_work was called in a different thread
        assert (
            executor_thread_id is not None
        ), "coordinator.request_work was not called"
        assert (
            executor_thread_id != main_thread_id
        ), "Blocking call not run in executor (same thread as async code)"


def test_request_work_endpoint_concurrent_load():
    """Simulate realistic concurrent load with multiple workers."""
    from src.services.work_queue import app

    with TestClient(app) as client:
        import threading

        results = []

        def worker_loop(worker_id, num_requests):
            for i in range(num_requests):
                try:
                    response = client.post(
                        "/work/request",
                        json={
                            "worker_id": f"{worker_id}-{i}",
                            "batch_size": 10,
                            "max_articles_per_domain": 3,
                        },
                        timeout=5.0,
                    )
                    results.append((worker_id, i, response.status_code, "success"))
                except Exception as e:
                    results.append((worker_id, i, None, str(e)))

        # Simulate 5 workers each making 3 requests
        threads = []
        for worker_num in range(5):
            thread = threading.Thread(
                target=worker_loop, args=(f"worker-{worker_num}", 3)
            )
            thread.start()
            threads.append(thread)

        # Wait for all threads
        for thread in threads:
            thread.join(timeout=15)

        # All 15 requests should complete
        assert len(results) == 15, f"Expected 15 results, got {len(results)}"

        # Count successes
        successes = [r for r in results if r[2] == 200 or r[3] == "success"]
        assert len(successes) >= 14, f"Too many failures: {15 - len(successes)}"


def test_heartbeat_endpoint_non_blocking():
    """Heartbeat endpoint should not block during concurrent use."""
    from src.services.work_queue import app

    with TestClient(app) as client:
        import threading

        results = []

        def send_heartbeat(worker_id):
            start = time.time()
            response = client.post(f"/work/heartbeat?worker_id={worker_id}")
            elapsed = time.time() - start
            results.append((worker_id, response.status_code, elapsed))

        # Send 10 concurrent heartbeats
        threads = []
        for i in range(10):
            thread = threading.Thread(target=send_heartbeat, args=(f"worker-{i}",))
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join(timeout=5)

        # All should succeed
        assert len(results) == 10
        for worker_id, status_code, elapsed in results:
            assert status_code == 200
            assert (
                elapsed < 2.0
            ), f"Heartbeat for {worker_id} took {elapsed:.2f}s (too slow)"


def test_stats_endpoint_non_blocking():
    """Stats endpoint should respond quickly even under load."""
    from src.services.work_queue import app, coordinator, StatsResponse

    # Mock slow get_stats (simulates 1-second query)
    def slow_get_stats():
        time.sleep(1)
        return StatsResponse(
            total_available=0,
            total_paused=0,
            domains_available=0,
            domains_paused=0,
            worker_assignments={},
            domain_cooldowns={},
        )

    with patch.object(coordinator, "get_stats", side_effect=slow_get_stats):
        with TestClient(app) as client:
            import threading

            results = []

            def get_stats():
                start = time.time()
                try:
                    response = client.get("/stats")
                    elapsed = time.time() - start
                    results.append((response.status_code, elapsed))
                except Exception:
                    results.append((None, time.time() - start))

            # Make 3 concurrent stats requests
            threads = []
            for _ in range(3):
                thread = threading.Thread(target=get_stats)
                thread.start()
                threads.append(thread)

            for thread in threads:
                thread.join(timeout=5)

            # All should complete
            assert len(results) == 3, f"Only {len(results)} requests completed"

            # With run_in_executor, should complete concurrently (~1s total)
            total_time = max(elapsed for _, elapsed in results)
            assert (
                total_time < 2.0
            ), f"Stats requests blocked: {total_time:.1f}s >= 2.0s"

            # All should succeed
            for status_code, _ in results:
                assert status_code == 200
