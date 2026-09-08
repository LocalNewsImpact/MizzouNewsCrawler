"""An article carries its dataset, and it is always the dataset of its link.

The column exists so that "this dataset's articles" is one index range
instead of a join through candidate_links. It is worth nothing if a write
path can leave it empty or set it to something else, so both paths --
the extraction command's SQL insert and the ORM upsert -- are held to the
same rule here.
"""

from datetime import datetime

import pytest
from sqlalchemy import text

from src.models import Base, CandidateLink
from src.models.database import DatabaseManager, upsert_article

MIZZOU = "61ccd4d3-763f-4cc6-b85d-74b268e80a00"


@pytest.fixture()
def db(tmp_path):
    dm = DatabaseManager(database_url=f"sqlite:///{tmp_path / 'articles.db'}")
    Base.metadata.create_all(bind=dm.engine)
    return dm


def _link(session, link_id, dataset_id):
    link = CandidateLink(
        id=link_id,
        url=f"https://a.example/{link_id}",
        source="a.example",
        dataset_id=dataset_id,
        discovered_by="test",
    )
    session.add(link)
    session.commit()
    return link


def _insert_through_the_command(session, article_id, link_id):
    from src.cli.commands.extraction import ARTICLE_INSERT_SQL

    now = datetime(2026, 9, 8, 12, 0, 0)
    session.execute(
        ARTICLE_INSERT_SQL,
        {
            "id": article_id,
            "candidate_link_id": link_id,
            "url": f"https://a.example/{link_id}",
            "title": "t",
            "author": None,
            "publish_date": None,
            "content": "body",
            "text": "body",
            "status": "extracted",
            "metadata": "{}",
            "wire": None,
            "wire_check_status": "pending",
            "wire_check_attempted_at": None,
            "wire_check_error": None,
            "wire_check_metadata": None,
            "extracted_at": now.isoformat(),
            "created_at": now.isoformat(),
            "text_hash": article_id,
            "raw_gcs_path": None,
        },
    )
    session.commit()


def _dataset_of(session, article_id):
    return session.execute(
        text("SELECT dataset_id FROM articles WHERE id = :id"), {"id": article_id}
    ).scalar()


def test_the_insert_derives_the_dataset_from_the_link(db):
    """Nothing passes a dataset to the insert. It reads the link's."""
    with db.get_session() as session:
        _link(session, "l1", MIZZOU)
        _insert_through_the_command(session, "a1", "l1")
        assert _dataset_of(session, "a1") == MIZZOU


def test_a_link_in_no_dataset_gives_an_article_in_no_dataset(db):
    with db.get_session() as session:
        _link(session, "l2", None)
        _insert_through_the_command(session, "a2", "l2")
        assert _dataset_of(session, "a2") is None


def test_the_orm_path_follows_the_same_rule(db):
    with db.get_session() as session:
        _link(session, "l3", MIZZOU)
        article = upsert_article(session, "l3", "some text")
        assert article.dataset_id == MIZZOU


def test_a_caller_that_names_the_dataset_is_not_overridden(db):
    """Explicit wins over derived, so a backfill can say what it means."""
    with db.get_session() as session:
        _link(session, "l4", None)
        article = upsert_article(session, "l4", "some text", dataset_id=MIZZOU)
        assert article.dataset_id == MIZZOU


def test_the_migration_fills_from_the_link_and_ends_with_analyze():
    """DDL does not count toward autovacuum's modification bar, so a
    column a migration adds and fills has no statistics until something
    unrelated crosses it. The migration analyzes what it indexed."""
    from pathlib import Path

    body = Path(
        "alembic/versions/t5u6v7w8x9y0_an_article_knows_its_dataset.py"
    ).read_text()
    upgrade = body[body.index("def upgrade") : body.index("def downgrade")]
    fill = upgrade.index("SET dataset_id = cl.dataset_id")
    index = upgrade.index("create_index")
    analyze = upgrade.index("ANALYZE articles")
    assert fill < index < analyze
