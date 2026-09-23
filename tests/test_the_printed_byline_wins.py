"""The byline the paper printed beats the one its CMS emitted.

The extractors take the author from structured data -- JSON-LD, a meta tag, a CMS
field -- and nothing compared that against the line printed at the top of the
story. Measured on the Mizzou corpus 2026-09-22: `Karl Zinke` on 489
examiner.net stories written by Mike Genet and Bill Althaus, `Admin` on 405 of
405 eldoradospringsmo.com stories, `Luis Merlo` on 344 of 354 dosmundos.com
stories, and one unterrifieddemocrat.com story headed "By Neal A. Johnson, UD
Editor" credited to a KY3 reporter with 896 stories elsewhere.

WHAT IS TESTED HERE IS THE BOUNDARY, because that is all this module owns.
`BylineCleaner` already knows what a byline says -- titles, publications, name
particles, desk names, what counts as a person -- and is asked. What it cannot
know is where a byline ENDS, because it was written for a byline field and a
cleaned body runs the byline into the story: handed the whole line it answers
"Tere Siqueira Protests Over Immigration Enforcement In Minnesota".
"""

from __future__ import annotations

import pytest

from src.utils.printed_byline import choose, disagrees, printed_byline


@pytest.fixture(scope="module")
def cleaner():
    """One cleaner for the module. It reads publication and organisation names
    from the database on construction, so building one per case is slow and
    tells us nothing extra."""
    from src.utils.byline_cleaner import BylineCleaner

    return BylineCleaner(enable_telemetry=False)


def read(text, cleaner):
    return printed_byline(text, cleaner=cleaner)


class TestWhereTheBylineEnds:
    """The one thing the cleaner cannot answer."""

    def test_a_byline_the_page_set_on_its_own_line(self, cleaner):
        assert read("By Mary Jo Rieth\n\nThe council met.", cleaner) == "Mary Jo Rieth"

    def test_a_byline_the_capture_ran_into_the_story(self, cleaner):
        """The corpus case: no newline, and the sentence's first word is
        capitalised exactly like a surname."""
        text = "By Tere Siqueira Protests over immigration enforcement in Minnesota"
        assert read(text, cleaner) == "Tere Siqueira"

    def test_a_title_after_the_name_is_left_to_the_cleaner(self, cleaner):
        assert read("By Neal A. Johnson, UD Editor\n\nLINN — ", cleaner) == (
            "Neal A. Johnson"
        )

    def test_a_paper_after_the_name_ends_the_byline(self, cleaner):
        """ "By Eli Hoff St. Louis Post-Dispatch" is a byline and a masthead. `St.`
        would otherwise be taken as a name particle and kept."""
        assert read("By Eli Hoff St. Louis Post-Dispatch\nJEFFERSON CITY", cleaner) == (
            "Eli Hoff"
        )

    def test_a_dateline_after_the_name_is_not_a_surname(self, cleaner):
        """Datelines are conventionally set in capitals."""
        assert read("By Jason Vance COLUMBIA — The board met", cleaner) == "Jason Vance"

    def test_a_name_particle_continues_the_name(self, cleaner):
        """A byline that a capital-only walk would cut to one word."""
        assert read("By Juan de la Cruz, staff\n\nText", cleaner) == "Juan de la Cruz"

    def test_a_title_before_the_name_does_not_shorten_it(self, cleaner):
        """Two words taken on sight would be "Congressman Mark" and the surname
        would be lost. What to do with the title is the cleaner's business."""
        assert "Alford" in (read("By Congressman Mark Alford\n\nText", cleaner) or "")

    def test_a_three_word_name_is_taken_when_the_line_ends(self, cleaner):
        assert (
            read("By Robin Garrison Leach\n\nText", cleaner) == "Robin Garrison Leach"
        )


class TestWhatIsRefused:
    """Refusing is always safe: the structured byline stays and the row stays
    reviewable. A wrong printed byline would be worse, because it would look
    reviewed."""

    def test_a_desk_name_is_not_a_person(self, cleaner):
        """The cleaner decides this, and returns nothing."""
        assert read("By Staff Reports\n\nText", cleaner) is None

    def test_a_masthead_is_not_a_person(self, cleaner):
        assert read("By The Associated Press\n\nText", cleaner) is None

    def test_a_byline_the_capture_glued_to_the_next_word(self, cleaner):
        """ "Jayme LachnerPrairie" cannot be split back apart, so no boundary can
        be found."""
        assert read("By Jayme LachnerPrairie Post\n\nText", cleaner) is None

    def test_a_name_run_into_the_papers_initials(self, cleaner):
        """ "PAUL STURMC-T" is Paul Sturm and the Constitution-Tribune."""
        assert read("By PAUL STURMC-T staff\n\nText", cleaner) is None

    def test_a_byline_the_capture_cut_off(self, cleaner):
        """ "By Neal A." -- a name cannot end on an initial."""
        assert read("By Neal A.\n\nText", cleaner) is None

    def test_by_in_a_sentence_is_a_preposition(self, cleaner):
        assert read("A plan praised by John Smith on Tuesday.", cleaner) is None

    def test_by_further_down_the_body_is_not_this_storys_byline(self, cleaner):
        """It belongs to a quoted item, a photo credit or a related story."""
        text = "The council met Tuesday.\n\nBy Someone Else\n\nMore text"
        assert read(text, cleaner) is None

    def test_a_by_line_that_is_not_a_name(self, cleaner):
        assert read("By the numbers: 42 people attended", cleaner) is None

    def test_no_body_is_no_answer(self, cleaner):
        assert read("", cleaner) is None
        assert read(None, cleaner) is None


class TestWhenTheStoredBylineIsReplaced:
    def test_a_different_person_is_replaced(self, cleaner):
        text = "By Neal A. Johnson, UD Editor\n\nLINN — Linn R-2 board members"
        author, note = choose("Christopher Replogle", text, cleaner=cleaner)
        assert author == "Neal A. Johnson"
        assert note["byline_replaced"] == "Christopher Replogle"
        assert note["byline_source"] == "printed_in_body"

    def test_a_cms_account_is_replaced(self, cleaner):
        author, note = choose(
            "Admin", "By Sawyer Bess\n\nThe city council", cleaner=cleaner
        )
        assert author == "Sawyer Bess"
        assert note is not None

    def test_a_spelling_variant_is_left_to_the_review_queue(self, cleaner):
        """ "Neal Johnson" and "Neal A. Johnson" are one person spelled two ways.
        Swapping spends a write on nothing and hides the variant from the
        reviewer, whose queue exists to settle exactly that."""
        text = "By Neal A. Johnson, UD Editor\n\nLINN — "
        author, note = choose("Neal Johnson", text, cleaner=cleaner)
        assert author == "Neal Johnson"
        assert note is None

    def test_nothing_printed_leaves_the_stored_byline_alone(self, cleaner):
        author, note = choose("Karl Zinke", "The council met Tuesday.", cleaner=cleaner)
        assert author == "Karl Zinke"
        assert note is None

    def test_an_absent_byline_is_not_filled_here(self, cleaner):
        """4,608 stories print a byline and have none stored. Filling those is a
        separate change: it would add names to the corpus rather than correct
        names already in it, and an AP byline printed in a wire story would
        become a local reporter."""
        author, note = choose(
            None, "By Sawyer Bess\n\nThe city council", cleaner=cleaner
        )
        assert author is None
        assert note is None


class TestComparingTwoBylines:
    def test_no_shared_name_word_is_a_different_person(self):
        assert disagrees("Christopher Replogle", "Neal A. Johnson")

    def test_a_shared_surname_is_the_same_person(self):
        assert not disagrees("Neal Johnson", "Neal A. Johnson")

    def test_a_missing_side_is_not_a_disagreement(self):
        assert not disagrees(None, "Neal A. Johnson")
        assert not disagrees("Neal A. Johnson", None)

    def test_a_co_authored_byline_agrees_on_either_name(self):
        """The printed line names one of them; that is not a contradiction."""
        assert not disagrees("Alyssa Mueller, Marcus Off", "Marcus Off")


class TestTheExtractionPathUsesIt:
    """Both write paths, because the batch path is the one that runs nightly and
    the single-url path is the one used to check a fix."""

    def test_both_paths_choose_the_printed_byline(self):
        from pathlib import Path

        source = Path("src/cli/commands/extraction.py").read_text()
        assert source.count("printed_byline.choose(") == 2

    def test_the_swap_is_recorded_on_the_row(self):
        """ "Why does this row say a different name than the page's JSON-LD" is a
        question asked months later, about one row, by somebody reading the
        database."""
        from pathlib import Path

        source = Path("src/cli/commands/extraction.py").read_text()
        assert source.count("metadata_value.update(byline_note)") == 2
