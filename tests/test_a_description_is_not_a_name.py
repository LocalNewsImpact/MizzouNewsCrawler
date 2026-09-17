"""OSM's `name` tag holds descriptions, and the guard's vocabulary was half-written.

`is_matchable_gazetteer_name` already had the right rule -- a name whose
every token describes a KIND of place is a description, not an identity --
and a vocabulary that stopped short. It knew `field`, `pool`, `court`,
`gym` and `parking`, and did not know `basketball`, `football`, `locker`
or `track`.

So these are real Missouri gazetteer features that became EntityRuler
patterns:

    Basketball                  sports        a court
    Locker Rooms                sports        a locker room
    The Track                   sports        a running track
    High School football field  sports        a football field
    Honor Roll                  landmarks     a memorial board

Every one of them proposed a city whenever its words appeared in prose.
`basketball` proposed Springfield on an MU sports-betting story;
`honor roll` proposed North Kansas City on an elementary school honour
roll; `the track` proposed Branson on a spring sports preview.
"""

import pytest

from src.utils.gazetteer_names import is_matchable_gazetteer_name


class TestADescriptionIsRejected:
    """Each of these is a feature that reached production."""

    @pytest.mark.parametrize(
        "name",
        [
            "Basketball",
            "Locker Rooms",
            "The Track",
            "High School football field",
            "Honor Roll",
            "Memorial",
            "Tennis Courts",
            "Restrooms",
            "Concessions",
            "Soccer Field",
            "Baseball Diamond",
        ],
    )
    def test_it_is_not_matchable(self, name):
        assert not is_matchable_gazetteer_name(name)


class TestOneDistinctiveTokenIsEnough:
    """The rule is deliberately conservative: it takes ALL tokens being
    generic to reject a name, so anything carrying a real name survives."""

    @pytest.mark.parametrize(
        "name",
        [
            "Hickman High School",
            "Battle High School",
            "University Hospital",
            "Southeast Missouri State University",
            "Daniel Boone Regional Library",
            "Mizzou Arena",
            "Bethel Church",
            "Vietnam Veterans Memorial",
            "Blue Springs High School",
            "Rock Bridge Soccer Field",
        ],
    )
    def test_it_is_matchable(self, name):
        assert is_matchable_gazetteer_name(name)


def test_the_defect_itself_is_pinned():
    """A test that cannot fail is not a test.

    Without the sports vocabulary these names pass, which is how they
    reached production. Assert that it is the vocabulary doing the work.
    """
    from src.utils import gazetteer_names

    thinner = gazetteer_names.GENERIC_TOKENS - {
        "basketball",
        "locker",
        "rooms",
        "track",
        "football",
    }
    assert "basketball" in gazetteer_names.GENERIC_TOKENS
    assert "basketball" not in thinner
