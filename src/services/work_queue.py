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

import asyncio
import logging
import os
import time
from collections import defaultdict
from datetime import datetime
from functools import partial
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
# One domain per request for better distribution and bot avoidance
MIN_DOMAINS_PER_WORKER = int(os.getenv("MIN_DOMAINS_PER_WORKER", "1"))
MAX_DOMAINS_PER_WORKER = int(os.getenv("MAX_DOMAINS_PER_WORKER", "1"))
# Max 3 articles per domain per request (below bot thresholds)
MAX_ARTICLES_PER_DOMAIN_PER_REQUEST = int(
    os.getenv("MAX_ARTICLES_PER_DOMAIN_PER_REQUEST", "3")
)

# FastAPI app
app = FastAPI(title="Work Queue Service", version="1.0.0")


#: Restricts every selection to records a review decision rewound.
#:
#: The housekeeping workflow is the pipeline workflow -- the same parallel
#: workers pulling from this queue -- and the ONLY difference is the set of
#: records that goes in. This is that difference, as one clause: a
#: candidate link is served only if `pipeline_rework` still owes work on
#: it. Without it a housekeeping worker draws from the whole extraction
#: backlog, which on 2026-09-12 was 4,802 links against 45 a reviewer had
#: actually rewound.
#:
#: The status filter is already in both queries (`cl.status = 'article'`
#: and no article row). A stage selects on the join of the two: the status
#: says which stage a record is ready for, and this says whether anybody
#: asked for it.
#: A link owes a fetch when it is queued for a first one, or rewound for
#: another. `refetch` is the rewind `src.pipeline.refetch` writes when a stored
#: body is a paywall teaser rather than the story: the article keeps its id, its
#: CIN labels and its history while its body is replaced.
#:
#: The direct-DB extraction path has honoured `refetch` since it was built. The
#: queue did not, in any of its five queries, so a rewound link was invisible to
#: every worker and "re-extract through the queue" was impossible for any host.
#: Putting the link in `pipeline_rework` does not help: `REWORK_ONLY` is ANDed
#: onto this clause, so it narrows what is offered and cannot widen it.
CLAIMABLE_STATUSES = "cl.status IN ('article', 'refetch')"

#: An existing article disqualifies a link -- except a rewound one, where
#: replacing that article's body is the whole point. `ARTICLE_INSERT_SQL` ends
#: `ON CONFLICT DO NOTHING`, so serving a rewind without this would fetch the
#: page, pay for the request and discard the body. It would look like it worked.
NOT_ALREADY_FETCHED = (
    "            AND (cl.status = 'refetch' OR NOT EXISTS (\n"
    "                SELECT 1 FROM articles a\n"
    "                WHERE a.candidate_link_id = cl.id\n"
    "            ))"
)

REWORK_ONLY = (
    " AND EXISTS (SELECT 1 FROM pipeline_rework r "
    "             WHERE r.record_id = cl.id AND r.done_at IS NULL)"
)


class WorkRequest(BaseModel):
    """Request for work items from a worker."""

    worker_id: str = Field(..., description="Unique identifier for the worker")
    batch_size: int = Field(
        50, ge=1, le=500, description="Number of articles requested"
    )
    max_articles_per_domain: int = Field(
        3, ge=1, le=20, description="Maximum articles per domain in this batch"
    )
    rework: bool = Field(
        False,
        description=(
            "Serve only records a review decision rewound (pipeline_rework). "
            "The housekeeping workflow sets this; the pipeline does not."
        ),
    )
    dataset: Optional[str] = Field(
        None,
        description=(
            "Restrict work to one dataset (candidate_links.dataset_id). "
            "Omit to draw from every dataset, which is the historical behaviour."
        ),
    )
    requires_login: Optional[bool] = Field(
        None,
        description=(
            "Serve only credentialed hosts (True) or only anonymous ones "
            "(False). Omit to mix, which is the historical behaviour.\n\n"
            "A credentialed host wants a worker of its own, because the "
            "Selenium driver is shared and its authenticated sessions are "
            "dropped every time it is recycled. A worker that fetches both "
            "kinds must either recycle on the ordinary schedule -- paying a "
            "fresh login on each credentialed host's next turn -- or hold the "
            "driver longer and deny the anonymous hosts the rotation that "
            "limit exists to give them. Segregating them lets each kind keep "
            "the setting it needs while both still rotate BETWEEN domains of "
            "their own kind, which is what the cooldowns are for.\n\n"
            "See docs/AN_AUTHENTICATED_WORKER_IS_PROVISIONED.md: this field is "
            "only half the answer, because a credentialed domain offered to "
            "whichever worker asks first is not segregated at all."
        ),
    )


class WorkItem(BaseModel):
    """A single work item (candidate link) to process."""

    id: str
    url: str
    source: str
    canonical_name: Optional[str] = None
    #: `candidate_links.status` -- `article` for a first fetch, `refetch` for a
    #: rewind. The worker MUST know which: a rewind's article already exists, so
    #: the body is written with `ARTICLE_REFETCH_SQL`, while the ordinary insert
    #: ends `ON CONFLICT DO NOTHING` and would discard it. The worker used to
    #: hardcode "article" for every queue item, so a rewind served through the
    #: queue would have been fetched -- spending a request on a paywalled
    #: publisher we hold a subscription to -- and silently thrown away.
    #:
    #: Defaults to `article` so a worker talking to an older queue behaves as it
    #: did rather than crashing on a missing field.
    status: str = "article"


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

    # Credentialed work, reported separately because segregating the pools
    # creates a way for it to be owed and claimed by nobody.
    #
    # A credentialed domain is invisible to an anonymous worker
    # (`requires_login = false`) and to every worker if none asks for the
    # authenticated pool. Nothing errors: the run finishes, the backlog does
    # not move, and "no work for me" reads exactly like "no work at all".
    #: Links at `article` on a host that needs a login, whatever its state.
    credentialed_available: int = 0
    #: Of those, the ones an authenticated worker could actually be served --
    #: active source, `auth_type` and `auth_secret_name` both present.
    credentialed_claimable: int = 0
    #: host -> why the rest cannot be claimed, so a stalled backlog names
    #: itself instead of being inferred from a count that never moves.
    credentialed_unclaimable: dict[str, str] = {}
    #: pool -> seconds since a worker last asked for it. A missing
    #: "authenticated" key with `credentialed_claimable` above zero is the
    #: starvation case: work is ready and nobody has come for it.
    pool_last_request_age: dict[str, float] = {}


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str


class WorkQueueCoordinator:
    """Coordinates work distribution with domain-aware rate limiting."""

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

        # Which pools workers have asked for: "authenticated"/"anonymous"/
        # "mixed" -> last ask (float, epoch seconds).
        #
        # Recorded because "no work for me" and "no work at all" look identical
        # to a worker, and an anonymous-only pipeline excludes credentialed
        # domains from every pool it runs. Without this the outcome is a
        # paywalled backlog that never moves while every run reports success,
        # and the only way to notice is a count somebody happens to re-run.
        self.pool_requests: dict[str, float] = {}

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

    def _get_available_domains(
        self,
        session,
        dataset: Optional[str] = None,
        rework: bool = False,
        requires_login: Optional[bool] = None,
    ) -> list[dict[str, Any]]:
        """Query database for domains with available candidate links.

        Args:
            session: SQLAlchemy session
            dataset: When given, only domains with work in this dataset are
                offered. Filtering HERE is what makes the scoping effective:
                _assign_domains_to_worker picks from whatever this returns, so
                an out-of-dataset domain is never handed to a worker at all.

        Returns:
            List of dicts with keys: source, canonical_name, article_count
        """
        # The dataset filter is APPENDED, not parameterised into a
        # constant string, and that is deliberate on two counts.
        #
        # It used to read `AND (:dataset IS NULL OR cl.dataset_id =
        # :dataset)`. Postgres could not plan that at all: `:dataset IS
        # NULL` gives it nothing to infer a type from and pg8000 -- unlike
        # psycopg2 -- sends none, so every call raised 42P18 and
        # /work/request answered 500 to every worker from the day #455
        # shipped it.
        #
        # Casting both sides fixes Postgres and breaks SQLite, where each
        # occurrence of a named parameter becomes its own positional
        # placeholder and the repeated `:dataset` no longer matches its
        # bindings. Mentioning the parameter ONCE, and only when there is
        # a value for it, is correct on both.
        sql = f"""
            SELECT
                cl.source,
                s.canonical_name,
                COUNT(*) as article_count
            FROM candidate_links cl
            JOIN sources s ON cl.source_id = s.id
            WHERE {CLAIMABLE_STATUSES}
            AND s.status = 'active'
{NOT_ALREADY_FETCHED}
        """
        params: dict = {}
        if dataset is not None:
            sql += "            AND cl.dataset_id = :dataset\n"
            params["dataset"] = dataset
        if requires_login is not None:
            # Appended rather than parameterised as
            # `(:requires_login IS NULL OR ...)`, for the reason the dataset
            # filter above is: Postgres could not plan the untyped form.
            sql += "            AND s.requires_login = :requires_login\n"
            params["requires_login"] = requires_login
        if requires_login:
            # Whether a host NEEDS a login and whether we can perform one are
            # different questions, and only the first is `requires_login`.
            # Without this an authenticated worker is handed a host it cannot
            # sign in to, fetches it anonymously, and stores whatever the
            # paywall serves -- which is the failure the pool exists to avoid,
            # arriving as content rather than as an error.
            #
            # Such a host belongs in NEITHER pool: the anonymous worker
            # excludes it on `requires_login = false`. That is a hole, not a
            # resolution, so `/stats` reports it by name under
            # `credentialed_unclaimable` -- see `get_stats`.
            sql += "            AND s.auth_type IS NOT NULL\n"
            sql += "            AND s.auth_secret_name IS NOT NULL\n"
        if rework:
            # Offered domains have to be rework domains too. Filtering only
            # the claim query would hand a worker a domain whose links are
            # all backlog, and it would come back with nothing while the
            # rework links sat behind a domain nobody was assigned.
            sql += REWORK_ONLY + "\n"
        sql += """
            GROUP BY cl.source, s.canonical_name
            HAVING COUNT(*) > 0
            ORDER BY COUNT(*) DESC
        """
        query = text(sql)

        result = session.execute(query, params)
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
        """Assign exactly one domain to a worker, randomized selection.

        Provides single domain per request to avoid back-to-back extractions
        and stay below bot detection thresholds.

        Args:
            worker_id: Worker identifier
            available_domains: List of domains with available work

        Returns:
            Set with single domain name (or empty if none available)
        """
        # Filter out domains assigned to other active workers
        assigned_to_others = set()
        for other_worker_id, state in self.worker_domains.items():
            if other_worker_id != worker_id:
                assigned_to_others.update(state["domains"])

        # Get unassigned domains that are available (not paused/cooldown)
        unassigned_domains = [
            d["source"]
            for d in available_domains
            if d["source"] not in assigned_to_others
            and self._is_domain_available(d["source"])
        ]

        if not unassigned_domains:
            return set()

        # Randomize domain selection to avoid back-to-back extractions
        import random

        selected_domain = random.choice(unassigned_domains)
        return {selected_domain}

    def request_work(
        self,
        worker_id: str,
        batch_size: int,
        max_articles_per_domain: int,
        dataset: Optional[str] = None,
        rework: bool = False,
        requires_login: Optional[bool] = None,
    ) -> WorkResponse:
        """Handle work request from a worker.

        Args:
            worker_id: Unique worker identifier
            batch_size: Number of articles requested
            max_articles_per_domain: Max articles per domain in batch
            dataset: Restrict work to one dataset id; None draws from all.
            requires_login: Serve only credentialed hosts (True) or only
                anonymous ones (False). None mixes them, which is what every
                caller got before authenticated workers existed.

        Returns:
            WorkResponse with items and worker_domains
        """
        with self.lock:
            self._cleanup_stale_workers()

            # Use test session if provided, otherwise create new one
            if self._test_session is not None:
                return self._request_work_with_session(
                    self._test_session,
                    worker_id,
                    batch_size,
                    max_articles_per_domain,
                    dataset,
                    rework,
                    requires_login,
                )
            else:
                with self.db.get_session() as session:
                    return self._request_work_with_session(
                        session,
                        worker_id,
                        batch_size,
                        max_articles_per_domain,
                        dataset,
                        rework,
                        requires_login,
                    )

    def _request_work_with_session(
        self,
        session,
        worker_id: str,
        batch_size: int,
        max_articles_per_domain: int,
        dataset: Optional[str] = None,
        rework: bool = False,
        requires_login: Optional[bool] = None,
    ) -> WorkResponse:
        """Internal method to handle work request with a given session."""
        pool = (
            "mixed"
            if requires_login is None
            else ("authenticated" if requires_login else "anonymous")
        )
        self.pool_requests[pool] = time.time()

        # Get available domains from database
        available_domains = self._get_available_domains(
            session, dataset, rework, requires_login
        )

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

        # Query candidate_links for assigned domain
        # Single domain with max 3 articles (below bot thresholds)
        # Use FOR UPDATE SKIP LOCKED for parallel processing safety
        # LEFT JOIN more efficient than NOT IN for large articles table
        # The dataset clause is appended only when there is a dataset, for
        # the reason spelled out on _get_available_domains: `:dataset IS NULL`
        # gives Postgres nothing to infer a type from, pg8000 sends none, and
        # the statement fails 42P18 before it runs. #533 repaired the domain
        # query and left this one, so /work/request kept answering 500 -- the
        # same fault, one query further down, and the reason the March
        # extraction run died after 302 of 424 articles.
        dataset_clause = " AND cl.dataset_id = :dataset" if dataset else ""
        rework_clause = REWORK_ONLY if rework else ""
        query = text(f"""
            SELECT cl.id, cl.url, cl.source, s.canonical_name, cl.status
            FROM candidate_links cl
            LEFT JOIN sources s ON cl.source_id = s.id
            LEFT JOIN articles a ON cl.id = a.candidate_link_id
            WHERE {CLAIMABLE_STATUSES}
            AND cl.source = ANY(:domains){dataset_clause}{rework_clause}
            AND (cl.status = 'refetch' OR a.candidate_link_id IS NULL)
            ORDER BY RANDOM()
            LIMIT :limit
            FOR UPDATE OF cl SKIP LOCKED
        """)

        # Enforce max 3 articles per domain
        max_articles = min(
            MAX_ARTICLES_PER_DOMAIN_PER_REQUEST,
            max_articles_per_domain,
            batch_size,
        )

        result = session.execute(
            query,
            {
                "domains": list(assigned_domains),
                "limit": max_articles,
                # Mentioned once, and only when the clause above uses it.
                **({"dataset": dataset} if dataset else {}),
            },
        )

        items = [
            WorkItem(
                id=row[0],
                url=row[1],
                source=row[2],
                canonical_name=row[3] if row[3] else row[2],
                status=row[4],
            )
            for row in result
        ]
        domain_counts = defaultdict(int)
        for item in items:
            domain_counts[item.source] += 1

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

        If worker is unknown (e.g., after work-queue restart), re-register it
        with empty domain set. This prevents workers from being marked stale
        when work-queue loses state.

        Args:
            worker_id: Worker sending heartbeat
        """
        with self.lock:
            if worker_id in self.worker_domains:
                self.worker_domains[worker_id]["last_seen"] = time.time()
                logger.debug(f"Heartbeat received from worker {worker_id}")
            else:
                # Re-register unknown worker (survives work-queue restart)
                self.worker_domains[worker_id] = {
                    "domains": set(),
                    "last_seen": time.time(),
                }
                logger.info(f"Re-registered unknown worker {worker_id} via heartbeat")

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
                SELECT COUNT(*) FROM candidate_links cl
                WHERE """
                + CLAIMABLE_STATUSES
                + """
                AND (cl.status = 'refetch' OR NOT EXISTS (
                    SELECT 1 FROM articles a
                    WHERE a.candidate_link_id = cl.id
                ))
            """
            )
            total_available = session.execute(available_query).scalar()

            # Get paused articles (approximate - we don't have a paused status)
            # This would need to be tracked separately in production
            total_paused = 0

            # Get unique domains
            domain_query = text(
                """
                SELECT COUNT(DISTINCT source) FROM candidate_links cl
                WHERE """
                + CLAIMABLE_STATUSES
                + """
                AND (cl.status = 'refetch' OR NOT EXISTS (
                    SELECT 1 FROM articles a
                    WHERE a.candidate_link_id = cl.id
                ))
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

            # Credentialed work: what is owed, what an authenticated worker
            # could be served, and why the remainder cannot be.
            #
            # Grouped per host rather than counted in total because the reasons
            # are per host and each has a different remedy: a paused source is
            # waiting on a monitored first run, a source with no
            # `auth_secret_name` is waiting on credentials that may not exist.
            credentialed_rows = session.execute(
                text(
                    """
                    SELECT s.host_norm,
                           s.status,
                           s.auth_type IS NOT NULL
                             AND s.auth_secret_name IS NOT NULL AS has_credentials,
                           s.auth_last_failed_at IS NOT NULL AS needs_revalidation,
                           COUNT(*) AS owed
                    FROM candidate_links cl
                    JOIN sources s ON cl.source_id = s.id
                    WHERE """
                    + CLAIMABLE_STATUSES
                    + """
                    AND s.requires_login
                    AND (cl.status = 'refetch' OR NOT EXISTS (
                        SELECT 1 FROM articles a
                        WHERE a.candidate_link_id = cl.id
                    ))
                    GROUP BY s.host_norm, s.status, has_credentials,
                             needs_revalidation
                """
                )
            ).fetchall()

            credentialed_available = 0
            credentialed_claimable = 0
            credentialed_unclaimable: dict[str, str] = {}
            for row in credentialed_rows:
                host, source_status, has_credentials, needs_revalidation, owed = row
                owed = int(owed or 0)
                credentialed_available += owed
                if needs_revalidation:
                    # A run refused this host because its login did not
                    # confirm. Its links are not claimable until a person
                    # re-validates (`validate-login --record`), and saying so
                    # here is the difference between a known gap and
                    # yakimaherald's two silent months.
                    credentialed_unclaimable[str(host)] = (
                        f"{owed} owed; login failed on a recent run -- "
                        "needs re-validation"
                    )
                elif not has_credentials:
                    credentialed_unclaimable[str(host)] = (
                        f"{owed} owed; no auth_type/auth_secret_name -- "
                        "in neither pool"
                    )
                elif source_status != "active":
                    credentialed_unclaimable[str(host)] = (
                        f"{owed} owed; source is {source_status}"
                    )
                else:
                    credentialed_claimable += owed

            pool_last_request_age = {
                pool: current_time - asked_at
                for pool, asked_at in self.pool_requests.items()
            }
            if credentialed_claimable and "authenticated" not in self.pool_requests:
                logger.warning(
                    "%d credentialed links are claimable and no worker has "
                    "asked for the authenticated pool",
                    credentialed_claimable,
                )

            return StatsResponse(
                total_available=int(total_available) if total_available else 0,
                total_paused=total_paused,
                domains_available=int(domains_available) if domains_available else 0,
                domains_paused=len(self.paused_domains),
                credentialed_available=credentialed_available,
                credentialed_claimable=credentialed_claimable,
                credentialed_unclaimable=credentialed_unclaimable,
                pool_last_request_age=pool_last_request_age,
                worker_assignments=worker_assignments,
                domain_cooldowns=active_cooldowns,
            )


# The process's coordinator, built when something first asks for it.
#
# This used to be `coordinator = WorkQueueCoordinator()` at module
# scope, which meant importing this module opened a database connection
# and ran `Base.metadata.create_all` (src/models/database.py). Any
# importer paid for that, including pytest: collecting a test module
# that imports this one created tables in whatever database the
# environment happened to name.
#
# It also made failures point at the wrong place. A stale, unwritable
# SQLite file in the temp directory surfaced as
#
#     ERROR collecting tests/integration/test_work_queue_integration.py
#     sqlite3.OperationalError: attempt to write a readonly database
#
# against a test that was deselected and never ran. It was simply the
# first module to import this one, so it wore an error it had no part
# in.
#
# Built on first use, the connection happens when the service serves,
# and importing this module does nothing but define things.
_coordinator: Optional["WorkQueueCoordinator"] = None
_coordinator_lock = Lock()


def get_coordinator() -> "WorkQueueCoordinator":
    """The coordinator this process serves from, made once.

    Double-checked under a lock: the routes hand their work to a thread
    pool, so two requests arriving together would otherwise build two
    coordinators and two connection pools.
    """
    global _coordinator
    if _coordinator is None:
        with _coordinator_lock:
            if _coordinator is None:
                _coordinator = WorkQueueCoordinator()
    return _coordinator


@app.post("/work/request", response_model=WorkResponse)
async def request_work(request: WorkRequest) -> WorkResponse:
    """Request work items from the queue.

    Args:
        request: WorkRequest with worker_id, batch_size, max_articles_per_domain

    Returns:
        WorkResponse with items and worker_domains
    """
    try:
        # Run blocking coordinator method in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            partial(
                get_coordinator().request_work,
                request.worker_id,
                request.batch_size,
                request.max_articles_per_domain,
                request.dataset,
                request.rework,
                request.requires_login,
            ),
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
        # Run in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, get_coordinator().update_worker_heartbeat, worker_id
        )
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
        # Run in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, partial(get_coordinator().report_failure, worker_id, domain)
        )
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
        # Run in thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, get_coordinator().get_stats)
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
