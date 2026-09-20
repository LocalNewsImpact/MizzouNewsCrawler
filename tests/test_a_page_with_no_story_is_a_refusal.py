"""A guarded host that answers 200 with no story has refused.

The crawler's bot-protection detector keys on a status code or a challenge
page. Cloudflare's JS Detections does neither: it returns HTTP 200 with a
full-looking page and simply omits the article. On 2026-09-20 that happened to
`myedmondsnews.com` 174 times across three hours — 72-90 KB responses yielding
zero characters, against 388 KB average on the runs that worked — and every one
of the six extraction methods ran, Selenium included. `mcmetadata` could only
say "Content is too short".

To the extraction loop that is the generic "No title extracted" failure, which
costs the domain one of its two allowed failures per batch and is forgotten at
the next batch. So the domain kept being asked, at roughly two requests a
minute for an hour after it had stopped yielding anything, which can only
deepen the vendor's scoring of our two egress IPs.

`sources.bot_protection_type` is what makes the 200 legible. Where it is set,
a 2xx carrying no story is treated the way a 403 and a proxy challenge already
are: skip the domain for the rest of the batch and report it, so the work
queue's own cooldown applies.

The guard is deliberately narrow. On a host with no recorded protection an
empty 200 is just a page that is not an article — a listing, an e-edition, a
PDF — and pausing the whole domain over one of those would cost the publisher
nothing and us a lot.
"""

from __future__ import annotations

import inspect
import re

from src.cli.commands import extraction


def _source_of(func) -> str:
    """The function's code with comment lines removed.

    The prose here explains Cloudflare and 200s at length; an assertion that
    matched the explanation rather than the code would pass with the guard
    deleted.
    """
    return "\n".join(
        line
        for line in inspect.getsource(func).splitlines()
        if not line.strip().startswith("#")
    )


class TestTheHostListIsLoadedOnce:
    def test_the_helper_reads_the_column(self):
        code = _source_of(extraction._hosts_behind_bot_protection)
        assert "bot_protection_type IS NOT NULL" in code

    def test_a_failure_to_read_it_does_not_stop_the_run(self):
        """Extraction matters more than the optimisation."""
        code = _source_of(extraction._hosts_behind_bot_protection)
        assert "except Exception" in code
        assert "return set()" in code

    def test_it_matches_with_and_without_www(self):
        code = _source_of(extraction._hosts_behind_bot_protection)
        # `domain` in the loop is the raw netloc, which keeps `www.`, while
        # `sources.host` may or may not. Both spellings go in the set.
        assert 'startswith("www.")' in code
        assert 'f"www.{h}"' in code

    def test_the_helper_is_called_with_a_session(self):
        batch = _source_of(extraction._process_batch)
        assert "_hosts_behind_bot_protection(session)" in batch

    def test_it_is_read_once_and_only_when_needed(self):
        batch = _source_of(extraction._process_batch)
        # None means "not read yet", so a run where nothing fails never asks,
        # and the second failure in a batch reuses the first read's answer.
        assert "protected_hosts: set[str] | None = None" in batch
        assert "if protected_hosts is None:" in batch

    def test_the_read_does_not_disturb_the_row_query(self):
        """It must not sit beside the row query.

        `tests/test_extraction_command.py` scripts `session.execute.side_effect`
        with a single exception meant for that query. An extra execute there
        consumes it, the intended error never reaches the code under test, and
        three rollback assertions fail.
        """
        batch = _source_of(extraction._process_batch)
        before_loop = batch[: batch.index("for row in rows:")]
        assert "_hosts_behind_bot_protection" not in before_loop


class TestAWithheldPageIsARefusal:
    def test_a_2xx_from_a_guarded_host_skips_the_domain(self):
        code = _source_of(extraction._process_batch)
        assert "withheld_by_guard" in code
        assert "host_is_guarded" in code
        # The two consequences, matching how a 403 is handled.
        block = code[code.index("withheld_by_guard = (") :]
        block = block[: block.index("if is_rate_limit")]
        assert "skipped_domains.add(domain)" in block
        assert "domain_failures[domain] = max_failures_per_domain" in block

    def test_the_status_range_is_the_success_range(self):
        code = _source_of(extraction._process_batch)
        assert re.search(r"200\s*<=\s*int\(http_status\)\s*<\s*300", code)

    def test_it_requires_the_host_to_be_guarded(self):
        """Without this it would pause a healthy domain over one odd page."""
        code = _source_of(extraction._process_batch)
        match = re.search(r"withheld_by_guard = \(\s*host_is_guarded", code, re.S)
        assert match, "the guard must be the first condition, not an afterthought"

    def test_a_missing_status_is_not_treated_as_success(self):
        code = _source_of(extraction._process_batch)
        # `http_status` is None when the fetch never got that far; None is not
        # a refusal, it is a different failure with its own handling.
        assert "http_status is not None" in code

    def test_the_403_path_is_untouched(self):
        code = _source_of(extraction._process_batch)
        assert "is_bot_protection = http_status == 403" in code
        assert "if is_rate_limit or is_bot_protection:" in code


class TestTheQueueStillHearsAboutIt:
    def test_skipped_domains_are_reported_to_the_queue(self):
        code = _source_of(extraction._process_batch)
        # The skip is only half of it: the work queue applies the 30-minute
        # cooldown, and it only learns from this report.
        assert "_report_domain_failure(worker_id, domain)" in code

    def test_the_report_is_gated_on_the_queue_being_in_use(self):
        code = _source_of(extraction._process_batch)
        assert "if USE_WORK_QUEUE:" in code
