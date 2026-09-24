"""Four ways a capture is not the byline it looks like.

None of them needs a reviewer, a threshold or a judgement. All four were
reaching the corpus whole, and each splits one reporter's work into two
strings so that every count drawn off either is wrong by the other.
"""

import pytest

from src.utils.byline_cleaner import BylineCleaner

#: The publication names these tests need, as `sources.canonical_name` spells
#: them -- WITH the leading article, because that is the whole defect.
PUBLICATIONS = {
    "The Missouri Independent",
    "Columbia Missourian",
    "The Kansas City Star",
}


@pytest.fixture
def cleaner(monkeypatch):
    """A cleaner whose publication list is FIXED, not read from the crawler.

    `get_publication_names` reads `sources` over the network. Left live, these
    tests pass on a laptop with a warm cache and fail in CI, where there is no
    crawler database and the call falls back to the wire-service list -- so
    the masthead trim would silently have nothing to match and the failure
    would look like a broken rule rather than a missing fixture.
    """
    cleaner = BylineCleaner(enable_telemetry=False)
    monkeypatch.setattr(cleaner, "get_publication_names", lambda *a, **k: PUBLICATIONS)
    monkeypatch.setattr(cleaner, "get_organization_names", lambda *a, **k: set())
    return cleaner


class TestAPhotoCreditIsNotAByline:
    """The one case where salvaging a name is the error.

    A photo credit names who supplied a picture. Trimming `Cameron Montemayor
    File Photo` into a byline credits a reporter with 302 real ones for a
    story he photographed; `Jim Faasen Photos` is eleven such stories. 183
    articles in the Mizzou dataset carry a credit in the byline field, 160 of
    them at `labeled` and still heading for the export.
    """

    @pytest.mark.parametrize(
        "credit",
        [
            "Cameron Montemayor File Photo",
            "Jim Faasen Photos",
            "William Carroll Photos",
            "Photos Waynesville",
            "Submitted Photo",
            "File Photo",
            "All Photos Kevin Jenkins",
        ],
    )
    def test_a_credit_leaves_no_byline(self, cleaner, credit):
        """Empty is the right answer: the article has no byline, and an empty
        field says so where an invented one does not."""
        assert cleaner.clean_byline(credit) == []

    def test_a_byline_beside_a_credit_survives(self, cleaner):
        assert cleaner.clean_byline("Chris Higgins, File Photo") == ["Chris Higgins"]

    def test_only_the_credit_segment_goes(self, cleaner):
        assert cleaner.clean_byline(
            "Luke Hahnel, Photos Emily Early, J Thomas Taylor"
        ) == ["Luke Hahnel", "J Thomas Taylor"]

    def test_a_photographer_is_not_promoted_to_author(self, cleaner):
        """The name in a credit is a real person, which is exactly why a rule
        that trims rather than drops is dangerous here."""
        assert "Cameron Montemayor" not in cleaner.clean_byline(
            "Cameron Montemayor File Photo"
        )


class TestTheMastheadComesOffTheByline:
    """`Rudi Keller Missouri Independent` is Rudi Keller: 126 articles under
    that string against 266 under his name.

    The cleaner already loaded 2,017 publication names and could not match
    one. `sources.canonical_name` is "The Missouri Independent" and the
    matcher compared n-grams for exact equality, so two words from the byline
    were tested against three from the cache and never matched.
    """

    def test_the_masthead_is_trimmed(self, cleaner):
        assert cleaner.clean_byline("Rudi Keller Missouri Independent") == [
            "Rudi Keller"
        ]

    @pytest.mark.parametrize("join", ["-", "–", "|", "~"])
    def test_however_it_is_hung_off_the_name(self, cleaner, join):
        """`normalise_dash_separators` turned the dash form into two authors,
        because an uppercase masthead is name-shaped. Trimming first makes it
        one reporter."""
        assert cleaner.clean_byline(f"Rudi Keller {join} Missouri Independent") == [
            "Rudi Keller"
        ]

    def test_the_article_in_the_masthead_is_optional(self, cleaner):
        """The whole bug, in one assertion."""
        assert BylineCleaner._without_article(("the", "missouri", "independent")) == (
            "missouri",
            "independent",
        )
        assert BylineCleaner._without_article(("missouri", "independent")) == (
            "missouri",
            "independent",
        )

    def test_a_plain_name_is_untouched(self, cleaner):
        assert cleaner.clean_byline("Rudi Keller") == ["Rudi Keller"]


class TestANameWrittenTwice:
    def test_a_doubled_name_is_one_name(self, cleaner):
        """52 articles."""
        assert cleaner.clean_byline("Jon Dykstra Jon Dykstra") == ["Jon Dykstra"]

    def test_two_different_people_are_not_a_doubling(self, cleaner):
        assert BylineCleaner.drop_repeated_name("Jon Dykstra Rudi Keller") == (
            "Jon Dykstra Rudi Keller"
        )

    def test_an_odd_number_of_words_is_not_a_doubling(self, cleaner):
        assert BylineCleaner.drop_repeated_name("Mary Clare Jalonick") == (
            "Mary Clare Jalonick"
        )


class TestAUsernameRunOntoTheName:
    """A CMS username on the end of the display name. `John Hacker Jhacker`
    is 85 articles and `Bill Battle Battleb` is 63, each splitting a real
    reporter's byline in two."""

    def test_first_initial_then_surname(self, cleaner):
        assert cleaner.clean_byline("John Hacker Jhacker") == ["John Hacker"]

    def test_surname_then_first_initial(self, cleaner):
        assert cleaner.clean_byline("Bill Battle Battleb") == ["Bill Battle"]

    def test_a_third_name_is_not_a_username(self, cleaner):
        """Only the two squashed shapes, and only against the name they
        follow, so a real third name survives."""
        assert BylineCleaner.drop_own_username("Mary Clare Jalonick") == (
            "Mary Clare Jalonick"
        )
        assert BylineCleaner.drop_own_username("Anton L Delgado") == "Anton L Delgado"

    def test_two_words_are_left_alone(self, cleaner):
        assert BylineCleaner.drop_own_username("John Hacker") == "John Hacker"


class TestTheOrderOfTheRules:
    def test_the_credit_is_dropped_before_anything_salvages_it(self, cleaner):
        """Every rule after the photo one tries to make a name out of what it
        is given. If the masthead trim ran first, `Cameron Montemayor File
        Photo` would survive as a byline."""
        source = (BylineCleaner.__module__, BylineCleaner.clean_byline.__qualname__)
        assert source  # the behavioural assertion is the next line
        assert cleaner.clean_byline("Cameron Montemayor File Photo") == []

    def test_clean_names_pass_through_all_four(self, cleaner):
        for name in ("Emily Skidmore", "Jeffrey Fox", "Mary Clare Jalonick"):
            assert cleaner.clean_byline(name) == [name]
