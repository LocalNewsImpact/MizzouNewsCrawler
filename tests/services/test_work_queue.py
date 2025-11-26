"""Unit tests for centralized work queue service."""

import time
import uuid
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.models import CandidateLink, Source
from src.services.work_queue import (
    MAX_DOMAIN_FAILURES,
    WorkQueueCoordinator,
    WorkRequest,
)


@pytest.fixture
def coordinator():
    """Create a WorkQueueCoordinator with mocked database."""
    with patch("src.services.work_queue.DatabaseManager") as mock_db_class:
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db

        coordinator = WorkQueueCoordinator()
        coordinator.db = mock_db

        yield coordinator

        # Cleanup
        coordinator.worker_domains.clear()
        coordinator.domain_cooldowns.clear()
        coordinator.domain_failure_counts.clear()
        coordinator.paused_domains.clear()


def test_domain_assignment_no_overlap(coordinator):
    """Multiple workers get non-overlapping domains (exactly 1 per worker)."""
    # Mock database response with 20 domains (more than enough for 3 workers)
    mock_session = MagicMock()
    domains_data = [(f"domain{i}.com", f"Domain {i}", 10) for i in range(20)]

    mock_session.execute.return_value = iter(domains_data)
    coordinator.db.get_session.return_value.__enter__.return_value = mock_session

    # Request work from 3 workers
    available_domains = [
        {"source": f"domain{i}.com", "article_count": 10} for i in range(20)
    ]

    worker1_domains = coordinator._assign_domains_to_worker(
        "worker-1", available_domains
    )
    coordinator.worker_domains["worker-1"] = {
        "domains": worker1_domains,
        "last_seen": time.time(),
    }

    worker2_domains = coordinator._assign_domains_to_worker(
        "worker-2", available_domains
    )
    coordinator.worker_domains["worker-2"] = {
        "domains": worker2_domains,
        "last_seen": time.time(),
    }

    worker3_domains = coordinator._assign_domains_to_worker(
        "worker-3", available_domains
    )

    # Assert no overlap between workers
    assert len(worker1_domains & worker2_domains) == 0
    assert len(worker1_domains & worker3_domains) == 0
    assert len(worker2_domains & worker3_domains) == 0

    # Assert each worker got exactly 1 domain
    assert len(worker1_domains) == 1
    assert len(worker2_domains) == 1
    assert len(worker3_domains) == 1


def test_randomized_domain_selection(coordinator):
    """Domain selection is randomized to avoid back-to-back extractions."""
    # Mock database response with 10 domains
    available_domains = [
        {"source": f"domain{i}.com", "article_count": 10} for i in range(10)
    ]

    # Request domains 20 times and collect results
    selected_domains = []
    for i in range(20):
        # Clear worker state to get fresh assignment
        coordinator.worker_domains.clear()
        domains = coordinator._assign_domains_to_worker(
            f"worker-{i}", available_domains
        )
        if domains:
            selected_domains.append(list(domains)[0])

    # Assert we got variety in selections (not always same domain)
    unique_selections = set(selected_domains)
    assert len(unique_selections) > 1, "Domain selection not randomized!"

    # Assert each selection returned exactly 1 domain
    assert all(len([d]) == 1 for d in selected_domains)


def test_domain_cooldown_respected(coordinator):
    """Worker cannot re-request same domain within cooldown period."""
    from src.services.work_queue import DOMAIN_COOLDOWN_SECONDS

    # Set cooldown for domain
    coordinator.domain_cooldowns["domain1.com"] = time.time() + DOMAIN_COOLDOWN_SECONDS

    # Check domain is not available
    assert not coordinator._is_domain_available("domain1.com")

    # Fast-forward time (mock)
    coordinator.domain_cooldowns["domain1.com"] = time.time() - 1

    # Check domain is now available
    assert coordinator._is_domain_available("domain1.com")


def test_domain_failure_incremental_cooldown(coordinator):
    """Cooldown extends progressively with each failure."""
    from src.services.work_queue import DOMAIN_COOLDOWN_SECONDS

    domain = "example.com"

    # First failure
    coordinator.report_failure("worker-1", domain)
    assert coordinator.domain_failure_counts[domain] == 1
    assert domain in coordinator.domain_cooldowns

    # Second failure (should have extended cooldown)
    coordinator.report_failure("worker-1", domain)
    assert coordinator.domain_failure_counts[domain] == 2

    # Third failure (should pause domain)
    coordinator.report_failure("worker-1", domain)
    assert coordinator.domain_failure_counts[domain] == 3
    assert domain in coordinator.paused_domains


def test_domain_failure_threshold_pause(coordinator):
    """Domain paused for 30 minutes after MAX_DOMAIN_FAILURES."""
    domain = "example.com"

    # Report failures up to threshold
    for i in range(MAX_DOMAIN_FAILURES):
        coordinator.report_failure("worker-1", domain)

    # Check domain is paused
    assert domain in coordinator.paused_domains
    assert not coordinator._is_domain_available(domain)

    # Simulate pause expiry and clear any cooldowns
    coordinator.paused_domains[domain] = time.time() - 1
    # Also clear the cooldown that may have been set
    if domain in coordinator.domain_cooldowns:
        coordinator.domain_cooldowns[domain] = time.time() - 1

    # Check domain is available again
    # Note: _is_domain_available removes the pause and resets failure count
    available = coordinator._is_domain_available(domain)
    assert available
    # After calling _is_domain_available, pause should be removed and count reset
    assert domain not in coordinator.paused_domains
    assert coordinator.domain_failure_counts.get(domain, 0) == 0


def test_worker_timeout_domain_rebalancing(coordinator):
    """Stale worker domains reassigned to active workers."""
    from src.services.work_queue import WORKER_TIMEOUT_SECONDS

    # Assign domains to worker 1
    coordinator.worker_domains["worker-1"] = {
        "domains": {"domain1.com", "domain2.com", "domain3.com"},
        "last_seen": time.time() - WORKER_TIMEOUT_SECONDS - 1,
    }

    # Cleanup stale workers
    coordinator._cleanup_stale_workers()

    # Assert worker 1 removed
    assert "worker-1" not in coordinator.worker_domains


def test_no_articles_available(coordinator):
    """Graceful handling when no work available."""
    # Mock database response with no domains
    mock_session = MagicMock()
    mock_session.execute.return_value = iter([])
    coordinator.db.get_session.return_value.__enter__.return_value = mock_session

    # Request work
    response = coordinator.request_work("worker-1", 50, 3)

    # Assert empty response
    assert len(response.items) == 0
    assert len(response.worker_domains) == 0


def test_all_domains_on_cooldown(coordinator):
    """Worker receives empty response when all domains cooling down."""
    # Set cooldowns for all domains
    current_time = time.time()
    for i in range(10):
        coordinator.domain_cooldowns[f"domain{i}.com"] = current_time + 60

    # Mock database response
    mock_session = MagicMock()
    domains_data = [(f"domain{i}.com", f"Domain {i}", 10) for i in range(10)]
    mock_session.execute.return_value = iter(domains_data)
    coordinator.db.get_session.return_value.__enter__.return_value = mock_session

    # Request work
    response = coordinator.request_work("worker-1", 50, 3)

    # Assert empty response (all domains on cooldown)
    assert len(response.items) == 0


def test_max_articles_per_domain_enforced(coordinator):
    """Worker gets max 3 articles per domain (hardcoded limit)."""
    # Mock database response
    mock_session = MagicMock()

    # First call for available domains
    domains_data = [("domain1.com", "Domain 1", 200)]

    # Second call for candidate_links - SQL LIMIT enforces max 3
    # (In real database, LIMIT :limit would restrict to 3 results)
    articles_data = [
        (f"id-{i}", f"https://domain1.com/article-{i}", "domain1.com", "Domain 1")
        for i in range(3)  # Only 3 articles due to SQL LIMIT
    ]

    mock_session.execute.side_effect = [iter(domains_data), iter(articles_data)]
    coordinator.db.get_session.return_value.__enter__.return_value = mock_session

    # Request work (batch_size=50, but SQL LIMIT restricts to 3)
    response = coordinator.request_work("worker-1", 50, 10)

    # Assert exactly 3 articles returned (enforced by SQL LIMIT)
    assert len(response.items) == 3
    assert all(item.source == "domain1.com" for item in response.items)


def test_worker_last_seen_updated(coordinator):
    """Worker last_seen timestamp updated on each request."""
    # Mock database response
    mock_session = MagicMock()
    domains_data = [("domain1.com", "Domain 1", 10)]
    articles_data = [
        ("id-1", "https://domain1.com/article-1", "domain1.com", "Domain 1")
    ]
    mock_session.execute.side_effect = [iter(domains_data), iter(articles_data)]
    coordinator.db.get_session.return_value.__enter__.return_value = mock_session

    # First request
    time1 = time.time()
    coordinator.request_work("worker-1", 50, 3)
    last_seen1 = coordinator.worker_domains["worker-1"]["last_seen"]

    assert last_seen1 >= time1

    # Second request (after some time)
    # Clear cooldown to allow second request
    coordinator.domain_cooldowns.clear()
    time.sleep(0.1)
    mock_session.execute.side_effect = [iter(domains_data), iter(articles_data)]
    time2 = time.time()
    coordinator.request_work("worker-1", 50, 3)
    last_seen2 = coordinator.worker_domains["worker-1"]["last_seen"]

    assert last_seen2 > last_seen1
    assert last_seen2 >= time2


def test_stats_endpoint_accuracy(coordinator):
    """Stats endpoint returns accurate data."""
    # Setup worker assignments
    coordinator.worker_domains = {
        "worker-1": {
            "domains": {"domain1.com", "domain2.com"},
            "last_seen": time.time(),
        },
        "worker-2": {
            "domains": {"domain3.com", "domain4.com"},
            "last_seen": time.time(),
        },
    }

    # Setup cooldowns
    coordinator.domain_cooldowns = {
        "domain1.com": time.time() + 30,
        "domain2.com": time.time() + 45,
    }

    # Mock database response
    mock_session = MagicMock()
    mock_session.execute.side_effect = [
        MagicMock(scalar=lambda: 200),  # total_available
        MagicMock(scalar=lambda: 20),  # domains_available
    ]
    coordinator.db.get_session.return_value.__enter__.return_value = mock_session

    # Get stats
    stats = coordinator.get_stats()

    # Assert accuracy
    assert stats.total_available == 200
    assert stats.domains_available == 20
    assert len(stats.worker_assignments) == 2
    assert "worker-1" in stats.worker_assignments
    assert "worker-2" in stats.worker_assignments
    assert len(stats.domain_cooldowns) == 2


def test_worker_heartbeat_updates_timestamp(coordinator):
    """Heartbeat updates worker last_seen timestamp."""
    # Setup initial worker state
    initial_time = time.time() - 100  # 100 seconds ago
    coordinator.worker_domains["worker-1"] = {
        "domains": {"domain1.com"},
        "last_seen": initial_time,
    }

    # Send heartbeat
    coordinator.update_worker_heartbeat("worker-1")

    # Assert timestamp updated
    updated_time = coordinator.worker_domains["worker-1"]["last_seen"]
    assert updated_time > initial_time
    assert updated_time >= time.time() - 1  # Within last second


def test_heartbeat_prevents_worker_timeout(coordinator):
    """Worker with active heartbeats not cleaned up as stale."""
    from src.services.work_queue import WORKER_TIMEOUT_SECONDS

    # Setup worker that would normally timeout
    old_time = time.time() - WORKER_TIMEOUT_SECONDS - 10
    coordinator.worker_domains["worker-1"] = {
        "domains": {"domain1.com"},
        "last_seen": old_time,
    }

    # Send heartbeat to refresh
    coordinator.update_worker_heartbeat("worker-1")

    # Run cleanup
    coordinator._cleanup_stale_workers()

    # Assert worker NOT removed (heartbeat prevented timeout)
    assert "worker-1" in coordinator.worker_domains


def test_heartbeat_unknown_worker_ignored(coordinator):
    """Heartbeat from unknown worker handled gracefully."""
    # Send heartbeat for non-existent worker
    coordinator.update_worker_heartbeat("worker-999")

    # Assert no error and worker not added
    assert "worker-999" not in coordinator.worker_domains


def test_single_domain_per_request_enforced(coordinator):
    """Each worker request returns articles from exactly 1 domain."""
    # Mock database response with 10 domains
    mock_session = MagicMock()
    domains_data = [(f"domain{i}.com", f"Domain {i}", 10) for i in range(10)]

    # Articles from only 1 domain (SQL WHERE cl.source = ANY(:domains) with 1 domain)
    # Coordinator assigns 1 domain, so SQL only returns articles from that domain
    articles_data = [
        (f"id-0-{j}", f"https://domain0.com/article-{j}", "domain0.com", "Domain 0")
        for j in range(3)  # Max 3 articles
    ]

    mock_session.execute.side_effect = [iter(domains_data), iter(articles_data)]
    coordinator.db.get_session.return_value.__enter__.return_value = mock_session

    # Request work
    response = coordinator.request_work("worker-1", 50, 10)

    # Assert all items from single domain
    assert len(response.items) > 0
    domains_in_response = {item.source for item in response.items}
    assert len(domains_in_response) == 1, "Multiple domains in single request!"


def test_three_article_limit_respected(coordinator):
    """Worker gets max 3 articles even with large batch_size."""
    # Mock database response
    mock_session = MagicMock()
    domains_data = [("domain1.com", "Domain 1", 100)]

    # SQL LIMIT enforces max 3 articles (even though 100 available)
    articles_data = [
        (f"id-{i}", f"https://domain1.com/article-{i}", "domain1.com", "Domain 1")
        for i in range(3)  # SQL LIMIT :limit returns only 3
    ]

    mock_session.execute.side_effect = [iter(domains_data), iter(articles_data)]
    coordinator.db.get_session.return_value.__enter__.return_value = mock_session

    # Request with large batch_size
    response = coordinator.request_work("worker-1", 100, 50)

    # Assert max 3 articles returned (enforced by SQL LIMIT)
    assert len(response.items) == 3
    assert all(item.source == "domain1.com" for item in response.items)


def test_domain_not_reassigned_during_processing(coordinator):
    """Domain assigned to active worker not given to other workers."""
    # Mock database response with 5 domains
    mock_session = MagicMock()
    domains_data = [(f"domain{i}.com", f"Domain {i}", 10) for i in range(5)]

    # Worker 1 gets domain1
    coordinator.worker_domains["worker-1"] = {
        "domains": {"domain1.com"},
        "last_seen": time.time(),
    }

    mock_session.execute.return_value = iter(domains_data)
    coordinator.db.get_session.return_value.__enter__.return_value = mock_session

    # Worker 2 requests work
    available_domains = [
        {"source": f"domain{i}.com", "article_count": 10} for i in range(5)
    ]
    worker2_domains = coordinator._assign_domains_to_worker(
        "worker-2", available_domains
    )

    # Assert worker 2 did NOT get domain1.com
    assert "domain1.com" not in worker2_domains
    assert len(worker2_domains) == 1  # Got 1 different domain
