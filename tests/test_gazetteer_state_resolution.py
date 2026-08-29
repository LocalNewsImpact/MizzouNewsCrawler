"""A gazetteer is only as good as the state it is built in.

The Mizzou dataset is a list of publishers who *cover* Missouri, not a
list of publishers who *sit* in Missouri: the Kansas City metro spans
the state line, so KMBZ (Mission, KS) and Dos Mundos (Overland Park, KS)
are legitimately in it. When the builder defaulted a missing state to
"MO" it did not fail loudly -- the Census place lookup missed, Nominatim
fuzzy-matched "Mission, Johnson, MO", and the gazetteer came out
centred eight miles from the newsroom, full of the wrong town's schools
and churches.

No state at all is the more common case: 896 of 901 Vermont sources
arrive without one. Guessing is what these tests forbid.
"""

from scripts.populate_gazetteer import resolve_source_state


def test_the_source_state_wins():
    src = {"metadata": {"state": "KS"}, "city": "Mission"}
    assert resolve_source_state(src, dataset_default="MO") == "KS"


def test_the_dataset_default_fills_a_gap():
    src = {"metadata": {}, "city": "Columbia"}
    assert resolve_source_state(src, dataset_default="MO") == "MO"


def test_no_state_anywhere_resolves_to_nothing():
    """The caller skips on "" -- it must never receive a guess."""
    src = {"metadata": {}, "city": "Montpelier"}
    assert resolve_source_state(src, dataset_default="") == ""
    assert resolve_source_state({"city": "Montpelier"}, dataset_default="") == ""


def test_a_missing_metadata_key_is_not_an_error():
    assert resolve_source_state({}, dataset_default="WA") == "WA"
    assert resolve_source_state({"metadata": None}, dataset_default="WA") == "WA"


def test_the_state_is_not_defaulted_to_missouri_anywhere_in_the_builder():
    """The specific regression: a hardcoded "MO" fallback.

    It lived in two centroid paths and would have geocoded every
    stateless Vermont source into Missouri on the next upload.
    """
    from pathlib import Path

    src_text = Path("scripts/populate_gazetteer.py").read_text()
    assert 'or "MO"' not in src_text
    assert 'state = "MO"' not in src_text
