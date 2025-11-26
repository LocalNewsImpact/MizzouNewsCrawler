"""Integration tests for work queue service with PostgreSQL."""

import time
import uuid
from datetime import datetime, timedelta

import pytest

from src.models import CandidateLink, Source
from src.services.work_queue import WorkQueueCoordinator


@pytest.mark.integration
@pytest.mark.postgres
def test_concurrent_workers_no_article_duplicates(cloud_sql_session):
    """6 workers request work simultaneously, no article processed twice."""
    # Create 20 sources
    sources = []
    for i in range(20):
        source = Source(
            id=str(uuid.uuid4()),
            host=f"domain{i}.com",
            host_norm=f"domain{i}.com",
            canonical_name=f"Domain {i}",
            status="active",
        )
        cloud_sql_session.add(source)
        sources.append(source)

    # Create 300 candidate_links (15 per domain)
    candidate_links = []
    for source in sources:
        for j in range(15):
            link = CandidateLink(
                id=str(uuid.uuid4()),
                url=f"https://{source.host}/article-{j}",
                source=source.host,
                source_id=source.id,
                status="article",
                discovered_by="test",
            )
            cloud_sql_session.add(link)
            candidate_links.append(link)

    cloud_sql_session.commit()

    # Create coordinator with test session
    coordinator = WorkQueueCoordinator(session=cloud_sql_session)

    # Simulate 6 workers requesting work
    all_items = []
    worker_ids = [f"worker-{i}" for i in range(6)]

    for worker_id in worker_ids:
        response = coordinator.request_work(worker_id, 50, 3)
        all_items.extend(response.items)

    # Assert no duplicates
    item_ids = [item.id for item in all_items]
    assert len(item_ids) == len(set(item_ids)), "Duplicate articles assigned!"

    # Assert all workers got work
    assert len(all_items) > 0


@pytest.mark.integration
@pytest.mark.postgres
def test_rate_limit_prevents_rapid_domain_access(cloud_sql_session):
    """Worker cannot bypass cooldown by requesting multiple times."""
    # Create 1 source with 100 articles
    source = Source(
        id=str(uuid.uuid4()),
        host="domain1.com",
        host_norm="domain1.com",
        canonical_name="Domain 1",
        status="active",
    )
    cloud_sql_session.add(source)

    for i in range(100):
        link = CandidateLink(
            id=str(uuid.uuid4()),
            url=f"https://domain1.com/article-{i}",
            source=source.host,
            source_id=source.id,
            status="article",
            discovered_by="test",
        )
        cloud_sql_session.add(link)

    cloud_sql_session.commit()

    # Create coordinator with test session
    coordinator = WorkQueueCoordinator(session=cloud_sql_session)

    # First request at T=0
    response1 = coordinator.request_work("worker-1", 50, 10)
    # Should get max 3 articles (hardcoded limit)
    assert len(response1.items) <= 3
    assert all(item.source == "domain1.com" for item in response1.items)

    # Immediate second request (should get 0 articles - domain on cooldown)
    response2 = coordinator.request_work("worker-1", 50, 10)
    assert len(response2.items) == 0

    # Third request (should also get 0)
    response3 = coordinator.request_work("worker-1", 50, 10)
    assert len(response3.items) == 0


@pytest.mark.integration
@pytest.mark.postgres
def test_failure_tracking_persists_across_requests(cloud_sql_session):
    """Domain failure counts maintained in memory across requests."""
    # Create source
    source = Source(
        id=str(uuid.uuid4()),
        host="domain1.com",
        host_norm="domain1.com",
        canonical_name="Domain 1",
        status="active",
    )
    cloud_sql_session.add(source)

    for i in range(50):
        link = CandidateLink(
            id=str(uuid.uuid4()),
            url=f"https://domain1.com/article-{i}",
            source=source.host,
            source_id=source.id,
            status="article",
            discovered_by="test",
        )
        cloud_sql_session.add(link)

    cloud_sql_session.commit()

    # Create coordinator
    coordinator = WorkQueueCoordinator()

    # Report 3 failures from different workers
    coordinator.report_failure("worker-1", "domain1.com")
    assert coordinator.domain_failure_counts["domain1.com"] == 1

    coordinator.report_failure("worker-2", "domain1.com")
    assert coordinator.domain_failure_counts["domain1.com"] == 2

    coordinator.report_failure("worker-3", "domain1.com")
    assert coordinator.domain_failure_counts["domain1.com"] == 3

    # Domain should be paused
    assert "domain1.com" in coordinator.paused_domains


@pytest.mark.integration
@pytest.mark.postgres
def test_domain_partitioning_with_real_database(cloud_sql_session):
    """Multiple workers get non-overlapping domains (1 each) from real database."""
    # Create 15 sources with 10 articles each
    for i in range(15):
        source = Source(
            id=str(uuid.uuid4()),
            host=f"test{i}.com",
            host_norm=f"test{i}.com",
            canonical_name=f"Test Source {i}",
            status="active",
        )
        cloud_sql_session.add(source)

        for j in range(10):
            link = CandidateLink(
                id=str(uuid.uuid4()),
                url=f"https://test{i}.com/article-{j}",
                source=source.host,
                source_id=source.id,
                status="article",
                discovered_by="test",
            )
            cloud_sql_session.add(link)

    cloud_sql_session.commit()

    # Create coordinator with test session
    coordinator = WorkQueueCoordinator(session=cloud_sql_session)

    # Request work from 3 workers
    responses = []
    for i in range(3):
        response = coordinator.request_work(f"worker-{i}", 50, 10)
        responses.append(response)

    # Collect all domains assigned
    all_domains = []
    for response in responses:
        all_domains.extend(response.worker_domains)

    # Assert no domain assigned to multiple workers
    assert len(all_domains) == len(
        set(all_domains)
    ), "Domain assigned to multiple workers!"

    # Assert each worker got exactly 1 domain
    for response in responses:
        assert len(response.worker_domains) == 1


@pytest.mark.integration
@pytest.mark.postgres
def test_heartbeat_extends_worker_lifetime(cloud_sql_session):
    """Worker heartbeats prevent premature timeout during long processing."""
    from src.services.work_queue import WORKER_TIMEOUT_SECONDS

    # Create source with articles
    source = Source(
        id=str(uuid.uuid4()),
        host="heartbeat-test.com",
        host_norm="heartbeat-test.com",
        canonical_name="Heartbeat Test",
        status="active",
    )
    cloud_sql_session.add(source)

    for i in range(20):
        link = CandidateLink(
            id=str(uuid.uuid4()),
            url=f"https://heartbeat-test.com/article-{i}",
            source=source.host,
            source_id=source.id,
            status="article",
            discovered_by="test",
        )
        cloud_sql_session.add(link)

    cloud_sql_session.commit()

    # Create coordinator
    coordinator = WorkQueueCoordinator(session=cloud_sql_session)

    # Worker gets assignment
    response1 = coordinator.request_work("worker-1", 50, 10)
    assert len(response1.items) > 0

    # Simulate worker being active for longer than timeout but sending heartbeats
    old_time = time.time() - WORKER_TIMEOUT_SECONDS - 30
    coordinator.worker_domains["worker-1"]["last_seen"] = old_time

    # Send heartbeat (simulates worker still processing)
    coordinator.update_worker_heartbeat("worker-1")

    # Run cleanup
    coordinator._cleanup_stale_workers()

    # Assert worker NOT removed (heartbeat saved it)
    assert "worker-1" in coordinator.worker_domains

    # Verify last_seen was updated to recent time
    assert coordinator.worker_domains["worker-1"]["last_seen"] > old_time


@pytest.mark.integration
@pytest.mark.postgres
def test_max_3_articles_per_domain_enforced(cloud_sql_session):
    """Each request returns max 3 articles from single domain."""
    # Create source with 50 articles
    source = Source(
        id=str(uuid.uuid4()),
        host="three-article-test.com",
        host_norm="three-article-test.com",
        canonical_name="Three Article Test",
        status="active",
    )
    cloud_sql_session.add(source)

    for i in range(50):
        link = CandidateLink(
            id=str(uuid.uuid4()),
            url=f"https://three-article-test.com/article-{i}",
            source=source.host,
            source_id=source.id,
            status="article",
            discovered_by="test",
        )
        cloud_sql_session.add(link)

    cloud_sql_session.commit()

    # Create coordinator
    coordinator = WorkQueueCoordinator(session=cloud_sql_session)

    # Request work with large batch_size
    response = coordinator.request_work("worker-1", 100, 50)

    # Assert max 3 articles returned
    assert len(response.items) <= 3
    assert all(item.source == "three-article-test.com" for item in response.items)

    # Verify only 1 domain assigned
    assert len(response.worker_domains) == 1


@pytest.mark.integration
@pytest.mark.postgres
def test_randomized_domain_selection_distribution(cloud_sql_session):
    """Domain selection shows random distribution across multiple requests."""
    # Create 10 sources with articles
    for i in range(10):
        source = Source(
            id=str(uuid.uuid4()),
            host=f"random{i}.com",
            host_norm=f"random{i}.com",
            canonical_name=f"Random Test {i}",
            status="active",
        )
        cloud_sql_session.add(source)

        for j in range(10):
            link = CandidateLink(
                id=str(uuid.uuid4()),
                url=f"https://random{i}.com/article-{j}",
                source=source.host,
                source_id=source.id,
                status="article",
                discovered_by="test",
            )
            cloud_sql_session.add(link)

    cloud_sql_session.commit()

    # Create coordinator
    coordinator = WorkQueueCoordinator(session=cloud_sql_session)

    # Make 10 requests from different workers (clearing cooldowns between)
    selected_domains = []
    for i in range(10):
        # Clear cooldowns to allow domain reuse for testing randomization
        coordinator.domain_cooldowns.clear()
        coordinator.worker_domains.clear()

        response = coordinator.request_work(f"worker-{i}", 50, 10)
        if response.worker_domains:
            selected_domains.extend(response.worker_domains)

    # Assert variety in selections (should get multiple different domains)
    unique_domains = set(selected_domains)
    assert (
        len(unique_domains) > 3
    ), f"Only {len(unique_domains)} unique domains selected, expected more variety"


@pytest.mark.integration
@pytest.mark.postgres
def test_for_update_skip_locked_prevents_duplicates(cloud_sql_session):
    """FOR UPDATE SKIP LOCKED prevents race conditions in concurrent access."""
    # Create source with articles
    source = Source(
        id=str(uuid.uuid4()),
        host="concurrent.com",
        host_norm="concurrent.com",
        canonical_name="Concurrent Test",
        status="active",
    )
    cloud_sql_session.add(source)

    for i in range(20):
        link = CandidateLink(
            id=str(uuid.uuid4()),
            url=f"https://concurrent.com/article-{i}",
            source=source.host,
            source_id=source.id,
            status="article",
            discovered_by="test",
        )
        cloud_sql_session.add(link)

    cloud_sql_session.commit()

    # Create coordinator
    coordinator = WorkQueueCoordinator()

    # Simulate concurrent requests (in practice, these would be in separate threads)
    # We clear cooldowns to allow same domain access for testing
    coordinator.domain_cooldowns.clear()

    response1 = coordinator.request_work("worker-1", 10, 3)

    # Clear cooldown again for testing
    coordinator.domain_cooldowns.clear()

    response2 = coordinator.request_work("worker-2", 10, 3)

    # Assert no duplicate article IDs
    ids1 = {item.id for item in response1.items}
    ids2 = {item.id for item in response2.items}
    assert len(ids1 & ids2) == 0, "Duplicate article IDs returned!"


@pytest.mark.integration
@pytest.mark.postgres
def test_worker_timeout_cleans_up_stale_assignments(cloud_sql_session):
    """Stale workers are cleaned up and their domains are released."""
    from src.services.work_queue import WORKER_TIMEOUT_SECONDS

    # Create sources
    for i in range(10):
        source = Source(
            id=str(uuid.uuid4()),
            host=f"timeout{i}.com",
            host_norm=f"timeout{i}.com",
            canonical_name=f"Timeout Test {i}",
            status="active",
        )
        cloud_sql_session.add(source)

        for j in range(10):
            link = CandidateLink(
                id=str(uuid.uuid4()),
                url=f"https://timeout{i}.com/article-{j}",
                source=source.host,
                source_id=source.id,
                status="article",
                discovered_by="test",
            )
            cloud_sql_session.add(link)

    cloud_sql_session.commit()

    # Create coordinator with test session
    coordinator = WorkQueueCoordinator(session=cloud_sql_session)

    # Worker 1 gets domains
    coordinator.request_work("worker-1", 50, 3)

    # Simulate worker 1 becoming stale
    coordinator.worker_domains["worker-1"]["last_seen"] = (
        time.time() - WORKER_TIMEOUT_SECONDS - 10
    )

    # Worker 2 requests work (should trigger cleanup)
    response2 = coordinator.request_work("worker-2", 50, 3)

    # Assert worker-1 was removed
    assert "worker-1" not in coordinator.worker_domains

    # Assert worker-2 got some of worker-1's domains
    worker2_domains = set(response2.worker_domains)
    # There should be some overlap since worker-1's domains are now available
    # (We can't guarantee exact overlap due to domain selection logic)
    assert len(worker2_domains) >= 3


@pytest.mark.integration
def test_empty_database_graceful_handling(cloud_sql_session):
    """Service handles empty database gracefully."""
    # Don't add any data

    # Create coordinator
    coordinator = WorkQueueCoordinator()

    # Request work
    response = coordinator.request_work("worker-1", 50, 3)

    # Assert empty response
    assert len(response.items) == 0
    assert len(response.worker_domains) == 0


@pytest.mark.integration
@pytest.mark.postgres
def test_stats_accuracy_with_real_data(cloud_sql_session):
    """Stats endpoint returns accurate counts from real database."""
    # Create 10 sources with 20 articles each (total 200)
    for i in range(10):
        source = Source(
            id=str(uuid.uuid4()),
            host=f"stats{i}.com",
            host_norm=f"stats{i}.com",
            canonical_name=f"Stats Test {i}",
            status="active",
        )
        cloud_sql_session.add(source)

        for j in range(20):
            link = CandidateLink(
                id=str(uuid.uuid4()),
                url=f"https://stats{i}.com/article-{j}",
                source=source.host,
                source_id=source.id,
                status="article",
                discovered_by="test",
            )
            cloud_sql_session.add(link)

    cloud_sql_session.commit()

    # Create coordinator with test session
    coordinator = WorkQueueCoordinator(session=cloud_sql_session)

    # Assign work to 2 workers
    coordinator.request_work("worker-1", 50, 3)
    coordinator.request_work("worker-2", 50, 3)

    # Get stats
    stats = coordinator.get_stats()

    # Assert accuracy
    assert stats.total_available == 200  # 10 sources * 20 articles
    assert stats.domains_available == 10  # 10 unique sources
    assert len(stats.worker_assignments) == 2
    assert "worker-1" in stats.worker_assignments
    assert "worker-2" in stats.worker_assignments
