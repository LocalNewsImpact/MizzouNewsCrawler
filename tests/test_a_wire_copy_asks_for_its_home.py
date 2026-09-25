"""A wire copy asks for its home.

Ruling a newsroom's copies `wire` takes them out of the export, and without a
HOME ruling nothing records whose reporting they were. Twenty bylines were
ruled before the HOME dropdown existed: decided, carrying no signal, and so
invisible to the queue however long they waited.

The signal is different from every other in one way that matters -- it
survives a decision. "Is this a real name" and "which newsroom is home" are
independent questions, and a byline whose string is settled can still owe a
home.
"""

import datetime
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models import Article, Base, CandidateLink, Source
from src.services import byline_review as br

# (byline, host, owner, articles) -- the shape `dataset_rows` returns.
ROWS = [
    ("Steph Quinn", "missouriindependent.com", "States Newsroom", 40),
    ("Rudi Keller", "missouriindependent.com", "States Newsroom", 30),
]


class TestTheSignalIsDeclared:
    def test_it_has_a_key_and_a_label(self):
        assert br.WIRE_UNCREDITED == "wire_uncredited"
        assert br.SIGNAL_LABELS[br.WIRE_UNCREDITED] == (
            "Wire copies with no home newsroom credited"
        )

    def test_it_is_asked_last(self):
        """The name is usually fine; only the credit is owed. So it waits
        behind every question about whether the string is right."""
        assert br.SIGNAL_ORDER[-1] == br.WIRE_UNCREDITED

    def test_it_is_scoped_to_the_active_period(self):
        """Every wire copy ever captured puts 227 bylines in the queue;
        March 2026 puts 78, and March is what the analysis reads."""
        assert br.CREDIT_PERIOD == ("2026-03-01", "2026-04-01")


class TestItSurvivesADecision:
    """The one thing no other signal does."""

    def test_a_decided_name_owing_credit_is_asked_again(self):
        rows = br.review_rows(
            ROWS,
            decisions={"Steph Quinn": ["Steph Quinn"]},
            uncredited={"Steph Quinn"},
        )
        quinn = next(r for r in rows if r.raw == "Steph Quinn")
        assert quinn.decided is True
        assert quinn.signals == (br.WIRE_UNCREDITED,)
        assert quinn.needs_review

    def test_the_decision_is_kept_not_reopened(self):
        """Only the credit question comes back. The string answer stands, so
        the proposal is still the name the reviewer settled on."""
        rows = br.review_rows(
            ROWS,
            decisions={"Steph Quinn": ["Stephanie Quinn"]},
            uncredited={"Steph Quinn"},
        )
        quinn = next(r for r in rows if r.raw == "Steph Quinn")
        assert quinn.proposed == ("Stephanie Quinn",)

    def test_a_decided_name_owing_nothing_stays_quiet(self):
        """Every other decided row behaves exactly as before."""
        rows = br.review_rows(
            ROWS,
            decisions={"Rudi Keller": ["Rudi Keller"]},
            uncredited={"Steph Quinn"},
        )
        keller = next(r for r in rows if r.raw == "Rudi Keller")
        assert keller.signals == ()
        assert not keller.needs_review


class TestAnUndecidedName:
    def test_it_is_added_beside_the_other_signals(self):
        rows = br.review_rows(ROWS, uncredited={"Rudi Keller"})
        keller = next(r for r in rows if r.raw == "Rudi Keller")
        assert br.WIRE_UNCREDITED in keller.signals

    def test_a_name_owing_nothing_does_not_get_it(self):
        rows = br.review_rows(ROWS, uncredited={"Rudi Keller"})
        quinn = next(r for r in rows if r.raw == "Steph Quinn")
        assert br.WIRE_UNCREDITED not in quinn.signals

    def test_no_set_means_no_signal(self):
        """Callers that do not ask about credit see the queue unchanged."""
        for row in br.review_rows(ROWS):
            assert br.WIRE_UNCREDITED not in row.signals


class TestItReachesTheQueue:
    def test_candidates_passes_it_through(self):
        got = br.candidates(
            ROWS, decisions={"Steph Quinn": ["Steph Quinn"]}, uncredited={"Steph Quinn"}
        )
        assert "Steph Quinn" in {r.raw for r in got}


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


def _wire(session, source, author, day, credited_to=None):
    link = CandidateLink(
        id=str(uuid.uuid4()),
        source_id=source.id,
        source=source.host,
        url=f"https://{source.host}/{uuid.uuid4()}",
        dataset_id="d-mo",
    )
    session.add(link)
    session.flush()
    session.add(
        Article(
            id=str(uuid.uuid4()),
            candidate_link_id=link.id,
            dataset_id="d-mo",
            url=link.url,
            author=author,
            status="wire",
            publish_date=(
                datetime.datetime(2026, 3, day) if isinstance(day, int) else day
            ),
            syndicated_from_source_id=credited_to,
        )
    )
    session.flush()


class TestFindingTheNamesThatOwe:
    def _source(self, session, host):
        row = Source(id=str(uuid.uuid4()), host=host, host_norm=host)
        session.add(row)
        session.flush()
        return row

    def test_names_are_split_the_way_the_queue_splits_them(self, session):
        """A copy captured as "Rudi Keller and Steph Quinn" is both of
        theirs. Matching the whole string found neither, which is how a
        first count came out at 55 instead of 78."""
        carrier = self._source(session, "sedaliademocrat.com")
        _wire(session, carrier, "Rudi Keller and Steph Quinn", 10)
        session.commit()
        names = br.uncredited_wire_names(session, "d-mo")
        assert {"Rudi Keller", "Steph Quinn"} <= names

    def test_a_credited_copy_owes_nothing(self, session):
        """It clears itself: a HOME ruling writes the credit and the name
        leaves the queue."""
        home = self._source(session, "missouriindependent.com")
        carrier = self._source(session, "sedaliademocrat.com")
        _wire(session, carrier, "Steph Quinn", 10, credited_to=home.id)
        session.commit()
        assert "Steph Quinn" not in br.uncredited_wire_names(session, "d-mo")

    def test_outside_the_period_owes_nothing(self, session):
        """Jazsmin Halliburton has 37 uncredited copies, all before March,
        and is correctly not asked about."""
        carrier = self._source(session, "abc17news.com")
        _wire(session, carrier, "Jazsmin Halliburton", datetime.datetime(2026, 1, 5))
        session.commit()
        assert "Jazsmin Halliburton" not in br.uncredited_wire_names(session, "d-mo")

    def test_another_dataset_owes_nothing(self, session):
        carrier = self._source(session, "sedaliademocrat.com")
        _wire(session, carrier, "Steph Quinn", 10)
        session.commit()
        assert br.uncredited_wire_names(session, "some-other-dataset") == set()
