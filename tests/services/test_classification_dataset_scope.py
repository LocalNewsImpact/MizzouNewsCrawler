"""Classification can be scoped to a single dataset.

Added for the VTCNI load: a new dataset arrives with thousands of unlabelled
articles, and we want to classify only those without re-walking every other
dataset's backlog in the same run.

The tests select against a real session rather than asserting on a compiled
statement, because the failure mode this guards is a flag that is accepted and
then silently ignored -- which a shape check on the SQL would not catch. The
first draft of this filter read `Article.dataset_id`, a column that does not
exist: articles carry no dataset, the candidate link they were discovered
through does.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.models import Article, Base, CandidateLink
from src.services.classification_service import ArticleClassificationService

DATASET_A = "vtcni"
DATASET_B = "mizzou-missouri"


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    try:
        with SessionLocal() as db:
            yield db
            db.rollback()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _add_article(session: Session, article_id: str, dataset_id: str | None) -> None:
    link_id = f"link-{article_id}"
    session.add(
        CandidateLink(
            id=link_id,
            url=f"https://example.com/{article_id}",
            source="example.com",
            dataset_id=dataset_id,
        )
    )
    session.add(
        Article(
            id=article_id,
            candidate_link_id=link_id,
            url=f"https://example.com/{article_id}",
            title="Commission approves measure",
            text="The county commission voted 4-1 on Tuesday.",
            status="cleaned",
            created_at=datetime(2026, 8, 11),
        )
    )
    session.commit()


def _select(session: Session, dataset_id: str | None) -> list[str]:
    service = ArticleClassificationService(session=session)
    articles = service._select_articles(
        ["cleaned"],
        "default",
        None,
        False,
        None,
        None,
        dataset_id,
    )
    return sorted(str(article.id) for article in articles)


def test_dataset_id_restricts_selection_to_that_dataset(session: Session) -> None:
    _add_article(session, "a1", DATASET_A)
    _add_article(session, "b1", DATASET_B)

    assert _select(session, DATASET_A) == ["a1"]
    assert _select(session, DATASET_B) == ["b1"]


def test_no_dataset_id_selects_across_every_dataset(session: Session) -> None:
    """The default stays corpus-wide -- existing scheduled runs must not narrow."""
    _add_article(session, "a1", DATASET_A)
    _add_article(session, "b1", DATASET_B)
    _add_article(session, "n1", None)

    assert _select(session, None) == ["a1", "b1", "n1"]


def test_dataset_scoping_excludes_articles_with_no_dataset(session: Session) -> None:
    """A NULL dataset_id is not a wildcard: those rows belong to no dataset."""
    _add_article(session, "a1", DATASET_A)
    _add_article(session, "n1", None)

    assert _select(session, DATASET_A) == ["a1"]
