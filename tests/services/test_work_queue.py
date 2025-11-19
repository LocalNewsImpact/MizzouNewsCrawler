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
    """Multiple workers get non-overlapping domains."""
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

    # Assert each worker got 3-5 domains (or whatever is available)
    assert 3 <= len(worker1_domains) <= 5
    assert 3 <= len(worker2_domains) <= 5
    # Worker 3 might get fewer domains if not enough remain
    assert len(worker3_domains) >= 3 or len(available_domains) < 15


def test_sticky_domain_assignments(coordinator):
    """Worker keeps same domains across multiple requests."""
    # Mock database response
    mock_session = MagicMock()
    domains_data = [(f"domain{i}.com", f"Domain {i}", 10) for i in range(10)]
    mock_session.execute.return_value = iter(domains_data)
    coordinator.db.get_session.return_value.__enter__.return_value = mock_session

    # First request
    available_domains = [
        {"source": f"domain{i}.com", "article_count": 10} for i in range(10)
    ]
    first_assignment = coordinator._assign_domains_to_worker(
        "worker-1", available_domains
    )
    coordinator.worker_domains["worker-1"] = {
        "domains": first_assignment,
        "last_seen": time.time(),
    }

    # Second request (simulate cooldown expiry)
    time.sleep(0.1)
    second_assignment = coordinator._assign_domains_to_worker(
        "worker-1", available_domains
    )

    # Assert worker kept same domains
    assert first_assignment == second_assignment


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
    """Worker gets max_articles_per_domain even if domain has many articles."""
    # Mock database response
    mock_session = MagicMock()

    # First call for available domains
    domains_data = [("domain1.com", "Domain 1", 200)]

    # Second call for candidate_links (simulate 200 articles from domain1)
    articles_data = [
        (f"id-{i}", f"https://domain1.com/article-{i}", "domain1.com", "Domain 1")
        for i in range(200)
    ]

    mock_session.execute.side_effect = [iter(domains_data), iter(articles_data)]
    coordinator.db.get_session.return_value.__enter__.return_value = mock_session

    # Request work with max_articles_per_domain=3
    response = coordinator.request_work("worker-1", 50, 3)

    # Assert exactly 3 articles returned
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
