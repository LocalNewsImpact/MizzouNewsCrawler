"""A decision can go stale.

A decided byline is never asked about again, which assumes the answer stays
true. It does not: `cross_owner` is read through `owner_groups` and
`sources.owner`, so an answer is only as good as the ownership recorded the
day it was given. Correcting seven NEMOnews papers from seven unrelated
owners, and three owner typos, left 50 Mizzou bylines still crossing
ownership -- every one of them already decided and therefore invisible.

Deletion would re-open the question and destroy the answer, including
`applied_at`, the record that the decision already reached `articles.author`.
"""

import datetime
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from src.models import Base, BylineNormalization
from src.services import byline_review as br


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


def _decision(session, raw, names, **kwargs):
    row = BylineNormalization(
        id=str(uuid.uuid4()),
        dataset_id="d-mo",
        raw_byline=raw,
        canonical_names=names,
        decision=kwargs.pop("decision", "accept"),
        decided_by="damon",
        **kwargs,
    )
    session.add(row)
    session.flush()
    return row


class TestAStaleDecisionReturnsToTheQueue:
    def test_a_decided_string_is_not_asked_again(self, session):
        _decision(session, "Joey Schneider", ["Joey Schneider"])
        session.commit()
        assert "Joey Schneider" in br.load_decisions(session, "d-mo")

    def test_a_stale_one_is(self, session):
        """`load_decisions` is what the queue consults to skip a string."""
        _decision(
            session,
            "Joey Schneider",
            ["Joey Schneider"],
            stale_at=datetime.datetime(2026, 9, 24),
            stale_reason="ownership corrected",
        )
        session.commit()
        assert "Joey Schneider" not in br.load_decisions(session, "d-mo")

    def test_the_answer_is_kept_not_deleted(self, session):
        """The whole point. The row survives with its answer, its author and
        its `applied_at` -- so a re-review knows the corpus already carries
        it, which deletion cannot say."""
        _decision(
            session,
            "Joey Schneider",
            ["Joey Schneider"],
            applied_at=datetime.datetime(2026, 9, 20),
            articles_updated=77,
            stale_at=datetime.datetime(2026, 9, 24),
            stale_reason="ownership corrected",
        )
        session.commit()
        prior = br.load_prior_answers(session, "d-mo")["Joey Schneider"]
        assert prior["decision"] == "accept"
        assert prior["names"] == ["Joey Schneider"]
        assert prior["decided_by"] == "damon"
        assert prior["applied"] is True
        assert prior["stale_reason"] == "ownership corrected"

    def test_a_live_decision_is_not_a_prior_answer(self, session):
        """`load_prior_answers` is for the strings being asked again, and a
        settled one is not being asked."""
        _decision(session, "Settled Name", ["Settled Name"])
        session.commit()
        assert br.load_prior_answers(session, "d-mo") == {}


class TestMarkingStale:
    def test_it_marks_the_named_strings(self, session):
        _decision(session, "A Name", ["A Name"])
        _decision(session, "B Name", ["B Name"])
        session.commit()
        assert br.mark_stale(session, "d-mo", ["A Name"], "owners changed") == 1
        session.commit()
        assert "A Name" not in br.load_decisions(session, "d-mo")
        assert "B Name" in br.load_decisions(session, "d-mo")

    def test_a_string_with_no_decision_is_not_counted(self, session):
        """It is already in the queue; marking it is not an error and not
        a change."""
        assert br.mark_stale(session, "d-mo", ["Never Decided"], "why") == 0

    def test_running_it_twice_does_not_rewrite_the_reason(self, session):
        """A reviewer is about to read that reason, and the count reported
        must be of what actually changed."""
        _decision(session, "A Name", ["A Name"])
        session.commit()
        assert br.mark_stale(session, "d-mo", ["A Name"], "first reason") == 1
        session.commit()
        assert br.mark_stale(session, "d-mo", ["A Name"], "second reason") == 0
        session.commit()
        prior = br.load_prior_answers(session, "d-mo")["A Name"]
        assert prior["stale_reason"] == "first reason"

    def test_a_dry_run_writes_nothing(self, session):
        _decision(session, "A Name", ["A Name"])
        session.commit()
        assert br.mark_stale(session, "d-mo", ["A Name"], "why", dry_run=True) == 1
        assert "A Name" in br.load_decisions(session, "d-mo")

    def test_nothing_named_is_nothing_done(self, session):
        assert br.mark_stale(session, "d-mo", [], "why") == 0


class TestSettlingItAgain:
    def test_the_old_answer_can_simply_stand(self, session):
        """The reviewer looked again and nothing changed. That is not a new
        decision; it is the end of a question."""
        _decision(
            session,
            "A Name",
            ["A Name"],
            stale_at=datetime.datetime(2026, 9, 24),
            stale_reason="ownership corrected",
        )
        session.commit()
        assert br.settled(session, "d-mo", ["A Name"]) == 1
        session.commit()
        assert "A Name" in br.load_decisions(session, "d-mo")
        assert br.load_prior_answers(session, "d-mo") == {}

    def test_settling_a_live_decision_changes_nothing(self, session):
        _decision(session, "A Name", ["A Name"])
        session.commit()
        assert br.settled(session, "d-mo", ["A Name"]) == 0


class TestTheColumns:
    def test_they_are_optional(self, session):
        """Every decision that exists was made before this, so a NOT NULL
        column could not be added at all."""
        columns = inspect(BylineNormalization).columns
        assert columns["stale_at"].nullable is True
        assert columns["stale_reason"].nullable is True

    def test_the_migration_chains_from_the_credit_column(self):
        from pathlib import Path

        body = (
            Path(__file__).resolve().parent.parent
            / "alembic/versions/e3f4a5b6c7d8_a_decision_can_go_stale.py"
        ).read_text()
        assert 'down_revision = "d2e3f4a5b6c7"' in body
        assert "stale_at" in body and "stale_reason" in body

    def test_the_decision_survives_a_round_trip(self, session):
        """Marked stale, then settled: the answer is the one originally
        given, not a rewrite of it."""
        _decision(session, "A Name", ["Different Spelling"], decision="fix")
        session.commit()
        br.mark_stale(session, "d-mo", ["A Name"], "why")
        session.commit()
        br.settled(session, "d-mo", ["A Name"])
        session.commit()
        row = session.execute(
            text("SELECT decision, canonical_names FROM byline_normalizations")
        ).fetchone()
        assert row[0] == "fix"
        assert "Different Spelling" in str(row[1])
