"""A body already stored under other URLs of the same host is not this article's.

The existing verdict catches a wall two ways: too little text, or explicit
paywall wording. Neither caught the Port Townsend Leader's fallback page -- 2,215
characters of a concert listing, no subscription language -- so it was stored as
the body of two different articles.
"""

from __future__ import annotations

import pytest

from src.crawler.duplicate_body import (
    ERROR_STATUS,
    OTHER_URL_LIMIT,
    SAME_HOST_BODY_COUNT_SQL,
    judge_body,
)


def _judge(count=0, status=200):
    return judge_body(same_host_url_count=count, http_status=status)


class TestTheStatusSettlesItFirst:
    @pytest.mark.parametrize("status", [400, 403, 404, 410, 500, 503])
    def test_an_error_status_means_this_is_not_the_article(self, status):
        """Whatever the server rendered, it did not give us what was asked for."""
        verdict = _judge(status=status)
        assert verdict.keep is False
        assert verdict.reason == f"http_{status}"

    @pytest.mark.parametrize("status", [200, 201, 301, 302, 304])
    def test_a_non_error_status_is_no_objection(self, status):
        assert _judge(status=status).keep is True

    def test_an_unknown_status_is_not_evidence_of_failure(self):
        """A path that cannot report one returns None, and the browser path
        reported none at all until recently. Reading that as failure would
        refuse every body those paths produce."""
        assert _judge(status=None).keep is True

    def test_an_error_status_outranks_a_clean_body(self):
        assert _judge(count=0, status=404).keep is False


class TestEverySameHostRepeat:
    def test_a_body_seen_nowhere_else_is_kept(self):
        assert _judge(count=0).keep is True

    def test_a_single_repeat_is_a_duplicate(self):
        """An earlier version left one repeat alone, on the theory that a
        republished story is two real articles. lafayettemonews showed it is
        not: the same title and the same 2,676-character body at
        /commissioners-meet-with-special-road-districts/ and the same slug with
        WordPress's `-2` suffix, both `enriched`, so the story appeared twice in
        everything downstream."""
        verdict = _judge(count=1)
        assert verdict.keep is False
        assert verdict.duplicate is True

    def test_frequent_furniture_is_the_same_verdict(self):
        """Furniture and a double-post are one problem at two frequencies."""
        verdict = _judge(count=613)
        assert verdict.keep is False
        assert verdict.duplicate is True

    def test_the_reason_says_how_many_hold_it(self):
        assert "613" in (_judge(count=613).reason or "")

    def test_the_first_row_to_store_a_body_keeps_it(self):
        """Which is what makes this a duplicate rule and not a rule that
        refuses the story outright: one copy survives."""
        assert OTHER_URL_LIMIT == 0
        assert _judge(count=0).keep is True


class TestADuplicateIsNotAnError:
    def test_an_error_status_is_not_marked_duplicate(self):
        """`duplicate` names the story that survived; a 404 had no story."""
        verdict = _judge(status=404)
        assert verdict.keep is False
        assert verdict.duplicate is False

    def test_the_caller_picks_the_status_from_that_flag(self):
        from pathlib import Path

        body = Path("src/cli/commands/extraction.py").read_text()
        block = body.split("if not body_verdict.keep:")[1][:1200]
        assert "body_verdict.duplicate" in block
        assert "DUPLICATE" in block
        assert '"not_article"' in block


class TestTheQueryItCountsWith:
    def test_it_is_scoped_to_one_host_and_excludes_the_url_itself(self):
        """Cross-host repeats are syndication -- the point of this corpus, and
        6,123 hash groups span more than one host. Counting them would refuse
        every syndicated story."""
        assert (
            "SELECT source_id FROM candidate_links WHERE id = :candidate_link_id"
            in (SAME_HOST_BODY_COUNT_SQL)
        )
        assert "a.candidate_link_id <> :candidate_link_id" in SAME_HOST_BODY_COUNT_SQL

    def test_it_matches_on_the_hash_so_the_index_is_used(self):
        assert "a.text_hash = :text_hash" in SAME_HOST_BODY_COUNT_SQL

    def test_it_is_bounded_because_the_answer_only_has_to_clear_a_threshold(self):
        """613 rows share one notice; counting them all to learn "more than 2"
        is work nobody needs."""
        assert "LIMIT :probe" in SAME_HOST_BODY_COUNT_SQL


class TestTheBoundariesAreNamedNotBuried:
    def test_they_are_importable_constants(self):
        assert OTHER_URL_LIMIT == 0
        assert ERROR_STATUS == 400
