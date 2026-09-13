"""Enrichment never spends on a kind a reviewer withheld.

`obituary`, `opinion`, `weather` and `column` are terminal once
identified: the corpus keeps them and never spends CIN coding or model
budget on them. `wire`, `other` and `non_english` should never have been
fetched at all.

The article's STATUS is supposed to carry that, and the console's
reconciler writes it -- but only on its next nightly run. Between the
verdict and that run the article sits at `labeled`, which is exactly what
enrichment selects. 21 columns and 17 obituaries were enriched that way,
and four more obituaries went through on 2026-09-13 while this was being
investigated; 89 articles had to be corrected and 79 enrichment rows
deleted afterwards.

So the refusal is here, at the moment the money is spent, reading the
reviewer's verdict rather than trusting a status somebody else is
responsible for writing.
"""

import inspect

from src.enrichment import repository


def test_every_withheld_kind_comes_from_the_contract():
    """Restating the list here is how it drifts: a kind added to the
    contract must take effect without anybody editing a second copy."""
    from lnic_contracts import discovery_verdict

    withheld = set(repository.withheld_kinds())
    assert withheld == set(discovery_verdict.UNENRICHED_TYPES) | set(
        discovery_verdict.UNFETCHED_TYPES
    )
    for kind in ("obituary", "opinion", "weather", "column", "wire"):
        assert kind in withheld, kind


def test_the_scheduled_run_refuses_them():
    assert "withheld_kinds" in str(repository._CANDIDATE_SQL)
    assert "review_verdict" in str(repository._CANDIDATE_SQL)


def test_a_reprocess_refuses_them():
    """A rewind is a reason to re-answer a question, not to overrule the
    reviewer who said it should not be asked."""
    assert "withheld_kinds" in str(repository._REPROCESS_SQL)


def test_the_backfill_refuses_them_by_name():
    """The one path that takes an explicit id list -- the only place a
    person can hand enrichment an article directly. An id list is not a
    reason to overrule a verdict."""
    source = inspect.getsource(repository.select_by_ids)
    assert "reviewed_kind" in source
    assert "withheld_kinds()" in source
    assert "never enriched" in source


def test_every_selection_path_is_gated():
    """Three ways in. A gate on two of them is a gate on none."""
    source = inspect.getsource(repository)
    paths = [
        "_CANDIDATE_SQL = text(",
        "_REPROCESS_SQL = text(",
        "def select_by_ids(",
    ]
    for path in paths:
        assert path in source, path
    assert (
        source.count("WITHHELD_BY_A_REVIEWER") >= 3
    ), "defined once and used by both queries"
    assert source.count("withheld_kinds()") >= 3, "bound by every caller"


def test_the_refusal_reads_the_verdict_not_the_status():
    """A status is written by the reconciler on its own schedule. The
    verdict is written the moment the reviewer clicks, and it is what the
    spend has to answer to."""
    assert "a.status" not in repository.WITHHELD_BY_A_REVIEWER
    assert "review_verdict" in repository.WITHHELD_BY_A_REVIEWER
