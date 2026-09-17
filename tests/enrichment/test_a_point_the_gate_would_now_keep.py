"""`reground` only removes. Nothing runs the other way.

When the evidence improves -- a school the gazetteer had never heard of,
a short form no story spells out -- the places the model had already
designated stay refused, because the decision was taken at enrichment and
nothing revisits it.

Re-enriching would revisit it and is the wrong tool: asked the same
question twice with the same prompt, the model moved 34 of 167 points and
demoted 32 from a city to the county around it. The churn is larger than
the effect.

This asks the model nothing. The claim is stored with its geoid; the only
thing that changed is whether the gate can defend it.
"""

import pytest

from src.enrichment import restore_points


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)
        self.rowcount = len(self._rows)

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def __init__(self, candidates, institutions=()):
        self.candidates = candidates
        self.institutions = list(institutions)
        self.writes = []
        self.committed = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        if "UPDATE article_enrichment" in sql:
            self.writes.append(params)
            return _Result([params])
        if "SELECT DISTINCT np.place_name" in sql:
            return _Result([(p,) for p in self.institutions])
        return _Result(self.candidates)

    def commit(self):
        self.committed += 1


def _claim(article_id="a1", place="Columbia", content="", title=""):
    return {
        "article_id": article_id,
        "place": place,
        "full_name": f"{place}, MO",
        "geoid": "2915670",
        "geoid_level": "place",
        "lat": 38.9,
        "lon": -92.3,
        "title": title,
        "content": content,
        "publication_city": "Columbia",
    }


class TestWhatIsRestored:
    def test_a_place_the_story_names(self):
        s = _Session([_claim(content="The council met in Columbia on Tuesday.")])
        assert restore_points.restore(s, dry_run=True)["named"] == 1

    def test_a_place_an_institution_sits_in(self):
        """The Battle High School case: the story never says Columbia."""
        s = _Session(
            [_claim(content="Battle High School hosted the meet.")],
            institutions=["Columbia"],
        )
        counts = restore_points.restore(s, dry_run=True)
        assert counts["institution"] == 1 and counts["named"] == 0

    def test_a_place_with_no_support_is_left_alone(self):
        s = _Session([_claim(content="A quiet week for the team.")])
        assert restore_points.restore(s, dry_run=True)["candidates"] == 0


class TestOneAnswerPerArticle:
    def test_the_first_accepted_claim_wins(self):
        """A second point is a second answer to a question that has one."""
        s = _Session(
            [
                _claim(place="Columbia", content="Columbia and Ashland met."),
                _claim(place="Ashland", content="Columbia and Ashland met."),
            ],
            institutions=[],
        )
        found = restore_points.restorable(s)
        assert [r["place"] for r in found] == ["Columbia"]


class TestWriting:
    def test_a_dry_run_writes_nothing(self):
        s = _Session([_claim(content="Columbia hosted it.")])
        result = restore_points.restore(s, dry_run=True)
        assert result["written"] == 0 and not s.writes and s.committed == 0

    def test_the_write_records_how_it_was_kept(self):
        """`restored` marks a row this pass wrote, and `point_support` says
        WHICH clause kept it -- as the enrichment write path does."""
        s = _Session(
            [_claim(content="Battle High School hosted.")], institutions=["Columbia"]
        )
        restore_points.restore(s, dry_run=False)
        assert s.writes[0]["method"] == "restored"
        assert s.writes[0]["support"] == "institution"
        assert s.writes[0]["geoid"] == "2915670"
        assert s.committed == 1

    def test_the_limit_is_honoured(self):
        s = _Session(
            [_claim(article_id=f"a{i}", content="Columbia hosted.") for i in range(5)]
        )
        assert restore_points.restore(s, dry_run=True, limit=2)["candidates"] == 2
