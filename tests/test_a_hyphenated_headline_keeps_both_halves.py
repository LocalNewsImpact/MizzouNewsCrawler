"""A headline split at a hyphenated word gets its first half back.

newspaper4k treats a bare hyphen as a site-name delimiter and keeps the
longest piece, so a hyphenated word splits the headline and the shorter
side is discarded:

    Purr-fect Start: 8 Cats Find Homes  ->  fect Start: 8 Cats Find Homes
    Van-Far girls widen gap             ->  Far girls widen gap
    Spider-Man: Brand New Day           ->  Man: Brand New Day

Roughly 800 articles carry a headline shortened this way. It was noticed
in the extraction review queue, where about half of them begin mid-word
in lowercase; the other half survive as something that reads like a
headline ("Man: Brand New Day") and are invisible without the URL.

The repair reads the page's own markup and restores the cut half only
where the join was a hyphen inside a word -- newspaper's exact
signature.
"""

from src.pipeline.title_repair import repair


def _og(title):
    return f'<meta property="og:title" content="{title}">'


# --- what was cut, put back --------------------------------------------------


def test_a_hyphenated_word_is_restored():
    assert (
        repair(
            "fect Start: 8 Cats Find Homes", _og("Purr-fect Start: 8 Cats Find Homes")
        )
        == "Purr-fect Start: 8 Cats Find Homes"
    )


def test_a_hyphenated_proper_noun_is_restored():
    """Van-Far is a school district, and half its name is not a headline."""
    assert (
        repair("Far girls widen gap", "<h1>Van-Far girls widen gap</h1>")
        == "Van-Far girls widen gap"
    )


def test_the_title_tag_serves_and_its_site_name_stays_out():
    """The <title> tag usually carries the site name, which is why the
    repair looks for the title inside the candidate rather than at its
    end -- and returns only as far as the title reaches."""
    html = "<title>Low-earning college degrees | Missouri Independent</title>"
    assert repair("earning college degrees", html) == "Low-earning college degrees"


def test_a_date_range_is_a_hyphenated_word_too():
    assert repair("2025", _og("1944-2025")) == "1944-2025"


# --- what must be left alone -------------------------------------------------


def test_an_untouched_title_is_returned_unchanged():
    html = _og("Council approves budget")
    assert repair("Council approves budget", html) == "Council approves budget"


def test_a_real_separator_is_not_a_hyphenated_word():
    """ " - " with spaces is a site-name separator, and newspaper was right
    to split there. Restoring it would put the publisher back into the
    headline."""
    assert repair("Houston Herald", _og("Some Story - Houston Herald")) == (
        "Houston Herald"
    )


def test_a_candidate_that_merely_differs_is_not_adopted():
    """This puts back what was cut. It does not choose a better title."""
    assert repair(
        "Council approves budget", _og("A completely different headline")
    ) == ("Council approves budget")


def test_a_longer_candidate_that_does_not_end_with_the_title_is_ignored():
    assert repair("approves budget", _og("Council approves budget tonight")) == (
        "approves budget"
    )


# --- the shapes that must not raise ------------------------------------------


def test_no_html_leaves_the_title_alone():
    assert repair("Far girls widen gap", None) == "Far girls widen gap"
    assert repair("Far girls widen gap", "") == "Far girls widen gap"


def test_no_title_is_returned_as_it_came():
    assert repair(None, _og("Van-Far girls widen gap")) is None
    assert repair("", _og("Van-Far girls widen gap")) == ""
    assert repair("   ", _og("Van-Far")) == "   "


def test_markup_and_entities_in_the_candidate_are_resolved():
    html = "<h1><span>Purr-fect</span> Start &amp; more</h1>"
    assert repair("fect Start & more", html) == "Purr-fect Start & more"
