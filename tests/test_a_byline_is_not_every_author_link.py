"""A byline is not every author link on the page.

newspaper4k gathers authorship document-wide, so a template that prints other
stories with their authors puts those authors in the byline. 402 of 557
Missouri Independent articles carried a multi-name byline this way, against
10% on the pages where structured data supplied the author instead.
"""

import pytest

from src.pipeline.byline_repair import byline_names, repair

#: The Missouri Independent's shape, reduced to what matters: one marked
#: byline and three related-post authors, all four `rel="author"`.
INDEPENDENT = """
<html><body>
  <span class="singleBylineAuthor">
    <a href="/author/rudi-keller/" class="author url fn" rel="author">Rudi Keller</a>
  </span>
  <p>WASHINGTON - the story.</p>
  <div class="crp_related">
    <span class="crp_author">by <a rel="author">Jason Hancock</a></span>
    <span class="crp_author">by <a rel="author">Annelise Hanshaw</a></span>
    <span class="crp_author">by <a rel="author">Ryleigh Hindle</a></span>
  </div>
</body></html>
"""

SCRAPED = ["Rudi Keller", "Jason Hancock", "Annelise Hanshaw", "Ryleigh Hindle"]


class TestTheRelatedPostsAuthorsAreDropped:
    def test_only_the_marked_byline_survives(self):
        assert repair(SCRAPED, INDEPENDENT) == ["Rudi Keller"]

    def test_a_joined_string_comes_back_joined(self):
        """Both call sites hand it `", ".join(article.authors)`."""
        assert repair(", ".join(SCRAPED), INDEPENDENT) == "Rudi Keller"

    def test_the_marked_byline_is_found(self):
        assert byline_names(INDEPENDENT) == ["Rudi Keller"]

    def test_a_related_block_is_never_read_as_the_byline(self):
        """`crp_author` sits inside `crp_related`, and both are foreign."""
        names = byline_names(INDEPENDENT)
        assert "Jason Hancock" not in names
        assert "Ryleigh Hindle" not in names


class TestARealCoBylineSurvives:
    """10% of the Independent's own output is genuinely co-written, which is
    why this is not a count rule. `Steph Quinn, Leore Tal` is two reporters."""

    def test_two_marked_authors_are_both_kept(self):
        html = """
        <span class="byline">
          <a rel="author">Steph Quinn</a>
          <a rel="author">Leore Tal</a>
        </span>
        <div class="related"><span class="crp_author"><a rel="author">Rudi Keller</a></span></div>
        """
        assert repair(["Steph Quinn", "Leore Tal", "Rudi Keller"], html) == [
            "Steph Quinn",
            "Leore Tal",
        ]


class TestItOnlyEverNarrows:
    """It removes what the page shows is somebody else's. Replacing the
    answer, or inventing one, is a different decision."""

    def test_a_page_that_marks_no_byline_is_left_alone(self):
        assert repair(["A Name", "B Name"], "<html><p>nothing</p></html>") == [
            "A Name",
            "B Name",
        ]

    def test_no_html_is_left_alone(self):
        assert repair(["A Name", "B Name"], None) == ["A Name", "B Name"]

    def test_a_single_author_is_never_touched(self):
        assert repair(["Rudi Keller"], INDEPENDENT) == ["Rudi Keller"]

    def test_a_marked_byline_naming_nobody_the_parser_found_is_ignored(self):
        """Disagreement is not correction. If the marked byline and the
        parser share no name, the page is not the shape this understands."""
        html = '<span class="byline"><a rel="author">Someone Else</a></span>'
        assert repair(["A Name", "B Name"], html) == ["A Name", "B Name"]

    def test_nothing_is_added_that_the_parser_did_not_find(self):
        html = """
        <span class="byline">
          <a rel="author">Rudi Keller</a><a rel="author">Never Scraped</a>
        </span>
        """
        assert repair(["Rudi Keller", "Jason Hancock"], html) == ["Rudi Keller"]


class TestTheContainerIsBounded:
    def test_a_byline_container_holding_the_whole_story_is_not_a_name(self):
        """Without the length bound, a mis-marked wrapper makes the article
        text the byline."""
        html = '<div class="byline">' + ("word " * 60) + "</div>"
        assert byline_names(html) == []

    @pytest.mark.parametrize(
        "marker", ["crp_author", "related-posts", "recirc", "sidebar", "widget-authors"]
    )
    def test_foreign_containers_are_skipped_whatever_they_are_called(self, marker):
        html = f'<span class="{marker} byline"><a rel="author">Nobody</a></span>'
        assert byline_names(html) == []
