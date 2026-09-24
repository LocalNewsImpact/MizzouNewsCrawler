"""A wire copy names the newsroom it came from.

`status = 'wire'` says a story is not this newsroom's reporting and stops
there, so a wire ruling only ever subtracts: the copies leave the export and
both byline reports, and nobody is credited. Steph Quinn's 307 wire copies
across 36 Missouri domains are the Missouri Independent's work.

These tests hold the column to the shape that makes the claim safe: optional,
pointing at a newsroom we hold, and never at the copy's own.
"""

import uuid

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from src.models import Article, Base, CandidateLink, Source


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as s:
        yield s


def _source(session, host):
    row = Source(id=str(uuid.uuid4()), host=host, host_norm=host, canonical_name=host)
    session.add(row)
    session.flush()
    return row


def _article(session, source, url, **kwargs):
    link = CandidateLink(
        id=str(uuid.uuid4()), source_id=source.id, source=source.host, url=url
    )
    session.add(link)
    session.flush()
    row = Article(id=str(uuid.uuid4()), candidate_link_id=link.id, url=url, **kwargs)
    session.add(row)
    session.flush()
    return row


class TestTheCopyCarriesItsOrigin:
    def test_a_wire_copy_can_name_the_newsroom_it_came_from(self, session):
        home = _source(session, "missouriindependent.com")
        carrier = _source(session, "www.sedaliademocrat.com")
        copy = _article(
            session,
            carrier,
            "https://www.sedaliademocrat.com/a",
            author="Steph Quinn",
            status="wire",
            syndicated_from_source_id=home.id,
        )
        session.commit()
        assert copy.syndicated_from_source_id == home.id

    def test_what_a_newsroom_syndicated_is_one_query(self, session):
        """The question the column exists for. Counting sources said nothing:
        the copies were `wire` and the origin was written nowhere."""
        home = _source(session, "missouriindependent.com")
        for i, host in enumerate(
            ("www.sedaliademocrat.com", "krcgtv.com", "www.newstribune.com")
        ):
            _article(
                session,
                _source(session, host),
                f"https://{host}/{i}",
                status="wire",
                syndicated_from_source_id=home.id,
            )
        session.commit()
        carried = (
            session.query(Article)
            .filter_by(syndicated_from_source_id=home.id, status="wire")
            .count()
        )
        assert carried == 3

    def test_a_story_nobody_has_claimed_is_null(self, session):
        """Null is "not claimed", which is not the same as "no origin". Most
        of the corpus is wire nobody has ruled."""
        carrier = _source(session, "krcgtv.com")
        copy = _article(session, carrier, "https://krcgtv.com/a", status="wire")
        session.commit()
        assert copy.syndicated_from_source_id is None

    def test_local_reporting_carries_no_origin(self, session):
        home = _source(session, "missouriindependent.com")
        story = _article(
            session,
            home,
            "https://missouriindependent.com/a",
            author="Steph Quinn",
            status="enriched",
        )
        session.commit()
        assert story.syndicated_from_source_id is None


class TestTheColumnIsOptionalAndIndexed:
    def test_it_is_nullable(self, session):
        """Every article that exists today has no origin, so a NOT NULL column
        could not be added at all."""
        column = inspect(Article).columns["syndicated_from_source_id"]
        assert column.nullable is True

    def test_it_is_indexed(self, session):
        """`what did this newsroom syndicate` reads by origin, not by
        article, and the corpus is millions of rows."""
        column = inspect(Article).columns["syndicated_from_source_id"]
        assert column.index is True

    def test_it_points_at_a_newsroom_we_hold(self, session):
        column = inspect(Article).columns["syndicated_from_source_id"]
        assert {fk.target_fullname for fk in column.foreign_keys} == {"sources.id"}


class TestTheMigrationChainsFromTheNameplateHead:
    """A second head is the failure that passes every test and then refuses to
    deploy, because `alembic upgrade head` cannot choose between two."""

    def _migration(self):
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "alembic/versions/d2e3f4a5b6c7_a_wire_copy_names_the_newsroom_it_came_from.py"
        )
        return path.read_text()

    def test_it_follows_the_nameplate_tables(self):
        assert 'down_revision = "c1d2e3f4a5b6"' in self._migration()

    def test_it_adds_the_column_nullable(self):
        """Every article that exists has no origin, so NOT NULL could not be
        added at all."""
        body = self._migration()
        assert "syndicated_from_source_id" in body
        assert "nullable=True" in body

    def test_the_downgrade_removes_what_the_upgrade_added(self):
        body = self._migration()
        down = body[body.index("def downgrade") :]
        assert "drop_index" in down
        assert "drop_constraint" in down
        assert "drop_column" in down
