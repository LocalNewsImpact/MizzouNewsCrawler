"""An author bio is syndication evidence when it names a paper that is not ours.

That is the whole question, and it needs no list of publications. Resolving a
bio's masthead against every paper that exists is impossible -- "Las Cruces
Sun-News" is real and not in our corpus, and a Las Cruces reporter's bio on the
Springfield News-Leader is Gannett syndication whether or not `sources` has
heard of Las Cruces. Whether the bio's masthead differs from OURS is a
comparison against one string we already have: `sources.canonical_name`.

The rule got two things wrong, and both are measured:

IT ASKED THE URL. "Is `dailynews` in tdn.com" -- no, because a domain may
abbreviate its own masthead, so The Daily News read as syndicating to itself.
133 of 158 historical detections, every one wrong, at 0.9 confidence, which is
enough to set `wire` alone.

IT CAPTURED ANYTHING. The patterns end in common English words -- Tribune, Star,
Post, News, Record -- and ran under `re.IGNORECASE`, which made the `[A-Z]`
anchor and the capitalised terminators decorative:

    "reporter for the Minnesota news outlet"
        IGNORECASE     -> "Minnesota news"
        case-sensitive -> no match

    "reporter for USA TODAY and covers scientific studies and trending news"
        IGNORECASE     -> the whole clause
        case-sensitive -> no match

"Minnesota news" is not a publication name.
"""

from __future__ import annotations

import inspect

import pytest

from src.utils.content_type_detector import (
    ContentTypeDetector,
    _is_our_own_masthead,
    _masthead_aliases,
    _normalize_masthead,
)

BODY = "The council voted on Tuesday to approve the measure. " * 20


def _fire(own_name: str | None, bio: str) -> str | None:
    body = f"{BODY}\n\nJane Smith is a reporter for {bio}."
    return ContentTypeDetector()._detect_syndication_from_bio(
        body, "https://example.com/news/story/article_1.html", own_name
    )


class TestADifferentPublicationIsSyndication:
    @pytest.mark.parametrize(
        "own,bio,why",
        [
            ("Fulton Sun", "Jefferson City News Tribune", "6 rows in production"),
            ("Fulton Sun", "News Tribune", "2 rows"),
            ("California Democrat", "Jefferson City News Tribune", "1 row"),
            (
                "Springfield News-Leader",
                "Las Cruces Sun-News",
                "2 rows: Gannett sharing between states, and NOT in our sources",
            ),
            ("Southeast Missourian", "Washington Examiner", "a paper we do not carry"),
        ],
    )
    def test_it_fires(self, own, bio, why):
        assert _fire(own, bio) == bio

    def test_a_paper_we_do_not_carry_still_counts(self):
        """The reason this rule does not consult a list of sources. An
        unrecognised masthead is not a reason to call the story local."""
        assert _fire("Springfield News-Leader", "Las Cruces Sun-News")

    def test_the_finding_is_the_masthead_the_bio_named(self):
        """So the evidence can be argued with, rather than saying only "wire"."""
        assert _fire("Fulton Sun", "Chicago Tribune") == "Chicago Tribune"


class TestOurOwnMastheadIsNotSyndication:
    @pytest.mark.parametrize(
        "own,bio",
        [
            ("The Daily News (Longview)", "The Daily News"),
            ("The Daily News (Longview)", "Daily News"),
            ("The Kansas City Star", "The Kansas City Star"),
            ("Jefferson City News Tribune/News Tribune", "News Tribune"),
            ("Jefferson City News Tribune/News Tribune", "Jefferson City News Tribune"),
        ],
    )
    def test_a_paper_does_not_syndicate_to_itself(self, own, bio):
        assert _fire(own, bio) is None

    def test_a_city_qualifier_is_ours_not_the_bylines(self):
        """ "(Longview)" is how our source list disambiguates; a byline will not
        carry it, and the old URL test could not see past that either."""
        assert _normalize_masthead("The Daily News (Longview)") == _normalize_masthead(
            "Daily News"
        )

    def test_a_less_specific_form_of_our_name_is_still_us(self):
        assert _fire("The Kansas City Star", "The Star") is None


class TestTheDirectionOfTheContainment:
    def test_a_more_specific_masthead_is_another_paper(self):
        """The direction that stops this excusing real syndication. Our "Daily
        News" appearing inside "New York Daily News" is the New York paper."""
        assert _fire("The Daily News (Longview)", "New York Daily News")

    def test_the_comparison_is_not_symmetric(self):
        assert _is_our_own_masthead("Daily News", "The Daily News (Longview)")
        assert not _is_our_own_masthead("New York Daily News", "The Daily News")

    def test_a_masthead_is_not_matched_inside_a_word(self):
        assert not _is_our_own_masthead("News", "Newsweek")


class TestWhatIsNotCapturedAtAll:
    def test_a_lowercase_phrase_is_not_a_publication(self):
        body = f"{BODY}\n\nJane is a reporter for the Minnesota news outlet."
        assert (
            ContentTypeDetector()._detect_syndication_from_bio(
                body, "https://example.com/a.html", "Fulton Sun"
            )
            is None
        )

    def test_a_clause_is_not_a_publication(self):
        body = (
            f"{BODY}\n\nHe is a reporter for USA TODAY and covers scientific "
            "studies and trending news"
        )
        assert (
            ContentTypeDetector()._detect_syndication_from_bio(
                body, "https://example.com/a.html", "Fulton Sun"
            )
            is None
        )

    def test_the_patterns_are_matched_case_sensitively(self):
        """Asserted on the CALL, not on the source text. The docstring names
        `re.IGNORECASE` to say what the defect was, so a test that searched the
        whole function body would fail on the explanation -- and, reversed,
        would have passed on it."""
        code = inspect.getsource(ContentTypeDetector._detect_syndication_from_bio)
        assert "re.search(pattern, bio_section)" in code
        body = "\n".join(
            line
            for line in code.splitlines()
            if not line.strip().startswith(("#", '"', "-", "IT ", "    IGNORECASE"))
        )
        assert "re.search(pattern, bio_section, " not in body

    def test_the_terminators_are_capitalised_in_the_pattern(self):
        assert "Tribune|Star|Times|Post|News" in ContentTypeDetector._BIO_MASTHEAD


class TestWithoutOurNameItMakesNoClaim:
    def test_no_publication_name_means_no_finding(self):
        """The URL is what got this wrong 133 times, so there is no fallback to
        it. A caller that cannot say who published the article gets no verdict."""
        assert _fire(None, "Jefferson City News Tribune") is None
        assert _fire("", "Jefferson City News Tribune") is None

    def test_it_consults_no_list_of_publications(self):
        """A source index was tried and dropped: it kept the Jefferson City
        findings and lost the Las Cruces ones, because completeness is
        impossible."""
        code = inspect.getsource(ContentTypeDetector._detect_syndication_from_bio)
        assert "_masthead_hosts" not in code
        assert not hasattr(ContentTypeDetector, "_masthead_hosts")


class TestNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("The Daily News (Longview)", "daily news"),
            ("The Kansas City Star", "kansas city star"),
            ("St. Louis Post-Dispatch", "st louis post dispatch"),
        ],
    )
    def test_a_masthead_reduces_to_what_identifies_it(self, raw, expected):
        assert _normalize_masthead(raw) == expected

    def test_a_slash_claims_two_mastheads(self):
        assert _masthead_aliases("Jefferson City News Tribune/News Tribune") == [
            "jefferson city news tribune",
            "news tribune",
        ]


class TestItIsWiredIn:
    def test_detect_takes_the_publishers_name(self):
        assert (
            "publication_name"
            in inspect.signature(ContentTypeDetector.detect).parameters
        )

    def test_the_wire_tier_receives_it(self):
        code = inspect.getsource(ContentTypeDetector.detect)
        assert "publication_name=publication_name" in code

    def test_the_rule_receives_it(self):
        code = inspect.getsource(ContentTypeDetector._detect_wire_service)
        assert "url_lower, publication_name" in code

    def test_extraction_passes_the_publisher(self):
        from pathlib import Path

        assert (
            "publication_name=publisher"
            in Path("src/cli/commands/extraction.py").read_text()
        )

    def test_the_evidence_names_both_publications(self):
        code = inspect.getsource(ContentTypeDetector._detect_wire_service)
        assert "author bio names a publication other" in code

    def test_the_url_guessing_rule_is_gone(self):
        assert not hasattr(ContentTypeDetector, "_detect_cross_publication_byline")


class TestEndToEnd:
    """The wiring. Every test above passes with the name threaded nowhere."""

    URL = "https://tdn.com/news/local/business/cowlitz-fines/article_1.html"

    def _detect(self, bio, publication_name):
        body = f"{BODY}\n\nJane Smith is a reporter for {bio}."
        return ContentTypeDetector().detect(
            url=self.URL,
            title="County fines firm over violations",
            metadata={},
            content=body,
            raw_html=f"<html><body><p>{body}</p></body></html>",
            publication_name=publication_name,
        )

    def test_our_own_masthead_is_not_wire(self):
        result = self._detect("The Daily News", "The Daily News (Longview)")
        assert result is None or result.status != "wire"

    def test_another_publication_is_wire(self):
        result = self._detect("The Kansas City Star", "The Daily News (Longview)")
        assert result is not None
        assert result.status == "wire"

    def test_without_the_name_nothing_is_claimed(self):
        result = self._detect("The Kansas City Star", None)
        assert result is None or result.status != "wire"
