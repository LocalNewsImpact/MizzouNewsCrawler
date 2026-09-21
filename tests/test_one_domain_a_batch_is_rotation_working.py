"""One domain in a batch is rotation working, not a single-domain dataset.

The work queue hands each worker exactly ONE domain per request and at most three
articles from it, then rotates. That is its entire design -- it is how a publisher
is kept from seeing a hundred consecutive requests, and `_assign_domains_to_worker`
excludes any domain another active worker holds.

So `unique_domains`, the count of distinct domains WITHIN one batch, is always 1
under the queue. The batch-sleep condition read it as proof of a single-domain
dataset:

    is_single_domain_dataset = unique_domains <= 1 and skipped_domains == 0
    needs_long_pause = (
        is_single_domain_dataset
        or same_domain_consecutive >= max_same_domain
        or unique_domains <= 1        # always true
    )

Worse, it OVERWROTE a correct value. `is_single_domain_dataset` is measured once
before the loop from `_analyze_dataset_domains`, which asks the database how many
domains have claimable work; the per-batch line replaced that with the wrong
answer.

Measured on the seven-host WSU rotation, 2026-09-21:

    Batch 1: domains_processed ['www.spokesman.com'], same_domain_consecutive 2
    ⏸️  Single-domain dataset - waiting 420s...

Seven credentialed domains were available. Three articles then 420 seconds is
about 24 an hour against a backlog of 846 -- roughly 35 hours.

The irony is the argument: the long pause exists to protect a single publisher
from a sustained run, which is the condition rotation removes. It throttled
hardest exactly where it was least needed. The logic predates the queue, when a
worker picked its own domains and one domain in a batch really did mean there was
nowhere else to go.

`same_domain_consecutive` is kept, because that IS a real signal: the queue
handing back the same domain repeatedly means rotation is exhausted whatever the
dataset holds.
"""

from __future__ import annotations

import inspect

from src.cli.commands import extraction
from src.utils.worker_pool import ANONYMOUS, AUTHENTICATED, MIXED


def _loop_body() -> str:
    source = inspect.getsource(extraction.handle_extraction_command)
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )


class TestTheBatchCountNoLongerDecides:
    def test_the_flag_is_not_recomputed_from_one_batch(self):
        """The bug, as a shape: a per-batch count assigned to the dataset flag."""
        body = _loop_body()
        assert "is_single_domain_dataset = unique_domains" not in body

    def test_unique_domains_is_not_a_pause_condition(self):
        """`or unique_domains <= 1` was the same mistake restated."""
        body = _loop_body()
        pause = body[body.index("needs_long_pause = (") :]
        pause = pause[: pause.index(")")]
        assert "unique_domains" not in pause

    def test_the_dataset_level_flag_is_what_is_consulted(self):
        body = _loop_body()
        pause = body[body.index("needs_long_pause = (") :]
        pause = pause[: pause.index(")")]
        assert "is_single_domain_dataset" in pause

    def test_it_is_measured_once_before_the_loop(self):
        body = _loop_body()
        measured = body.index(
            'is_single_domain_dataset = domain_analysis.get("is_single_domain"'
        )
        loop = body.index("while True:")
        assert measured < loop

    def test_repeated_same_domain_still_pauses(self):
        """Kept deliberately. The queue returning one domain over and over means
        rotation is exhausted, which is a genuine reason to slow down."""
        body = _loop_body()
        pause = body[body.index("needs_long_pause = (") :]
        pause = pause[: pause.index(")")]
        assert "same_domain_consecutive >= max_same_domain" in pause


class TestTheDomainCountIsPoolScoped:
    def test_the_query_filters_on_requires_login(self):
        """An authenticated worker must count only the hosts it can be handed.

        Counting the dataset's anonymous domains would tell it rotation is
        available when it is not, and it would then hammer the one credentialed
        host it can reach -- the precise failure the long pause exists to prevent.
        """
        source = inspect.getsource(extraction._analyze_dataset_domains)
        assert "requires_login" in source
        assert "CAST(:requires_login AS boolean) IS NULL" in source

    def test_the_parameter_comes_from_the_worker_pool(self):
        source = inspect.getsource(extraction._analyze_dataset_domains)
        assert "requires_login_filter(worker_pool())" in source

    def test_null_means_no_filter_rather_than_no_rows(self):
        """A `mixed` worker draws both kinds, so its filter is None.

        Written as `IS NULL OR ...` rather than `= :requires_login`, because a
        NULL equality test matches nothing and a mixed worker would see zero
        domains -- and zero is not one, so it would not even trip the
        single-domain branch. It would look like an empty dataset.
        """
        source = inspect.getsource(extraction._analyze_dataset_domains)
        clause = source[source.index("CAST(:requires_login AS boolean) IS NULL") :]
        clause = clause[: clause.index(")\n")]
        assert "OR" in clause

    def test_a_null_requires_login_source_counts_as_anonymous(self):
        """`sources.requires_login` is nullable, and a NULL is not a login.

        `coalesce(s.requires_login, false)` so an anonymous worker still sees
        those domains; without it they would be invisible to both pools.
        """
        source = inspect.getsource(extraction._analyze_dataset_domains)
        assert "coalesce(s.requires_login, false)" in source

    def test_each_pool_maps_to_the_filter_it_needs(self):
        from src.utils.worker_pool import requires_login_filter

        assert requires_login_filter(AUTHENTICATED) is True
        assert requires_login_filter(ANONYMOUS) is False
        assert requires_login_filter(MIXED) is None


class TestWhatTheRunActuallyDid:
    def test_the_sleep_is_still_reachable_for_a_real_single_domain_dataset(self):
        """The protection is not removed, only stopped from firing on everything.

        A dataset with one claimable domain still gets the long pause, because
        `_analyze_dataset_domains` will say so.
        """
        body = _loop_body()
        assert "needs_long_pause" in body
        assert "BATCH_SLEEP_SECONDS" in body

    def test_the_analysis_still_reports_a_count_and_a_flag(self):
        """Both are used: the count is printed, the flag decides."""
        source = inspect.getsource(extraction._analyze_dataset_domains)
        assert '"unique_domains"' in source
        assert '"is_single_domain"' in source
