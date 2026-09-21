"""A label describes the body it was made from.

17 WSU articles sat at `cleaned` on 2026-09-21 while carrying CIN labels. Every
one had been labeled BEFORE its latest extraction: first captured as a paywall
or navigation page, classified, then refetched by the authenticated rotation --
which put the status back to `cleaned` -- and then skipped by classification,
because a label existed at the run's version. Enrichment selects `labeled`, so
none could be enriched, and each still carried the label it was given for the
wall. Re-run on the real bodies, 4 of the 17 changed category.

So a label applied before the article's latest extraction does not count as
existing. These run against a real session, because the failure this guards is
a filter that is accepted and silently matches nothing.

`articles.extracted_at` is NOT NULL with a default (0 nulls in 167,337
production rows), so there is no "never extracted" case to keep.

Measured before shipping: all 326 Mizzou rows at `cleaned` with labels were
labeled AFTER their latest extraction, so this reaches none of them. Theirs is a
different cause, still open.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.models import Article, ArticleLabel, Base, CandidateLink
from src.services.classification_service import ArticleClassificationService

T0 = datetime(2026, 9, 19, 12, 0)


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


def _article(session, article_id, *, extracted_at, labeled_at, version="default"):
    link_id = f"link-{article_id}"
    session.add(
        CandidateLink(id=link_id, url=f"https://ex.com/{article_id}", source="ex.com")
    )
    session.add(
        Article(
            id=article_id,
            candidate_link_id=link_id,
            url=f"https://ex.com/{article_id}",
            title="Council approves budget",
            text="The city council voted 5-2 on Monday.",
            status="cleaned",
            extracted_at=extracted_at,
            created_at=T0,
        )
    )
    if labeled_at is not None:
        session.add(
            ArticleLabel(
                article_id=article_id,
                label_version=version,
                model_version="m1",
                primary_label="Civic information",
                applied_at=labeled_at,
            )
        )
    session.commit()


def _selected(session, *, include_existing=False, version="default") -> list[str]:
    service = ArticleClassificationService(session=session)
    return sorted(
        str(a.id)
        for a in service._select_articles(["cleaned"], version, None, include_existing)
    )


def test_a_label_older_than_the_body_does_not_count(session):
    """The WSU case: labeled on the wall, refetched afterwards."""
    _article(session, "refetched", extracted_at=T0 + timedelta(days=2), labeled_at=T0)
    assert _selected(session) == ["refetched"]


def test_a_label_made_from_the_current_body_still_counts(session):
    """Unchanged: nothing is re-classified that was classified on this body."""
    _article(session, "current", extracted_at=T0, labeled_at=T0 + timedelta(hours=1))
    assert _selected(session) == []


def test_a_label_applied_at_the_same_instant_counts(session):
    _article(session, "same", extracted_at=T0, labeled_at=T0)
    assert _selected(session) == []


def test_an_unlabeled_article_is_selected_as_before(session):
    _article(session, "fresh", extracted_at=T0, labeled_at=None)
    assert _selected(session) == ["fresh"]


def test_only_the_runs_label_version_is_consulted(session):
    """A stale label at another version neither hides nor exposes this one."""
    _article(
        session,
        "other-version",
        extracted_at=T0,
        labeled_at=T0 + timedelta(hours=1),
        version="wsu-notebook-2026-02",
    )
    assert _selected(session) == ["other-version"]


def test_force_still_takes_everything(session):
    _article(session, "current", extracted_at=T0, labeled_at=T0 + timedelta(hours=1))
    _article(session, "refetched", extracted_at=T0 + timedelta(days=2), labeled_at=T0)
    assert _selected(session, include_existing=True) == ["current", "refetched"]


def test_the_mixture_selects_exactly_the_stale_one(session):
    _article(session, "current", extracted_at=T0, labeled_at=T0 + timedelta(hours=1))
    _article(session, "refetched", extracted_at=T0 + timedelta(days=2), labeled_at=T0)
    _article(session, "fresh", extracted_at=T0, labeled_at=None)
    assert _selected(session) == ["fresh", "refetched"]
