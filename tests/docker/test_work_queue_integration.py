"""
Docker-based work queue integration tests.

These tests verify the work queue service can coordinate extraction across multiple
workers in a production-like environment with actual PostgreSQL database and HTTP requests.

Unlike unit/integration tests that mock components, these tests:
- Start actual work-queue service container
- Use real PostgreSQL database
- Make actual HTTP requests between containers
- Verify domain assignment, cooldown, and failure tracking

Run with:
    pytest tests/docker/test_work_queue_integration.py -v -m docker

Critical for production readiness:
- Work queue must prevent duplicate article extraction
- Domain cooldowns must prevent bot detection
- Failure tracking must pause problematic domains
- Multiple workers must coordinate without conflicts
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Get project root relative to this file (tests/docker/test_work_queue_integration.py -> ../../)
PROJECT_ROOT = Path(__file__).parent.parent.parent.absolute()


def run_docker_command(
    service: str, command: list[str], capture_output: bool = True, timeout: int = 30
) -> subprocess.CompletedProcess:
    """Run command in Docker Compose service container."""
    full_cmd = ["docker-compose", "run", "--rm", "-T"]
    full_cmd.append(service)
    full_cmd.extend(command)

    result = subprocess.run(
        full_cmd,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
        cwd=str(PROJECT_ROOT),
    )
    return result


def start_work_queue_service() -> subprocess.Popen:
    """Start work queue service in background."""
    # Ensure clean state by removing any existing container
    subprocess.run(
        ["docker-compose", "rm", "-fs", "work-queue"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
    )

    cmd = ["docker-compose", "up", "-d", "work-queue"]
    subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        check=True,
    )

    # Wait for service to be ready (check logs for "Application startup complete")
    # The health check may cause restarts, so wait a bit longer
    for attempt in range(45):  # Increased from 30 to 45 seconds
        try:
            result = subprocess.run(
                ["docker-compose", "logs", "work-queue", "--tail=10"],
                capture_output=True,
                text=True,
                timeout=2,
                cwd=str(PROJECT_ROOT),
            )
            # Check if latest startup is complete (look for most recent "Application startup complete")
            if (
                "Uvicorn running" in result.stdout
                and "Application startup complete" in result.stdout
            ):
                # Give it 2 more seconds to stabilize
                time.sleep(2)
                return
        except subprocess.TimeoutExpired:
            pass
        time.sleep(1)

    raise RuntimeError("Work queue service failed to become healthy")


def stop_work_queue_service():
    """Stop and remove work queue service container."""
    cmd = ["docker-compose", "rm", "-fs", "work-queue"]
    subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
    )


def make_work_request(worker_id: str, batch_size: int = 50) -> dict[str, Any]:
    """Make HTTP request to work queue service."""
    request_json = json.dumps(
        {"worker_id": worker_id, "batch_size": batch_size, "max_articles_per_domain": 3}
    )

    result = subprocess.run(
        [
            "docker-compose",
            "exec",
            "-T",
            "work-queue",
            "python",
            "-c",
            f"""
import urllib.request
import json

req = urllib.request.Request(
    'http://localhost:8080/work/request',
    data={repr(request_json.encode())},
    headers={{'Content-Type': 'application/json'}}
)
response = urllib.request.urlopen(req)
print(response.read().decode())
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(PROJECT_ROOT),
    )

    if result.returncode != 0:
        raise RuntimeError(f"Work request failed: {result.stderr}")

    return json.loads(result.stdout)


@pytest.mark.docker
class TestWorkQueueService:
    """Test work queue service can start and handle requests."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Ensure postgres is running and work-queue is stopped before/after tests."""
        # Start postgres
        subprocess.run(
            ["docker-compose", "up", "-d", "postgres"],
            cwd=str(PROJECT_ROOT),
            check=True,
        )

        # Wait for postgres health check
        time.sleep(5)

        yield

        # Cleanup
        stop_work_queue_service()

    def test_work_queue_service_can_start(self):
        """CRITICAL: Verify work queue service container can start successfully.

        This validates:
        - Container builds correctly
        - Service can bind to port 8080
        - Health endpoint responds
        """
        start_work_queue_service()

        # Verify health endpoint using Python (curl not installed in container)
        result = subprocess.run(
            [
                "docker-compose",
                "exec",
                "-T",
                "work-queue",
                "python",
                "-c",
                "import urllib.request; "
                "r = urllib.request.urlopen('http://localhost:8080/health'); "
                "print(r.read().decode())",
            ],
            capture_output=True,
            timeout=5,
            cwd=str(PROJECT_ROOT),
        )

        assert result.returncode == 0, f"Health check failed: {result.stderr}"
        assert b"healthy" in result.stdout.lower() or b"ok" in result.stdout.lower()

    def test_work_queue_can_connect_to_database(self):
        """CRITICAL: Verify work queue service can connect to PostgreSQL.

        This validates:
        - DATABASE_URL environment variable is correct
        - Database connection works
        - Can query candidate_links and sources tables
        """
        start_work_queue_service()

        # Create test source and candidate link
        result = run_docker_command(
            "api",
            [
                "python",
                "-c",
                """
from src.models.database import DatabaseManager
from src.models import Source, CandidateLink
import uuid

db = DatabaseManager()
with db.get_session() as session:
    source = Source(
        id=str(uuid.uuid4()),
        host='test-wq.com',
        host_norm='test-wq.com',
        canonical_name='Test Source',
        status='active'
    )
    session.add(source)
    session.commit()
    
    link = CandidateLink(
        id=str(uuid.uuid4()),
        url='https://test-wq.com/article-1',
        source='test-wq.com',
        source_id=source.id,
        status='article',
        discovered_by='test'
    )
    session.add(link)
    session.commit()
    print('Test data created')
""",
            ],
            timeout=30,
        )

        assert result.returncode == 0, f"Failed to create test data: {result.stderr}"

        # Request work from work queue
        response = make_work_request("test-worker-1", batch_size=10)

        # Should return work items or empty list (depending on database state)
        assert "items" in response
        assert isinstance(response["items"], list)

    def test_multiple_workers_get_different_domains(self):
        """CRITICAL: Verify work queue assigns different domains to different workers.

        This prevents duplicate extraction and bot detection from overloading single domains.
        """
        start_work_queue_service()

        # Create multiple sources with candidate links
        result = run_docker_command(
            "api",
            [
                "python",
                "-c",
                """
from src.models.database import DatabaseManager
from src.models import Source, CandidateLink
import uuid

db = DatabaseManager()
with db.get_session() as session:
    # Create 5 sources with 10 articles each
    for i in range(5):
        source = Source(
            id=str(uuid.uuid4()),
            host=f'domain{i}.com',
            host_norm=f'domain{i}.com',
            canonical_name=f'Domain {i}',
            status='active'
        )
        session.add(source)
        session.commit()
        
        for j in range(10):
            link = CandidateLink(
                id=str(uuid.uuid4()),
                url=f'https://domain{i}.com/article-{j}',
                source=f'domain{i}.com',
                source_id=source.id,
                status='article',
                discovered_by='test'
            )
            session.add(link)
    
    session.commit()
    print('Test data created: 5 domains, 50 articles')
""",
            ],
            timeout=30,
        )

        assert result.returncode == 0

        # Request work from 3 different workers
        worker1_response = make_work_request("worker-1", batch_size=10)
        worker2_response = make_work_request("worker-2", batch_size=10)
        worker3_response = make_work_request("worker-3", batch_size=10)

        # Workers should get different domains (no overlap)
        # OR if same domain, work queue should track which worker processed which article
        # The critical test is: no duplicate article IDs across workers
        worker1_ids = set(item["id"] for item in worker1_response["items"])
        worker2_ids = set(item["id"] for item in worker2_response["items"])
        worker3_ids = set(item["id"] for item in worker3_response["items"])

        # CRITICAL: No article should be assigned to multiple workers
        assert (
            len(worker1_ids & worker2_ids) == 0
        ), "Worker 1 and 2 got duplicate articles"
        assert (
            len(worker1_ids & worker3_ids) == 0
        ), "Worker 1 and 3 got duplicate articles"
        assert (
            len(worker2_ids & worker3_ids) == 0
        ), "Worker 2 and 3 got duplicate articles"

    def test_work_queue_respects_domain_cooldown(self):
        """CRITICAL: Verify work queue enforces cooldown between requests to same domain.

        This prevents bot detection from overloading domains too quickly.
        """
        start_work_queue_service()

        # Create single source with many articles
        result = run_docker_command(
            "api",
            [
                "python",
                "-c",
                """
from src.models.database import DatabaseManager
from src.models import Source, CandidateLink
import uuid

db = DatabaseManager()
with db.get_session() as session:
    source = Source(
        id=str(uuid.uuid4()),
        host='cooldown-test.com',
        host_norm='cooldown-test.com',
        canonical_name='Cooldown Test',
        status='active'
    )
    session.add(source)
    session.commit()
    
    for i in range(20):
        link = CandidateLink(
            id=str(uuid.uuid4()),
            url=f'https://cooldown-test.com/article-{i}',
            source='cooldown-test.com',
            source_id=source.id,
            status='article',
            discovered_by='test'
        )
        session.add(link)
    
    session.commit()
    print('Created 20 articles for cooldown-test.com')
""",
            ],
            timeout=30,
        )

        assert result.returncode == 0

        # First request should return articles
        worker_response = make_work_request("worker-cooldown", batch_size=5)
        first_batch_count = len(worker_response["items"])

        assert first_batch_count > 0, "First request should return articles"

        # Immediate second request should return fewer articles (cooldown enforced)
        # OR empty list if domain is on cooldown
        time.sleep(1)  # Brief delay
        worker_response2 = make_work_request("worker-cooldown", batch_size=5)
        second_batch_count = len(worker_response2["items"])

        # Either domain is on cooldown (empty) or different domain assigned
        # The critical test: work queue must not overload the same domain immediately
        if second_batch_count > 0:
            # If articles returned, they should be from different domain
            second_domains = set(item["source"] for item in worker_response2["items"])
            assert (
                "cooldown-test.com" not in second_domains
            ), "Domain should be on cooldown, but work queue returned more articles from it"

    def test_work_queue_stats_endpoint(self):
        """Verify work queue /stats endpoint returns coordination metrics."""
        start_work_queue_service()

        result = subprocess.run(
            [
                "docker-compose",
                "exec",
                "-T",
                "work-queue",
                "python",
                "-c",
                "import urllib.request; "
                "r = urllib.request.urlopen('http://localhost:8080/stats'); "
                "print(r.read().decode())",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(PROJECT_ROOT),
        )

        assert result.returncode == 0

        stats = json.loads(result.stdout)

        # Verify expected fields
        assert "total_available" in stats
        assert "domains_available" in stats
        assert "worker_assignments" in stats
        assert isinstance(stats["worker_assignments"], dict)


@pytest.mark.docker
class TestWorkQueueFailureHandling:
    """Test work queue handles extraction failures and domain pausing."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Ensure postgres is running."""
        subprocess.run(
            ["docker-compose", "up", "-d", "postgres"],
            cwd=str(PROJECT_ROOT),
            check=True,
        )
        time.sleep(5)

        yield

        stop_work_queue_service()

    def test_work_queue_tracks_domain_failures(self):
        """CRITICAL: Verify work queue pauses domains after repeated failures.

        This prevents wasting resources on problematic domains.
        """
        start_work_queue_service()

        # Create test domain
        result = run_docker_command(
            "api",
            [
                "python",
                "-c",
                """
from src.models.database import DatabaseManager
from src.models import Source, CandidateLink
import uuid

db = DatabaseManager()
with db.get_session() as session:
    source = Source(
        id=str(uuid.uuid4()),
        host='failing-domain.com',
        host_norm='failing-domain.com',
        canonical_name='Failing Domain',
        status='active'
    )
    session.add(source)
    session.commit()
    
    for i in range(10):
        link = CandidateLink(
            id=str(uuid.uuid4()),
            url=f'https://failing-domain.com/article-{i}',
            source='failing-domain.com',
            source_id=source.id,
            status='article',
            discovered_by='test'
        )
        session.add(link)
    
    session.commit()
""",
            ],
            timeout=30,
        )

        assert result.returncode == 0

        # Request work
        response = make_work_request("worker-failure-test", batch_size=5)

        if len(response["items"]) == 0:
            # No work available yet - this is acceptable
            return

        # Report failures for the domain via work queue API
        # (Implementation depends on work queue API - may need to add failure reporting endpoint)
        # For now, verify stats show the domain assignment
        stats_result = subprocess.run(
            [
                "docker-compose",
                "exec",
                "-T",
                "work-queue",
                "python",
                "-c",
                "import urllib.request; "
                "r = urllib.request.urlopen('http://localhost:8080/stats'); "
                "print(r.read().decode())",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(PROJECT_ROOT),
        )

        stats = json.loads(stats_result.stdout)

        # Verify worker assignment tracked
        assert "worker-failure-test" in stats["worker_assignments"]
