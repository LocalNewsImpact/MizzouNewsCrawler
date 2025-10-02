"""Helpers for creating disposable SQLite databases during tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

import pytest

SchemaInput = str | Iterable[str] | None
SeedCallback = Callable[[sqlite3.Connection], Any] | None


IsolationLevel = Literal["DEFERRED", "IMMEDIATE", "EXCLUSIVE"] | None


def _apply_schema(connection: sqlite3.Connection, schema: SchemaInput) -> None:
    """Apply the supplied schema SQL to the connection."""

    if schema is None:
        return

    if isinstance(schema, str):
        connection.executescript(schema)
    else:
        for statement in schema:
            connection.execute(statement)
    connection.commit()


@pytest.fixture
def sqlite_builder(tmp_path):
    """Factory fixture that creates disposable SQLite databases.

    Examples
    --------
    def test_using_sqlite(sqlite_builder):
        path, conn = sqlite_builder(
            schema="CREATE TABLE example(id INTEGER PRIMARY KEY, value TEXT);",
            seed=lambda c: c.execute(
                "INSERT INTO example(value) VALUES (?)", ("foo",)
            ),
        )
        assert path.exists()
        assert conn.execute("SELECT value FROM example").fetchone()[0] == "foo"
    """

    created_connections: list[sqlite3.Connection] = []

    def _builder(
        *,
        name: str = "test.db",
        schema: SchemaInput = None,
        seed: SeedCallback = None,
    isolation_level: IsolationLevel = None,
        pragmas: Iterable[str] | None = None,
    ) -> tuple[Path, sqlite3.Connection]:
        db_path = tmp_path / name
        connection = sqlite3.connect(db_path, isolation_level=isolation_level)
        created_connections.append(connection)

        if pragmas:
            for pragma in pragmas:
                connection.execute(pragma)

        _apply_schema(connection, schema)

        if seed is not None:
            seed(connection)
            connection.commit()

        return db_path, connection

    yield _builder

    for connection in created_connections:
        try:
            connection.close()
        except Exception:
            pass


def create_sqlite_db(
    base_path: Path,
    *,
    schema: SchemaInput = None,
    seed: SeedCallback = None,
    name: str = "test.db",
    isolation_level: IsolationLevel = None,
    pragmas: Iterable[str] | None = None,
) -> tuple[Path, sqlite3.Connection]:
    """Utility for creating a temporary database outside of pytest fixtures."""

    db_path = base_path / name
    connection = sqlite3.connect(db_path, isolation_level=isolation_level)

    if pragmas:
        for pragma in pragmas:
            connection.execute(pragma)

    _apply_schema(connection, schema)

    if seed is not None:
        seed(connection)
        connection.commit()

    return db_path, connection
