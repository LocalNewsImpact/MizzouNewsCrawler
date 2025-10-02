from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from src.models.database import DatabaseManager


@pytest.fixture
def sample_dataframe() -> pd.DataFrame:
    """Simple DataFrame used by reporting CSV tests."""

    return pd.DataFrame(
        {
            "article_id": ["1", "2"],
            "title": ["Example", "Another"],
            "publish_date": ["2024-09-25 10:00:00", "2024-09-26 12:00:00"],
        }
    )


@pytest.fixture
def reporting_db(tmp_path: Path) -> Iterator[DatabaseManager]:
    """Provide a temporary SQLite database for county reporting tests."""

    db_path = tmp_path / "reporting.db"
    db_url = f"sqlite:///{db_path}"
    manager = DatabaseManager(database_url=db_url)
    with manager.engine.begin() as connection:
        try:
            connection.execute(text("ALTER TABLE articles ADD COLUMN wire TEXT"))
        except OperationalError:
            pass
    try:
        yield manager
    finally:
        manager.close()
        for suffix in ("", "-wal", "-shm"):
            candidate = db_path.with_suffix(db_path.suffix + suffix)
            if candidate.exists():
                candidate.unlink()


@pytest.fixture
def reporting_db_url(reporting_db: DatabaseManager) -> str:
    """Expose the database URL for configuring report generation."""

    return reporting_db.database_url
