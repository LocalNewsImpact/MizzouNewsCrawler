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


class TestHowManyOtherUrlsHoldIt:
    def test_a_body_seen_nowhere_else_is_kept(self):
        assert _judge(count=0).keep is True

    def test_a_single_repeat_is_left_alone(self):
        """An outlet does republish a story at a second URL, and those are real
        articles -- lafayettemonews has a 2,676-character one at two."""
        assert _judge(count=1).keep is True

    def test_two_other_urls_is_still_allowed(self):
        assert _judge(count=OTHER_URL_LIMIT).keep is True

    def test_three_makes_it_a_fixture_of_the_site(self):
        """By then it is a wall, a search page or a calendar notice. The corpus
        holds one "Attention subscribers" notice under 613 URLs of one host."""
        verdict = _judge(count=OTHER_URL_LIMIT + 1)
        assert verdict.keep is False
        assert "urls_of_this_host" in (verdict.reason or "")

    def test_the_reason_says_how_many(self):
        assert "40" in (_judge(count=40).reason or "")


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
        assert OTHER_URL_LIMIT == 2
        assert ERROR_STATUS == 400
