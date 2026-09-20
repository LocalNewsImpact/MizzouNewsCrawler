"""A URL somebody handed over has already been judged.

Uploading a set of URLs is an affirmative decision to collect and export those
specific URLs. Selection IS the filter and it ran before the crawler saw the
link, so URL verification and the MediaCloud wire check add nothing — and their
verdicts can only remove records the study was defined to contain. Only a fetch
failure (404 and friends) should drop one.

The flag is per URL RECORD, not per dataset, because a dataset holds both kinds:
WSU-Washington-State has 2,681 ingested links and 6 crawled ones, while
Mizzou-Missouri-State has ~234,800 crawled and ~1,178 ingested. A dataset-level
bypass would be wrong in both directions.

What it cost before: `wire_check_status` is `NOT NULL DEFAULT 'pending'`, and
`pending` is the one value that BLOCKS enrichment (the selector wants
`IN ('complete','local')`). So every ingested article queued for a check it
should never have had and stopped short of the export — 154 WSU rows sat at
`pending` on 2026-09-20 and another 147 had reached `error` on
`api_error:422` from MediaCloud.
"""

from __future__ import annotations

import inspect

from src.cli.commands import extraction
from src.services.url_verification import URLVerificationService


def _code(func) -> str:
    """Source with comment lines stripped.

    The prose in these modules explains curation at length; an assertion that
    matched the explanation would pass with the behaviour removed.
    """
    return "\n".join(
        line
        for line in inspect.getsource(func).splitlines()
        if not line.strip().startswith("#")
    )


class TestTheWireCheckIsAsserted:
    def test_a_curated_article_is_local_not_pending(self):
        got = extraction._initial_wire_check_status("extracted", curated=True)
        assert got == extraction.WIRE_CHECK_STATUS_LOCAL

    def test_local_is_not_complete(self):
        """Bypassing a check is not the same as asserting its happy answer."""
        assert (
            extraction.WIRE_CHECK_STATUS_LOCAL != extraction.WIRE_CHECK_STATUS_COMPLETE
        )

    def test_a_discovered_article_still_gets_checked(self, monkeypatch):
        # Pinned, because `ENABLE_MEDIACLOUD_WIRE_CHECK` differs between a
        # laptop and CI and the answer depends on it: with the check disabled
        # everything is `complete` and this test would pass vacuously.
        monkeypatch.setattr(extraction, "ENABLE_MEDIACLOUD_WIRE_CHECK", True)
        got = extraction._initial_wire_check_status("extracted", curated=False)
        assert got == extraction.WIRE_CHECK_STATUS_PENDING

    def test_curated_is_local_even_with_the_mediacloud_check_disabled(
        self, monkeypatch
    ):
        """`local` and `complete` say different things and must not collapse.

        With the external check off, a discovered article is `complete` -- the
        check is not coming. A curated one is `local`: we asserted the verdict.
        """
        monkeypatch.setattr(extraction, "ENABLE_MEDIACLOUD_WIRE_CHECK", False)
        assert (
            extraction._initial_wire_check_status("extracted", curated=True)
            == extraction.WIRE_CHECK_STATUS_LOCAL
        )
        assert (
            extraction._initial_wire_check_status("extracted", curated=False)
            == extraction.WIRE_CHECK_STATUS_COMPLETE
        )

    def test_curated_wins_over_every_status(self):
        # It short-circuits before the status table, because the point is the
        # URL's provenance rather than what the extractor made of the page.
        for status in ("extracted", "cleaned", "labeled", "wire"):
            assert (
                extraction._initial_wire_check_status(status, curated=True)
                == extraction.WIRE_CHECK_STATUS_LOCAL
            )

    def test_the_default_is_unchanged_for_callers_that_do_not_pass_it(
        self, monkeypatch
    ):
        monkeypatch.setattr(extraction, "ENABLE_MEDIACLOUD_WIRE_CHECK", True)
        assert (
            extraction._initial_wire_check_status("extracted")
            == extraction.WIRE_CHECK_STATUS_PENDING
        )

    def test_the_statuses_that_never_needed_a_check_are_untouched(self):
        for status in ("error", "paywall", "obituary", "opinion", "not_article"):
            assert (
                extraction._initial_wire_check_status(status)
                == extraction.WIRE_CHECK_STATUS_COMPLETE
            )


class TestTheBypassIsAuditable:
    def test_the_authority_is_recorded(self):
        meta = extraction.CURATED_WIRE_METADATA
        assert meta["authority"]
        assert meta["mediacloud_lookup"] is False
        assert meta["bypass_reason"]

    def test_both_insert_sites_write_it(self):
        """A bypass with no trace looks like a check that came back clean."""
        code = _code(extraction._process_batch) + _code(
            extraction.handle_extract_url_command
        )
        assert code.count("CURATED_WIRE_METADATA") == 2
        assert code.count("WIRE_CHECK_STATUS_LOCAL") == 2


class TestTheFlagIsReadPerBatch:
    def test_the_helper_asks_for_the_batch_at_once(self):
        code = _code(extraction._curated_link_ids)
        assert "id = ANY(:ids)" in code
        assert "AND is_curated" in code

    def test_it_fails_open_to_not_curated(self):
        """A discovered row must never skip a check it needs."""
        code = _code(extraction._curated_link_ids)
        assert "except Exception" in code
        assert "return set()" in code

    def test_an_empty_batch_asks_nothing(self):
        assert extraction._curated_link_ids(None, []) == set()
        assert extraction._curated_link_ids(None, [None]) == set()

    def test_the_batch_reads_it_once_and_only_when_needed(self):
        code = _code(extraction._process_batch)
        assert "curated_ids: set[str] | None = None" in code
        assert "if curated_ids is None:" in code
        assert code.count("_curated_link_ids(") == 1

    def test_the_read_does_not_disturb_the_row_query(self):
        """It must not sit beside the row query.

        `tests/test_extraction_command.py` scripts
        `session.execute.side_effect` with a single exception meant for that
        query. An extra execute there consumes it, so the error never reaches
        the code under test and three rollback assertions fail.
        """
        code = _code(extraction._process_batch)
        before_loop = code[: code.index("for row in rows:")]
        assert "_curated_link_ids" not in before_loop


class TestUrlVerificationSkipsThem:
    def test_the_selection_excludes_curated_links(self):
        code = _code(URLVerificationService.get_unverified_urls)
        assert "NOT cl.is_curated" in code

    def test_it_still_scopes_by_dataset(self):
        # The dataset filter went in the day before this; both must hold.
        code = _code(URLVerificationService.get_unverified_urls)
        assert "cl.dataset_id = :dataset_id" in code


class TestTheModelAndMigration:
    def test_the_column_is_a_positive_marker(self):
        from src.models import CandidateLink

        col = CandidateLink.__table__.c.is_curated
        # NOT NULL with a false default: a row always says which it is, rather
        # than a bypass being the absence of a value.
        assert col.nullable is False
        assert col.server_default is not None

    def test_the_migration_backfills_from_provenance(self):
        from pathlib import Path

        path = Path(
            "alembic/versions/d3e4f5a6b7c9_an_ingested_url_says_it_was_curated.py"
        )
        assert path.exists()
        text = path.read_text()
        assert "is_curated" in text
        # `discovery.` is what the crawler writes when it found the link itself.
        assert "discovery." in text
        assert "NOT LIKE" in text
        # A NULL provenance is not a curation claim.
        assert "discovered_by IS NOT NULL" in text
