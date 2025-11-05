"""Tests for parallel classification with row-level locking."""

import inspect

import pytest


@pytest.mark.integration
def test_classification_service_uses_with_for_update():
    """Test that classification service uses with_for_update."""
    from src.services.classification_service import (
        ArticleClassificationService,
    )

    # Read the source to verify with_for_update is present
    source = inspect.getsource(ArticleClassificationService._select_articles)

    assert "with_for_update" in source, "Query must include with_for_update"
    assert "skip_locked=True" in source, "Query must use skip_locked=True"


@pytest.mark.postgres
@pytest.mark.integration
def test_sqlalchemy_skip_locked_syntax(cloud_sql_session):
    """Test SQLAlchemy with_for_update(skip_locked=True) works."""
    from sqlalchemy import select

    from src.models import Article

    # Build query with skip_locked
    stmt = (
        select(Article)
        .where(Article.status == "cleaned")
        .limit(5)
        .with_for_update(skip_locked=True)
    )

    # Should execute without error
    result = cloud_sql_session.execute(stmt)
    articles = result.scalars().all()
    assert isinstance(articles, list)
