"""A dash in a byline means one of two things, and the tail decides which.

"Matthew Defranks - Nathan Mills" is two reporters. "John Garlock - Ktvo"
is a reporter and the station that employs him. Neither was handled:
both reached the column whole, so the first counted as one author with a
strange name and the second carried an outlet into a name field.

Found by reading the 177 byline values a name-shape rule rejected. 116
of them were real names -- 24 several reporters joined by a dash, 37 a
name with an outlet appended, 43 a name with a trailing separator and
nothing after it. A review queue would have asked about all of them; the
fix is computable, so it belongs here instead.

Tilde and "//" already split correctly. Dash did not.
"""

import pytest

from src.utils.byline_cleaner import BylineCleaner

# No logging.disable here. Called at module scope it is global and lasts
# the whole session, so caplog captured nothing in every test that ran
# afterwards -- which is why test_extraction_loop_resilience failed in
# the full suite and passed on its own.


@pytest.fixture
def cleaner():
    return BylineCleaner(enable_telemetry=False)


# --- several reporters ------------------------------------------------------


def test_two_reporters_joined_by_a_dash(cleaner):
    assert cleaner.clean_byline("Matthew Defranks - Nathan Mills") == [
        "Matthew Defranks",
        "Nathan Mills",
    ]


def test_four_reporters_joined_by_dashes(cleaner):
    assert cleaner.clean_byline(
        "David Carson - Christian Gooden - Liz Rymarev - Laurie Skrivan"
    ) == ["David Carson", "Christian Gooden", "Liz Rymarev", "Laurie Skrivan"]


# --- a name with an outlet appended -----------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("John Garlock - Ktvo", ["John Garlock"]),
        ("Jorge Borges - Local", ["Jorge Borges"]),
        ("Tom Davis - Standard", ["Tom Davis"]),
    ],
)
def test_the_outlet_does_not_reach_the_name_field(cleaner, raw, expected):
    assert cleaner.clean_byline(raw) == expected


# --- a separator with nothing after it --------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["Cecilia Velazquez -", "Courtney Waters --", "Bob Miller -", "Julia Thomas -"],
)
def test_a_trailing_separator_is_removed(cleaner, raw):
    cleaned = cleaner.clean_byline(raw)
    assert cleaned and not cleaned[0].rstrip().endswith("-")


# --- what must not change ---------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Jane Smith", ["Jane Smith"]),
        ("Jane Smith and John Doe", ["Jane Smith", "John Doe"]),
        ("Jane Smith, John Doe", ["Jane Smith", "John Doe"]),
    ],
)
def test_bylines_that_already_worked_still_work(cleaner, raw, expected):
    assert cleaner.clean_byline(raw) == expected


# --- the name shape, which decides co-author from outlet ---------------------


@pytest.mark.parametrize(
    "name",
    [
        "Melissa Hernandez de la Cruz",
        "Juan de la Cruz",
        "Maria de los Angeles Rodriguez",
        "Emily van de Riet",
        "Vincent van der Berg",
        "Oscar de la Renta",
    ],
)
def test_particles_do_not_make_a_name_unreadable(name):
    """A rule that rejects real names is worse than no rule. `los` was
    missing from the first draft, which would have discarded
    'Maria de los Angeles Rodriguez' as an outlet."""
    assert BylineCleaner._looks_like_a_person(name)


@pytest.mark.parametrize("value", ["Ktvo", "Admin", "Standard", "Fr", ""])
def test_a_single_word_is_not_a_person(value):
    assert not BylineCleaner._looks_like_a_person(value)


def test_tilde_is_left_to_the_existing_logic(cleaner):
    """It already split these correctly and dropped the outlet against
    the publication list. Taking them over replaced a working path with
    one that keeps "Standard Democrat" as a co-author wherever that list
    is not loaded."""
    assert (
        BylineCleaner.normalise_dash_separators("Leonna Heuring~Standard Democrat")
        == "Leonna Heuring~Standard Democrat"
    )


def test_a_byline_it_cannot_read_is_left_alone(cleaner):
    """Left for the existing logic rather than emptied by a rule that did
    not understand it."""
    assert BylineCleaner.normalise_dash_separators("Knem/Knmo") == "Knem/Knmo"
