from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.helpers import (
    FakeSpacyNlp,
    FakeSpacySpan,
    FakeStorySniffer,
    create_sqlite_db,
)


def test_sqlite_builder_creates_schema(sqlite_builder):
    schema = """
    CREATE TABLE example(id INTEGER PRIMARY KEY, value TEXT);
    """

    def seed(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO example(value) VALUES (?)", ("alpha",))

    path, connection = sqlite_builder(schema=schema, seed=seed)

    assert path.exists()
    cursor = connection.execute("SELECT value FROM example")
    assert cursor.fetchone()[0] == "alpha"


def test_create_sqlite_db_helper(tmp_path: Path) -> None:
    schema = [
        "CREATE TABLE numbers(id INTEGER PRIMARY KEY, value INTEGER);",
        "INSERT INTO numbers(value) VALUES (1), (2);",
    ]
    path, connection = create_sqlite_db(
        tmp_path, schema=schema, name="nums.db"
    )
    assert path.name == "nums.db"
    values = [
        row[0]
        for row in connection.execute("SELECT value FROM numbers")
    ]
    assert values == [1, 2]
    connection.close()


def test_filesystem_builder_creates_structure(filesystem_builder):
    structure = {
        "config": {
            "settings.yaml": "name: demo\n",
            "binary.dat": b"\x00\x01",
        },
        "logs": None,
        "custom.txt": lambda path: path.write_text("custom"),
    }
    base = filesystem_builder(structure)

    assert (base / "config" / "settings.yaml").read_text() == "name: demo\n"
    assert (base / "config" / "binary.dat").read_bytes() == b"\x00\x01"
    assert (base / "logs").is_dir()
    assert (base / "custom.txt").read_text() == "custom"


def test_fake_spacy_nlp_records_calls() -> None:
    span = FakeSpacySpan(text="Columbia", label_="GPE")
    fake = FakeSpacyNlp(entities={"Hello": [span]})

    doc = fake("Hello")
    assert fake.calls == ["Hello"]
    assert len(doc.ents) == 1
    assert doc.ents[0].label_ == "GPE"


def test_fake_storysniffer_decision_variants() -> None:
    decisions = {"https://example.com": True, "https://other.com": False}
    fake = FakeStorySniffer(decision=decisions)

    assert fake.guess("https://example.com") is True
    assert fake.guess("https://other.com") is False
    assert fake.guess("https://unknown.com") is False
    assert fake.calls == [
        "https://example.com",
        "https://other.com",
        "https://unknown.com",
    ]


def test_fake_storysniffer_exception_path() -> None:
    class Boom(Exception):
        pass

    def raiser(url: str) -> Exception:
        raise Boom(f"boom: {url}")

    fake = FakeStorySniffer(decision=True, exception=raiser)

    with pytest.raises(Boom):
        fake.guess("https://fail.com")
