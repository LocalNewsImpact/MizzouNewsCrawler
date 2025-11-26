"""Centralized work queue service for domain-aware extraction coordination.

This service coordinates article extraction across multiple worker pods by:
1. Assigning exclusive domains to each worker (3-5 domains per worker)
2. Enforcing rate limits (60s cooldown between requests to same domain)
3. Tracking failures and pausing problematic domains
4. Rebalancing domains when workers become stale

Architecture:
    - Single long-running FastAPI service
    - Thread-safe coordination with locks
    - Read-only database access to candidate_links and sources
    - Sticky domain assignments (workers keep domains across requests)
"""

import logging
import os
import time
from collections import defaultdict
from datetime import datetime
from threading import Lock
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from src.models.database import DatabaseManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Configuration from environment variables
DOMAIN_COOLDOWN_SECONDS = int(os.getenv("DOMAIN_COOLDOWN_SECONDS", "60"))
MAX_DOMAIN_FAILURES = int(os.getenv("MAX_DOMAIN_FAILURES", "3"))
DOMAIN_PAUSE_SECONDS = int(os.getenv("DOMAIN_PAUSE_SECONDS", "1800"))  # 30 minutes
# Worker timeout: 10 minutes is sufficient with heartbeats
WORKER_TIMEOUT_SECONDS = int(os.getenv("WORKER_TIMEOUT_SECONDS", "600"))
# One domain per request for better distribution
MIN_DOMAINS_PER_WORKER = int(os.getenv("MIN_DOMAINS_PER_WORKER", "1"))
MAX_DOMAINS_PER_WORKER = int(os.getenv("MAX_DOMAINS_PER_WORKER", "1"))

# FastAPI app
app = FastAPI(title="Work Queue Service", version="1.0.0")


class WorkRequest(BaseModel):
    """Request for work items from a worker."""

    worker_id: str = Field(..., description="Unique identifier for the worker")
    batch_size: int = Field(
        50, ge=1, le=500, description="Number of articles requested"
    )
    max_articles_per_domain: int = Field(
        3, ge=1, le=20, description="Maximum articles per domain in this batch"
    )


class WorkItem(BaseModel):
    """A single work item (candidate link) to process."""

    id: str
    url: str
    source: str
    canonical_name: Optional[str] = None


class WorkResponse(BaseModel):
    """Response containing work items for a worker."""

    items: list[WorkItem]
    worker_domains: list[str] = Field(
        description="Domains currently assigned to this worker"
    )


class StatsResponse(BaseModel):
    """Statistics about the work queue service."""

    total_available: int
    total_paused: int
    domains_available: int
    domains_paused: int
    worker_assignments: dict[str, list[str]]
    domain_cooldowns: dict[str, float]


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str


class WorkQueueCoordinator:
    """Coordinates work distribution across multiple workers with domain-aware rate limiting."""

    def __init__(self, db: Optional[DatabaseManager] = None, session=None):
        """Initialize the coordinator with thread-safe state management.

        Args:
            db: Optional DatabaseManager instance (for testing)
            session: Optional SQLAlchemy session (for testing with transactions)
        """
        self.db = db if db is not None else DatabaseManager()
        self._test_session = session  # For testing with transactional fixtures
        self.lock = Lock()

        # Worker state: worker_id -> {domains: Set[str], last_seen: float}
        self.worker_domains: dict[str, dict[str, Any]] = {}

        # Domain cooldowns: domain -> last_access_time (float)
        self.domain_cooldowns: dict[str, float] = {}

        # Domain failure tracking: domain -> failure_count
        self.domain_failure_counts: dict[str, int] = {}

        # Paused domains: domain -> pause_until_time (float)
        self.paused_domains: dict[str, float] = {}

        logger.info(
            "WorkQueueCoordinator initialized with config: "
            f"cooldown={DOMAIN_COOLDOWN_SECONDS}s, "
            f"max_failures={MAX_DOMAIN_FAILURES}, "
            f"pause={DOMAIN_PAUSE_SECONDS}s, "
            f"worker_timeout={WORKER_TIMEOUT_SECONDS}s"
        )

    def _get_session(self):
        """Get database session - uses test session if provided, else creates new one.

        Returns:
            Database session object
        """
        if self._test_session is not None:
            return self._test_session
        # For production use, create session via context manager
        # Caller is responsible for managing the session lifecycle
        return self.db.get_session().__enter__()

    def _cleanup_stale_workers(self) -> None:
        """Remove workers that haven't checked in recently.

        Must be called with lock held.
        """
        current_time = time.time()
        stale_workers = []

        for worker_id, state in self.worker_domains.items():
            last_seen = state.get("last_seen", 0)
            if current_time - last_seen > WORKER_TIMEOUT_SECONDS:
                stale_workers.append(worker_id)

        for worker_id in stale_workers:
            logger.info(f"Removing stale worker: {worker_id}")
            del self.worker_domains[worker_id]

    def _get_available_domains(self, session) -> list[dict[str, Any]]:
        """Query database for domains with available candidate links.

        Args:
            session: SQLAlchemy session

        Returns:
            List of dicts with keys: source, canonical_name, article_count
        """
        query = text(
            """
            SELECT 
                cl.source,
                s.canonical_name,
                COUNT(*) as article_count
            FROM candidate_links cl
            LEFT JOIN sources s ON cl.source_id = s.id
            WHERE cl.status = 'article'
            AND cl.id NOT IN (
                SELECT candidate_link_id FROM articles
                WHERE candidate_link_id IS NOT NULL
            )
            GROUP BY cl.source, s.canonical_name
            HAVING COUNT(*) > 0
            ORDER BY COUNT(*) DESC
        """
        )

        result = session.execute(query)
        domains = []
        for row in result:
            domains.append(
                {
                    "source": row[0],
                    "canonical_name": row[1] if row[1] else row[0],
                    "article_count": int(row[2]),
                }
            )
        return domains

    def _is_domain_available(self, domain: str) -> bool:
        """Check if domain is available for processing.

        Args:
            domain: Domain to check

        Returns:
            True if domain can be processed now
        """
        current_time = time.time()

        # Check if domain is paused
        if domain in self.paused_domains:
            if current_time < self.paused_domains[domain]:
                return False
            else:
                # Pause expired, remove it
                del self.paused_domains[domain]
                # Reset failure count
                if domain in self.domain_failure_counts:
                    self.domain_failure_counts[domain] = 0

        # Check if domain is on cooldown
        if domain in self.domain_cooldowns:
            if current_time < self.domain_cooldowns[domain]:
                return False

        return True

    def _assign_domains_to_worker(
        self, worker_id: str, available_domains: list[dict[str, Any]]
    ) -> set[str]:
        """Assign domains to a worker, preferring existing assignments.

        Args:
            worker_id: Worker identifier
            available_domains: List of domains with available work

        Returns:
            Set of domain names assigned to worker
        """
        # Get current worker domains (sticky assignment)
        if worker_id in self.worker_domains:
            current_domains = self.worker_domains[worker_id]["domains"]
        else:
            current_domains = set()

        # Filter to available domains that still have work
        available_domain_names = {d["source"] for d in available_domains}
        valid_current_domains = current_domains & available_domain_names

        # Filter out domains assigned to other workers or unavailable
        assigned_to_others = set()
        for other_worker_id, state in self.worker_domains.items():
            if other_worker_id != worker_id:
                assigned_to_others.update(state["domains"])

        # Start with valid current domains that aren't assigned elsewhere
        assigned_domains = valid_current_domains - assigned_to_others

        # Filter by availability (cooldown, paused)
        assigned_domains = {d for d in assigned_domains if self._is_domain_available(d)}

        # If we need more domains, add unassigned ones
        if len(assigned_domains) < MIN_DOMAINS_PER_WORKER:
            unassigned_domains = [
                d["source"]
                for d in available_domains
                if d["source"] not in assigned_to_others
                and d["source"] not in assigned_domains
                and self._is_domain_available(d["source"])
            ]

            # Add domains up to MAX_DOMAINS_PER_WORKER
            for domain in unassigned_domains:
                if len(assigned_domains) >= MAX_DOMAINS_PER_WORKER:
                    break
                assigned_domains.add(domain)

        return assigned_domains

    def request_work(
        self, worker_id: str, batch_size: int, max_articles_per_domain: int
    ) -> WorkResponse:
        """Handle work request from a worker.

        Args:
            worker_id: Unique worker identifier
            batch_size: Number of articles requested
            max_articles_per_domain: Max articles per domain in batch

        Returns:
            WorkResponse with items and worker_domains
        """
        with self.lock:
            self._cleanup_stale_workers()

            # Use test session if provided, otherwise create new one
            if self._test_session is not None:
                return self._request_work_with_session(
                    self._test_session, worker_id, batch_size, max_articles_per_domain
                )
            else:
                with self.db.get_session() as session:
                    return self._request_work_with_session(
                        session, worker_id, batch_size, max_articles_per_domain
                    )

    def _request_work_with_session(
        self, session, worker_id: str, batch_size: int, max_articles_per_domain: int
    ) -> WorkResponse:
        """Internal method to handle work request with a given session."""
        # Get available domains from database
        available_domains = self._get_available_domains(session)

        if not available_domains:
            logger.warning("No domains with available work")
            return WorkResponse(items=[], worker_domains=[])

        # Assign domains to worker
        assigned_domains = self._assign_domains_to_worker(worker_id, available_domains)

        if not assigned_domains:
            logger.warning(
                f"No available domains for worker {worker_id} "
                "(all on cooldown or assigned to others)"
            )
            return WorkResponse(items=[], worker_domains=[])

        # Update worker state
        self.worker_domains[worker_id] = {
            "domains": assigned_domains,
            "last_seen": time.time(),
        }

        logger.info(
            f"Worker {worker_id} assigned {len(assigned_domains)} domains: "
            f"{sorted(assigned_domains)}"
        )

        # Query candidate_links for assigned domains
        # Use FOR UPDATE SKIP LOCKED for parallel processing safety
        query = text(
            """
            SELECT cl.id, cl.url, cl.source, s.canonical_name
            FROM candidate_links cl
            LEFT JOIN sources s ON cl.source_id = s.id
            WHERE cl.status = 'article'
            AND cl.source = ANY(:domains)
            AND cl.id NOT IN (
                SELECT candidate_link_id FROM articles
                WHERE candidate_link_id IS NOT NULL
            )
            ORDER BY cl.source, RANDOM()
            LIMIT :limit
            FOR UPDATE OF cl SKIP LOCKED
        """
        )

        # Build result with max_articles_per_domain limit
        items = []
        domain_counts = defaultdict(int)

        result = session.execute(
            query, {"domains": list(assigned_domains), "limit": batch_size * 2}
        )

        for row in result:
            domain = row[2]
            if domain_counts[domain] >= max_articles_per_domain:
                continue
            if len(items) >= batch_size:
                break

            items.append(
                WorkItem(
                    id=row[0],
                    url=row[1],
                    source=row[2],
                    canonical_name=row[3] if row[3] else row[2],
                )
            )
            domain_counts[domain] += 1

        # Update domain cooldowns for domains we're returning work from
        current_time = time.time()
        for domain in domain_counts.keys():
            self.domain_cooldowns[domain] = current_time + DOMAIN_COOLDOWN_SECONDS

        logger.info(
            f"Worker {worker_id} received {len(items)} items from "
            f"{len(domain_counts)} domains: {dict(domain_counts)}"
        )

        return WorkResponse(items=items, worker_domains=sorted(assigned_domains))

    def update_worker_heartbeat(self, worker_id: str) -> None:
        """Update worker last_seen timestamp.

        Args:
            worker_id: Worker sending heartbeat
        """
        with self.lock:
            if worker_id in self.worker_domains:
                self.worker_domains[worker_id]["last_seen"] = time.time()
                logger.debug(f"Heartbeat received from worker {worker_id}")

    def report_failure(self, worker_id: str, domain: str) -> None:
        """Report a domain failure (rate limit, bot protection, etc.).

        Args:
            worker_id: Worker reporting the failure
            domain: Domain that failed
        """
        with self.lock:
            # Increment failure count
            self.domain_failure_counts[domain] = (
                self.domain_failure_counts.get(domain, 0) + 1
            )
            failure_count = self.domain_failure_counts[domain]

            logger.info(
                f"Worker {worker_id} reported failure for {domain} "
                f"(count: {failure_count}/{MAX_DOMAIN_FAILURES})"
            )

            # Progressive cooldown: 60s, 120s, then pause for 30 minutes
            if failure_count >= MAX_DOMAIN_FAILURES:
                pause_until = time.time() + DOMAIN_PAUSE_SECONDS
                self.paused_domains[domain] = pause_until
                logger.warning(
                    f"Domain {domain} paused until "
                    f"{datetime.fromtimestamp(pause_until).isoformat()} "
                    f"after {failure_count} failures"
                )
            else:
                # Exponential backoff for cooldown
                extended_cooldown = DOMAIN_COOLDOWN_SECONDS * (2 ** (failure_count - 1))
                self.domain_cooldowns[domain] = time.time() + extended_cooldown
                logger.info(
                    f"Domain {domain} cooldown extended to {extended_cooldown}s"
                )

    def get_stats(self) -> StatsResponse:
        """Get current queue statistics.

        Returns:
            StatsResponse with current state
        """
        with self.lock:
            session = self._get_session()
            # Get total available articles
            available_query = text(
                """
                SELECT COUNT(*) FROM candidate_links
                WHERE status = 'article'
                AND id NOT IN (
                    SELECT candidate_link_id FROM articles
                    WHERE candidate_link_id IS NOT NULL
                )
            """
            )
            total_available = session.execute(available_query).scalar()

            # Get paused articles (approximate - we don't have a paused status)
            # This would need to be tracked separately in production
            total_paused = 0

            # Get unique domains
            domain_query = text(
                """
                SELECT COUNT(DISTINCT source) FROM candidate_links
                WHERE status = 'article'
                AND id NOT IN (
                    SELECT candidate_link_id FROM articles
                    WHERE candidate_link_id IS NOT NULL
                )
            """
            )
            domains_available = session.execute(domain_query).scalar()

            # Calculate domains with active cooldowns
            current_time = time.time()
            active_cooldowns = {
                domain: cooldown_time - current_time
                for domain, cooldown_time in self.domain_cooldowns.items()
                if cooldown_time > current_time
            }

            # Get worker assignments
            worker_assignments = {
                worker_id: sorted(state["domains"])
                for worker_id, state in self.worker_domains.items()
            }

            return StatsResponse(
                total_available=int(total_available) if total_available else 0,
                total_paused=total_paused,
                domains_available=int(domains_available) if domains_available else 0,
                domains_paused=len(self.paused_domains),
                worker_assignments=worker_assignments,
                domain_cooldowns=active_cooldowns,
            )


# Global coordinator instance
coordinator = WorkQueueCoordinator()


@app.post("/work/request", response_model=WorkResponse)
async def request_work(request: WorkRequest) -> WorkResponse:
    """Request work items from the queue.

    Args:
        request: WorkRequest with worker_id, batch_size, max_articles_per_domain

    Returns:
        WorkResponse with items and worker_domains
    """
    try:
        return coordinator.request_work(
            request.worker_id, request.batch_size, request.max_articles_per_domain
        )
    except Exception as e:
        logger.error(f"Error processing work request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/work/heartbeat")
async def worker_heartbeat(worker_id: str) -> dict[str, str]:
    """Update worker last_seen timestamp to prevent timeout.

    Args:
        worker_id: Worker sending heartbeat

    Returns:
        Success message
    """
    try:
        coordinator.update_worker_heartbeat(worker_id)
        return {
            "status": "success",
            "message": f"Heartbeat received for {worker_id}",
        }
    except Exception as e:
        logger.error(f"Error processing heartbeat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/work/report-failure")
async def report_failure(worker_id: str, domain: str) -> dict[str, str]:
    """Report a domain failure.

    Args:
        worker_id: Worker reporting the failure
        domain: Domain that failed

    Returns:
        Success message
    """
    try:
        coordinator.report_failure(worker_id, domain)
        return {"status": "success", "message": f"Failure reported for {domain}"}
    except Exception as e:
        logger.error(f"Error reporting failure: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    """Get queue statistics.

    Returns:
        StatsResponse with current state
    """
    try:
        return coordinator.get_stats()
    except Exception as e:
        logger.error(f"Error getting stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint.

    Returns:
        HealthResponse indicating service status
    """
    return HealthResponse(status="healthy", service="work-queue")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
