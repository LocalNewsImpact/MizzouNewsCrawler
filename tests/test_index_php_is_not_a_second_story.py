"""One story arrived twice, differing only by `/index.php`.

    http://www.excelsiorspringsstandard.com/index.php/news/lewis-growing-young-readers
    http://www.excelsiorspringsstandard.com/news/lewis-growing-young-readers

A front controller in the path is routing, not address: the CMS serves
the identical page at both, and different parts of the same site link to
each form. Discovery found both, made two links, and the story was
fetched, parsed and classified twice.

MEASURED 2026-09-14: 313 stories in the corpus twice, 278 of them
extracted twice, 99% from two publishers -- richmond-dailynews.com (169)
and excelsiorspringsstandard.com (139). One reached BigQuery twice.

Stripping it in `normalize_url` rather than only in the dedup comparison,
so the STORED url is the canonical one and there is only ever one form of
it to find.
"""

from __future__ import annotations

import pytest

from src.utils.url_utils import normalize_url, normalize_url_for_dedup


class TestTheTwoFormsBecomeOne:
    def test_the_pair_that_was_reported(self):
        with_it = (
            "http://www.excelsiorspringsstandard.com"
            "/index.php/news/lewis-growing-young-readers"
        )
        without = (
            "http://www.excelsiorspringsstandard.com"
            "/news/lewis-growing-young-readers"
        )
        assert normalize_url(with_it) == normalize_url(without)

    def test_it_strips_rather_than_flags(self):
        """The stored URL is the canonical one. Normalising only for the
        dedup comparison would still leave whichever form was found first
        sitting in the table, so the corpus would carry `/index.php`
        addresses that resolve to the same page as their neighbours."""
        assert "/index.php" not in normalize_url("https://example.com/index.php/news/x")

    @pytest.mark.parametrize(
        "front",
        [
            "index.php",
            "index.html",
            "index.htm",
            "index.cfm",
            "index.asp",
            "index.aspx",
            "index.jsp",
        ],
    )
    def test_the_other_front_controllers_too(self, front):
        """Same routing trick, different stack. Cheap to cover, and a
        publisher moving from PHP to .NET should not reintroduce this."""
        assert normalize_url(f"https://example.com/{front}/news/x") == (
            "https://example.com/news/x"
        )

    def test_it_is_case_insensitive(self):
        assert normalize_url("https://example.com/Index.PHP/news/x") == (
            "https://example.com/news/x"
        )

    def test_a_front_controller_deeper_in_the_path(self):
        assert normalize_url("https://example.com/story/index.php/more") == (
            "https://example.com/story/more"
        )

    def test_dedup_agrees(self):
        """The comparison path is built on `normalize_url`, so it follows
        -- but the pair that started this has to match there too, because
        that is what stops the second link being created."""
        a = "http://www.excelsiorspringsstandard.com/index.php/news/x"
        b = "https://excelsiorspringsstandard.com/news/x"
        assert normalize_url_for_dedup(a) == normalize_url_for_dedup(b)


class TestWhatItMustNotTouch:
    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/indexed.php/story",
            "https://example.com/news/index.phone-story",
            "https://example.com/news/reindex.php/x",
            "https://example.com/my-index.php-guide",
        ],
    )
    def test_a_name_that_merely_contains_it_survives(self, url):
        """Anchored on a path segment: it needs a slash before it and a
        slash or the end after it. `indexed.php` is not a front
        controller, and neither is a story slug that happens to read
        like one."""
        assert normalize_url(url) == url

    def test_the_bare_front_controller_is_the_front_page(self):
        """`/index.php` alone is what the bare domain serves."""
        assert normalize_url("https://example.com/index.php") == "https://example.com"

    def test_a_url_with_no_path_is_unharmed(self):
        assert normalize_url("https://example.com") == "https://example.com"

    def test_an_empty_url_is_returned_as_given(self):
        assert normalize_url("") == ""
        assert normalize_url("   ") == "   "


class TestItChangesOnlyWhatItShould:
    def test_it_is_the_only_new_behaviour(self):
        """Run against all 262,041 URLs in production on 2026-09-14, this
        altered 464 of them and every one was a front-controller segment.
        Nothing else in the corpus normalised differently than before.

        Asserted here on the shape, because the corpus is not available
        to the test: the substitution is anchored to a path segment and
        touches nothing else in the URL."""
        import re

        from src.utils.url_utils import _FRONT_CONTROLLER

        assert _FRONT_CONTROLLER.pattern.startswith("/index")
        assert "(?=/|$)" in _FRONT_CONTROLLER.pattern
        assert _FRONT_CONTROLLER.flags & re.I

    def test_the_query_and_fragment_rules_still_hold(self):
        assert normalize_url("https://example.com/index.php/x?ref=home#top") == (
            "https://example.com/x"
        )
