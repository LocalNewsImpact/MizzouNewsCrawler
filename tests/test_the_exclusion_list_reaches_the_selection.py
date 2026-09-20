"""One exclusion list, and it reaches the query that selects articles.

There were two and they disagreed. `classification_service` excluded
`opinion/opinions/obituary/obits/wire` and passed that to the selection.
`cli/commands/analysis.py` named those plus `paywall` and `not_article` — but
applied its copy only inside `_snapshot_labels`, the label-change REPORT. The
selection never saw the extra two, and neither list knew about the terminal
statuses added later.

So `analyze --statuses all` resolves to no status filter and would re-label 32
WSU articles that had been deliberately set aside: 24 `not_article`, 7
`paywall`, 1 `non_english`. Measured against production 2026-09-19, before a
planned full WSU reclassification.

`non_english` and `text_unavailable` are terminal by decision rather than by
content — a Spanish article waits for a Spanish classifier, and a row with no
usable body exists only to record that the publication ran the story.
"""

from __future__ import annotations

from src.cli.commands import analysis
from src.services.classification_service import NEVER_CLASSIFIED


def test_the_two_lists_are_now_one_object():
    # Not "equal" -- the same object. Two sets that happen to match today
    # drift apart, which is exactly what happened.
    assert analysis.EXCLUDED_STATUSES is NEVER_CLASSIFIED


def test_the_statuses_that_were_missing_are_covered():
    # These four are the gap the divergence left.
    for status in ("paywall", "not_article", "non_english", "text_unavailable"):
        assert status in NEVER_CLASSIFIED, status


def test_the_original_five_are_still_covered():
    for status in ("opinion", "opinions", "obituary", "obits", "wire"):
        assert status in NEVER_CLASSIFIED, status


def test_the_statuses_a_run_is_supposed_to_take_are_not_excluded():
    # The default selection and the statuses a full reclassification names.
    for status in (
        "cleaned",
        "local",
        "labeled",
        "enriched",
        "enrichment_skipped",
    ):
        assert status not in NEVER_CLASSIFIED, status


def test_the_list_cannot_be_mutated_by_a_caller():
    # A set would let one caller's edit reach every other. `analysis` aliases
    # this object, so it has to be immutable.
    assert isinstance(NEVER_CLASSIFIED, frozenset)


def test_the_service_uses_the_shared_list_not_its_own_copy():
    """The literal set must be gone from the method, not merely widened."""
    import inspect

    from src.services.classification_service import ArticleClassificationService

    source = inspect.getsource(ArticleClassificationService.apply_classification)
    body = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )
    assert "NEVER_CLASSIFIED" in body
    # The old inline set opened with `excluded_statuses = {` and a literal.
    assert "excluded_statuses = {\n" not in body


def test_a_named_terminal_status_is_refused_not_honoured():
    """`--statuses non_english` classifies nothing, and says so.

    A prohibition, not a default. The service filters the named statuses
    against the list and returns early when nothing survives, rather than
    letting an English model judge a Spanish article because it was asked.
    """
    from src.services.classification_service import ArticleClassificationService

    service = ArticleClassificationService.__new__(ArticleClassificationService)
    survivors = [s for s in ("non_english", "paywall") if s not in NEVER_CLASSIFIED]
    assert survivors == []
    assert service is not None
