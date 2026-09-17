"""No survey will ever have them all, so a person has to be able to add one.

Missouri articles say `Tolton` 297 times, `Tolton Catholic` 25 and
`Tolton Catholic High School` 6. OSM records the school as `Father Tolton
Catholic High School` and the index held only that, so a story about the
school located nothing -- while the model named Columbia correctly in all
20 claims it made about it.

Some of that is fixable by rule. `Tolton` alone is not: indexing bare
surnames automatically is how `Battle` becomes a PERSON and `Clark` a
filling station. It takes somebody who knows the beat, and it takes a
record of who decided and why.
"""

import pytest

from src.pipeline.manual_gazetteer import Refused, add_place


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __iter__(self):
        return iter(self.__dict__.values())


class _Session:
    """Answers each execute in order; records the statements it was given."""

    def __init__(self, answers=None):
        self.answers = list(answers or [])
        self.statements = []
        self.params = []
        self.committed = 0

    def execute(self, statement, params=None):
        self.statements.append(str(statement))
        self.params.append(params or {})
        return _Result(self.answers.pop(0) if self.answers else [])

    def commit(self):
        self.committed += 1


def _place_known():
    """A geocoded Columbia, as the gazetteer holds it."""
    return [_Row(place_geoid="2915670", place_name="Columbia", county_geoid="29019")]


def _session_for_a_clean_add():
    return _Session(
        answers=[
            _place_known(),  # the place resolves
            [],  # nothing holds this name yet
            [],  # insert
            [],  # reindex
            [_Row(place_count=1, place_name="Columbia")],  # what the index now says
        ]
    )


class TestWhatIsRefused:
    def test_a_description_is_not_a_name(self):
        """The same guard the extracts apply: a name whose every word
        names a KIND of place would match in every town."""
        with pytest.raises(Refused, match="description"):
            add_place(
                _Session(),
                state="MO",
                name="High School",
                place="Columbia",
                added_by="damon",
            )

    def test_a_place_the_gazetteer_has_not_geocoded(self):
        """A manual entry may point at a town the corpus knows. It may not
        invent one -- the index answers with a place geoid."""
        with pytest.raises(Refused, match="not a place"):
            add_place(
                _Session(answers=[[]]),
                state="MO",
                name="Tolton Catholic High School",
                place="Nowhereville",
                added_by="damon",
            )

    def test_an_entry_with_no_author(self):
        with pytest.raises(Refused, match="who added it"):
            add_place(
                _Session(),
                state="MO",
                name="Tolton Catholic High School",
                place="Columbia",
                added_by="",
            )

    @pytest.mark.parametrize("field", ["state", "name", "place"])
    def test_the_required_fields(self, field):
        kwargs = {
            "state": "MO",
            "name": "Tolton Catholic High School",
            "place": "Columbia",
            "added_by": "damon",
        }
        kwargs[field] = ""
        with pytest.raises(Refused, match="required"):
            add_place(_Session(), **kwargs)

    def test_adding_the_same_name_twice(self):
        session = _Session(
            answers=[
                _place_known(),
                [
                    _Row(
                        name="Tolton Catholic High School",
                        place_name="Columbia",
                        osm_type="manual",
                    )
                ],
            ]
        )
        with pytest.raises(Refused, match="already added by hand"):
            add_place(
                session,
                state="MO",
                name="Tolton Catholic High School",
                place="Columbia",
                added_by="damon",
            )


class TestWhatIsRecorded:
    def test_the_entry_resolves_to_the_place(self):
        added = add_place(
            _session_for_a_clean_add(),
            state="MO",
            name="Tolton Catholic High School",
            place="Columbia",
            added_by="damon",
            note="articles say Tolton",
        )
        assert added["resolves_to"] == "Columbia"
        assert added["ambiguous"] is False

    def test_who_added_it_and_why_are_kept(self):
        session = _session_for_a_clean_add()
        add_place(
            session,
            state="MO",
            name="Tolton Catholic High School",
            place="Columbia",
            added_by="damon",
            note="articles say Tolton",
        )
        insert = next(
            p
            for s, p in zip(session.statements, session.params, strict=True)
            if "INSERT INTO gazetteer_features" in s
        )
        assert "damon" in insert["tags"]
        assert "articles say Tolton" in insert["tags"]

    def test_it_is_written_as_an_ordinary_feature(self):
        """So the index, the gate and the matcher need to know nothing
        about it -- only its source says a person put it there."""
        session = _session_for_a_clean_add()
        add_place(
            session,
            state="MO",
            name="Tolton Catholic High School",
            place="Columbia",
            added_by="damon",
        )
        insert = next(
            p
            for s, p in zip(session.statements, session.params, strict=True)
            if "INSERT INTO gazetteer_features" in s
        )
        assert insert["source"] == "manual"
        assert insert["place_geoid"] == "2915670"

    def test_only_that_name_is_reindexed(self):
        """A curator adding one school should not pay for a rebuild of
        every name in the state, nor have to remember to run one."""
        session = _session_for_a_clean_add()
        add_place(
            session,
            state="MO",
            name="Tolton Catholic High School",
            place="Columbia",
            added_by="damon",
        )
        reindex = next(
            p
            for s, p in zip(session.statements, session.params, strict=True)
            if "INSERT INTO gazetteer_name_places" in s
        )
        assert reindex["name_norm"] == "tolton catholic high school"
        assert reindex["state"] == "MO"

    def test_the_reindex_counts_unplaced_bearers(self):
        """The same rule the full rebuild uses, or a manual entry could
        make a name look unambiguous that the rebuild calls ambiguous."""
        session = _session_for_a_clean_add()
        add_place(
            session,
            state="MO",
            name="Tolton Catholic High School",
            place="Columbia",
            added_by="damon",
        )
        sql = next(
            s for s in session.statements if "INSERT INTO gazetteer_name_places" in s
        )
        assert "FILTER (WHERE place_geoid IS NULL)" in sql

    def test_a_name_already_borne_elsewhere_is_reported_ambiguous(self):
        """The entry is kept -- the next reader should see it was
        considered -- but it answers nothing until that is resolved."""
        session = _Session(
            answers=[
                _place_known(),
                [],
                [],
                [],
                [_Row(place_count=2, place_name=None)],
            ]
        )
        added = add_place(
            session,
            state="MO",
            name="Bethel Church",
            place="Columbia",
            added_by="damon",
        )
        assert added["ambiguous"] is True
        assert added["resolves_to"] is None

    def test_it_is_committed(self):
        session = _session_for_a_clean_add()
        add_place(
            session,
            state="MO",
            name="Tolton Catholic High School",
            place="Columbia",
            added_by="damon",
        )
        assert session.committed == 1
