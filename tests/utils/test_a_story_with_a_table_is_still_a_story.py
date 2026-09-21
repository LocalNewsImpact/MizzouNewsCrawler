"""A story that ends in a table is still a story.

`looks_like_furniture` is a BLOCK test -- its own docstring says so -- and every
shape rule it falls back on (prose density, capitalisation, utility-word rate,
token repetition) is an AVERAGE over whatever it is handed. The extraction gate
handed it a whole captured body, so the verdict was decided by whichever part of
the document had the most lines.

Measured on the real capture, `filing-week-kicks-off-with-46-candidates-in-yakima-
county`, fetched as a subscriber with HTTP 200 on 2026-09-20:

| measured over | prose density | capitalisation | verdict |
| --- | --- | --- | --- |
| the whole body (3,440 chars) | 0.11 (floor 0.14) | 0.67 (ceiling 0.60) | furniture |
| its first five paragraphs (965) | 0.265 | 0.344 | prose |

Six paragraphs of reporting, 1,064 characters, then 46 candidates for 40 offices
as 80 lines of 8 to 53 characters. The roster outvotes the reporting 80 lines to
6, so no threshold setting rescues it -- and a story about who is running for
local office was filed `not_article` and left the corpus. A second instance was
found the same day: `school-board-races-starting-to-take-shape-with-more-candidate-
filings`.

The fix asks the question the other way round. Not "is the average prose" but "is
there a run of prose long enough to be a story", at the threshold this pipeline
already accepts for a whole article (`MIN_CONTENT_LENGTH`, 150).

The safety property is the asymmetry: a SHAPE verdict can be overturned by prose,
a MARKER verdict never can. A paywall teaser is a few real sentences followed by a
wall, which is exactly the shape this override would otherwise wave through -- and
it stays caught, because a wall is found by its phrase before shape is ever
measured.
"""

from __future__ import annotations

from src.utils.boilerplate import (
    PAYWALL,
    REPLACES_THE_STORY,
    UNKNOWN,
    classify_furniture,
    document_is_furniture,
    longest_prose_run,
)

#: The opening of the real capture, verbatim, then the roster shape that sank it.
FILING_WEEK = "\n".join(
    [
        "Filing week began with 46 candidates filing for 40 local elected "
        "positions across Yakima County on Monday.",
        "So far, two candidates have filed to run to fill the Yakima County "
        "coroner seat left vacant by Jim Curtice, who resigned last month. Chief "
        "Deputy Coroner Marshall Slight and Dan Williams, a funeral director and "
        "embalmer who ran in 2018, are vying for the position.",
        "For Yakima City Council, incumbent council member Janice Deccio is "
        "running for reelection against challenger Juliet Potrykus for Position "
        "4. Council member Matt Brown, in Position 6, filed for reelection. The "
        "Position 2 seat in East Yakima also is up for election.",
        "The Zillah mayoral race saw two candidates file for the position: "
        "incumbent Mayor Scott Carmack and Jacob Castillo. In Mabton, Martha "
        "Gonzalez filed to run for mayor.",
    ]
    + [
        # 80 roster lines in the real capture; 40 is enough to invert the average.
        line
        for pair in zip(
            [f"Yakima School District, Position {n}" for n in range(1, 21)],
            [f"Candidate Name {n} (incumbent)" for n in range(1, 21)],
            strict=True,
        )
        for line in pair
    ]
)

TEASER_THEN_WALL = "\n".join(
    [
        "Yakima City Council voted Tuesday to approve the budget after two hours "
        "of testimony from residents who packed the chamber. The measure passed "
        "five to two, with members citing the need for police overtime funding.",
        "To continue reading please log in or subscribe",
        "Subscribe now",
    ]
)

NAV_DUMP = "\n".join(
    [
        "Home News Sports Obituaries Classifieds Jobs Legals Contact Us",
        "Subscribe Manage Account Newsletters E-Edition",
    ]
)


class TestTheRealCaptureThatWasLost:
    def test_the_block_test_still_calls_it_furniture(self):
        """The bug, reproduced. This is why the call site had to change.

        `looks_like_furniture` is not wrong -- it answers a block question
        correctly. It was being asked a document question.
        """
        verdict = classify_furniture(FILING_WEEK)
        assert verdict is not None
        assert verdict.kind == UNKNOWN

    def test_the_document_test_calls_it_a_story(self):
        assert document_is_furniture(FILING_WEEK, 150) is None

    def test_the_prose_run_is_what_carries_it(self):
        """The reporting is contiguous and far over the threshold."""
        assert longest_prose_run(FILING_WEEK) >= 700


class TestAWallIsStillAWall:
    def test_a_teaser_followed_by_a_wall_stays_caught(self):
        """The regression this override could have introduced.

        A teaser's prose clears 150 characters easily, so if shape were the only
        thing consulted the wall would pass as a story. It is caught on the
        phrase, before shape is measured.
        """
        verdict = document_is_furniture(TEASER_THEN_WALL, 150)
        assert verdict is not None
        assert verdict.kind == PAYWALL

    def test_only_a_wall_is_unoverridable(self):
        """The distinction is what the furniture REPLACES, not that it is a marker.

        My first version made every marker verdict fatal, which cost two
        Spanish-language stories from Spokane Public Radio and Northwest Public
        Broadcasting: filed `not_article` on `sign up for our`, with 1,020 and 603
        characters of reporting in them. A newsletter ask is printed beside
        reporting; a wall is served instead of it.
        """
        assert REPLACES_THE_STORY == {PAYWALL}

    def test_a_nav_dump_with_no_prose_is_still_furniture(self):
        """Not because nav is fatal -- because there is no prose in it.

        The threshold is what keeps the genuine cases out. Measured on the WSU
        captures: a "Page not found" e-edition shell has a 66-character run and a
        masthead page 114, both under the 150 this pipeline needs.
        """
        assert longest_prose_run(NAV_DUMP) < 150
        assert document_is_furniture(NAV_DUMP, 150) is not None


class TestFurnitureBesideAStoryIsNotFatal:
    pytestmark_note = "the real captures are Spanish-language WSU stories"

    def test_a_newsletter_ask_does_not_discard_the_reporting(self):
        body = "\n".join(
            [
                "El Condado de Chelan dejara de compartir las fechas de los "
                "incendios con las comunidades agricolas, una decision que segun "
                "los lideres locales dejara a los trabajadores sin informacion "
                "sobre cuando es seguro volver a los campos de manzanas.",
                "Los grupos comunitarios dijeron que la falta de avisos en "
                "espanol ya habia limitado la respuesta durante la temporada "
                "pasada, cuando el humo cerro varias escuelas de la zona.",
                "Sign up for our newsletter",
            ]
        )
        assert classify_furniture(body) is not None  # the ask is still found
        assert document_is_furniture(body, 150) is None  # the story survives it

    def test_the_same_body_without_enough_prose_stays_furniture(self):
        """The prose run is doing the work, not a blanket exemption for promos."""
        assert document_is_furniture("Sign up for our newsletter", 150) is not None


class TestTheRunIsContiguous:
    def test_prose_split_by_furniture_does_not_accumulate(self):
        """Two short prose fragments either side of a table are not a story.

        Summing every prose paragraph in the document would let a body of
        scattered captions add up to an article, which is the opposite mistake.
        """
        scattered = "\n".join(
            [
                "A short caption here.",
                "Section One",
                "Another short caption.",
                "Section Two",
            ]
        )
        assert longest_prose_run(scattered) < 150

    def test_an_empty_body_has_no_run(self):
        assert longest_prose_run("") == 0
        assert longest_prose_run(None) == 0
        assert longest_prose_run("   \n  \n") == 0

    def test_blank_lines_do_not_break_a_run(self):
        """Publishers separate paragraphs with blank lines; that is formatting,
        not a furniture boundary."""
        a = "The council met on Tuesday evening to consider the budget proposal."
        b = "Residents spoke for two hours before the vote was finally taken."
        assert longest_prose_run(f"{a}\n\n{b}") == len(a) + len(b)


class TestTheGateUsesIt:
    def test_extraction_calls_the_document_test(self):
        import inspect

        from src.cli.commands import extraction

        source = inspect.getsource(extraction._process_batch)
        body = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        assert "document_is_furniture(stripped_content, MIN_CONTENT_LENGTH)" in body
        assert "looks_like_furniture(" not in body

    def test_the_threshold_is_the_one_already_used_for_a_whole_article(self):
        """Not a new number to tune. If 150 characters is enough to be an
        article, 150 characters of prose is enough to prove one is present.

        Asserted as an equality against the constant the insufficient-content
        check uses, so the two cannot drift apart: raising one and not the other
        would mean a body long enough to keep needs MORE prose than a whole
        article does, or less.
        """
        import inspect
        import re

        from src.cli.commands import extraction

        source = inspect.getsource(extraction._process_batch)
        declared = re.search(r"MIN_CONTENT_LENGTH = (\d+)", source)
        assert declared, "MIN_CONTENT_LENGTH is not declared in the batch"
        assert int(declared.group(1)) == 150
        assert "len(stripped_content.strip()) < MIN_CONTENT_LENGTH" in source
        assert "document_is_furniture(stripped_content, MIN_CONTENT_LENGTH)" in source
