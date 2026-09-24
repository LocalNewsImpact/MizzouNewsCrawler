"""A nameplate is not a domain.

`sources` carried one row for two things: a domain we crawl and a newspaper that
exists. Where they coincide nothing complains; where they do not, every count
drawn off the table is wrong and the error is invisible — `myleaderpaper.com` is
one row standing for four Jefferson County papers, which is why that county
reads 6 newspapers in two directories and 1 in ours.

These tests hold the two tables to the shapes that make the distinction useful:
several nameplates on a domain, several domains over a nameplate's life, a
nameplate that is a section of a site, a nameplate with no domain at all, and
one current answer to "where does this publish".
"""

import datetime
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.models import Base, Nameplate, NameplateDomain, Source


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


def _source(session, host, name):
    row = Source(id=str(uuid.uuid4()), host=host, host_norm=host, canonical_name=name)
    session.add(row)
    session.flush()
    return row


def _nameplate(session, name, **kwargs):
    row = Nameplate(id=str(uuid.uuid4()), name=name, **kwargs)
    session.add(row)
    session.flush()
    return row


def _published(session, nameplate, source, **kwargs):
    kwargs.setdefault("basis", "directory")
    row = NameplateDomain(
        id=str(uuid.uuid4()),
        nameplate_id=nameplate.id,
        source_id=source.id,
        **kwargs,
    )
    session.add(row)
    session.flush()
    return row


class TestSeveralNameplatesOnOneDomain:
    """The case the table exists for. `myleaderpaper.com` is ONE source row
    named "Leader"; the Missouri Press directory and the Blue Book between them
    name four papers behind it."""

    def test_four_papers_can_share_a_domain(self, session):
        leader = _source(session, "myleaderpaper.com", "Leader")
        for name in (
            "Arnold-Imperial Leader",
            "Eureka Leader",
            "Jefferson County Leader",
            "West Side Leader",
        ):
            _published(session, _nameplate(session, name), leader)
        assert (
            session.query(NameplateDomain).filter_by(source_id=leader.id).count() == 4
        )

    def test_the_county_count_is_of_nameplates_not_domains(self, session):
        """One source row in Jefferson County is four newspapers there. Counting
        sources said 1 against the directories' 6."""
        leader = _source(session, "myleaderpaper.com", "Leader")
        for name in ("Arnold-Imperial Leader", "Eureka Leader", "West Side Leader"):
            _published(session, _nameplate(session, name, fips="29099"), leader)
        assert session.query(Nameplate).filter_by(fips="29099").count() == 3


class TestANameplateWeCannotReach:
    def test_a_nameplate_needs_no_domain(self, session):
        """Eight Missouri papers publish only a flipbook replica and one only on
        Facebook. They are newspapers we know about and cannot collect, and
        absent is not the same as unknown."""
        paper = _nameplate(session, "Mound City News", status="replica_only")
        assert paper.domains == []
        assert session.query(Nameplate).filter_by(status="replica_only").count() == 1

    @pytest.mark.parametrize(
        "status", ["publishing", "print_only", "replica_only", "social_only", "closed"]
    )
    def test_the_statuses_that_say_why_we_cannot_collect(self, session, status):
        _nameplate(session, f"Paper {status}", status=status)
        session.commit()

    def test_a_status_that_is_not_one_is_refused(self, session):
        with pytest.raises(IntegrityError):
            _nameplate(session, "Nowhere Gazette", status="probably_fine")


class TestANameplateThatMoves:
    """`lincolnnewsnow.com` now serves only a notice that its three papers have
    moved to their own sites. The move is a closed row and an open one."""

    def test_a_move_is_two_rows(self, session):
        old = _source(session, "lincolnnewsnow.com", "Lincoln News Now")
        new = _source(session, "lincolncountyjournal.com", "Lincoln County Journal")
        paper = _nameplate(session, "Lincoln County Journal")
        _published(
            session,
            paper,
            old,
            from_date=datetime.date(2020, 1, 1),
            to_date=datetime.date(2026, 6, 1),
        )
        _published(
            session,
            paper,
            new,
            from_date=datetime.date(2026, 6, 1),
            basis="redirect",
        )
        current = [d for d in paper.domains if d.to_date is None]
        assert len(current) == 1
        assert current[0].source_id == new.id
        assert len(paper.domains) == 2

    def test_a_nameplate_has_only_one_current_domain(self, session):
        """Two open rows would be two answers to "where does this publish"."""
        paper = _nameplate(session, "Troy Free Press")
        host = _source(session, "troyfreepress.com", "Troy Free Press")
        _published(session, paper, host)
        with pytest.raises(IntegrityError):
            _published(session, paper, host)

    def test_a_nameplate_may_return_to_a_domain_it_left(self, session):
        paper = _nameplate(session, "Wandering Register")
        host = _source(session, "example.com", "Example")
        _published(session, paper, host, to_date=datetime.date(2024, 1, 1))
        _published(session, paper, host)
        session.commit()
        assert len(paper.domains) == 2

    def test_a_run_cannot_end_before_it_starts(self, session):
        paper = _nameplate(session, "Backwards Bugle")
        host = _source(session, "backwards.com", "Backwards")
        with pytest.raises(IntegrityError):
            _published(
                session,
                paper,
                host,
                from_date=datetime.date(2026, 1, 1),
                to_date=datetime.date(2025, 1, 1),
            )


class TestANameplateThatIsASection:
    def test_a_path_records_part_of_a_site(self, session):
        """`higginsvilleadvance.com` redirects into
        `lafayettemonews.com/category/higginsville-advance/`. The nameplate is
        real, its own domain is a signpost, its articles are under a path."""
        host = _source(session, "lafayettemonews.com", "Lafayette Mo News")
        advance = _nameplate(session, "Higginsville Advance")
        lexington = _nameplate(session, "Lexington News")
        _published(
            session,
            advance,
            host,
            path="/category/higginsville-advance/",
            basis="redirect",
        )
        _published(session, lexington, host, path="/category/lexington-news/")
        session.commit()
        assert {d.path for d in host_rows(session, host)} == {
            "/category/higginsville-advance/",
            "/category/lexington-news/",
        }


def host_rows(session, source):
    return session.query(NameplateDomain).filter_by(source_id=source.id).all()


class TestHowTheClaimWasReached:
    """`basis` is the same idea as `review/mopress.py`'s: a link proven by a
    redirect is worth more than one inferred from two directories agreeing, and
    a reviewer settling a conflict has to see which they hold."""

    @pytest.mark.parametrize("basis", ["redirect", "masthead_on_page", "directory"])
    def test_the_bases_a_machine_can_establish(self, session, basis):
        _published(
            session,
            _nameplate(session, f"Paper {basis}"),
            _source(session, f"{basis}.com", basis),
            basis=basis,
        )
        session.commit()

    def test_a_basis_that_is_not_one_is_refused(self, session):
        paper = _nameplate(session, "Hunch Herald")
        host = _source(session, "hunch.com", "Hunch")
        with pytest.raises(IntegrityError):
            _published(session, paper, host, basis="seemed-right")

    def test_a_decision_must_name_who_made_it(self, session):
        """`decided` overrules the evidence, so it is signed."""
        paper = _nameplate(session, "Overruled Observer")
        host = _source(session, "overruled.com", "Overruled")
        with pytest.raises(IntegrityError):
            _published(session, paper, host, basis="decided")

    def test_a_signed_decision_is_accepted(self, session):
        _published(
            session,
            _nameplate(session, "Signed Sentinel"),
            _source(session, "signed.com", "Signed"),
            basis="decided",
            decided_by="damon",
            evidence="the masthead on the printed edition",
        )
        session.commit()


class TestSourcesIsUnchanged:
    def test_a_source_still_stands_alone(self, session):
        """The tables are beside `sources`, not instead of it. A domain with no
        nameplate recorded is every source we have today."""
        host = _source(session, "columbiamissourian.com", "Columbia Missourian")
        session.commit()
        assert host.id
        assert session.query(NameplateDomain).count() == 0
