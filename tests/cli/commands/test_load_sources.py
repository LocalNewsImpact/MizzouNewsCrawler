from types import SimpleNamespace

import pandas as pd
import pytest

from src.cli.commands import load_sources
from src.cli.commands.load_sources import (
    REQUIRED_COLUMNS,
    _detect_duplicate_urls,
    _normalize_source_row,
    _parse_host_components,
    _validate_columns,
)
from src.models import Dataset, DatasetSource, Source


def test_validate_columns_reports_missing_fields():
    df = pd.DataFrame([{"host_id": 1, "name": "Example", "city": "Columbia"}])

    missing = _validate_columns(df)

    expected_missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    assert missing == expected_missing


def test_normalize_source_row_generates_expected_payload():
    row = pd.Series(
        {
            "host_id": 123,
            "name": "Example News",
            "city": "Columbia",
            "county": "Boone",
            "url_news": "https://example.com/feed",
            "media_type": "newspaper",
            "frequency": "weekly",
            "owner": "Local Media",
            "address1": "123 Main St",
            "address2": "Suite 200",
            "zip": 65201,
            "cached_geographic_entities": "Boone County",
            "cached_institutions": "University of Missouri",
            "cached_schools": "Mizzou",
            "cached_government": "City Council",
            "cached_healthcare": "MU Health",
            "cached_businesses": "Downtown Biz",
            "cached_landmarks": "Columns",
        }
    )

    normalized = _normalize_source_row(row)

    assert normalized["source_host_id"] == "123"
    assert normalized["source_name"] == "Example News"
    assert normalized["source_city"] == "Columbia"
    assert normalized["source_county"] == "Boone"
    assert normalized["url"] == "https://example.com/feed"
    assert normalized["source_type"] == "newspaper"
    assert normalized["frequency"] == "weekly"
    assert normalized["owner"] == "Local Media"
    assert normalized["address"] == "123 Main St, Suite 200"
    assert normalized["zip_code"] == "65201"
    assert normalized["cached_geographic_entities"] == "Boone County"
    assert normalized["cached_institutions"] == "University of Missouri"
    assert normalized["cached_schools"] == "Mizzou"
    assert normalized["cached_government"] == "City Council"
    assert normalized["cached_healthcare"] == "MU Health"
    assert normalized["cached_businesses"] == "Downtown Biz"
    assert normalized["cached_landmarks"] == "Columns"
    assert normalized["status"] == "pending"
    assert normalized["priority"] == 1


@pytest.mark.parametrize(
    "zip_value, expected",
    [(pd.NA, None), ("", ""), (12345, "12345")],
)
def test_normalize_source_row_handles_missing_zip(zip_value, expected):
    row = pd.Series(
        {
            "host_id": 1,
            "name": "Example",
            "city": "Columbia",
            "county": "Boone",
            "url_news": "https://example.com",
            "zip": zip_value,
        }
    )

    normalized = _normalize_source_row(row)

    assert normalized["zip_code"] == expected


def test_parse_host_components_returns_raw_and_normalized():
    raw, normalized = _parse_host_components("https://Sub.Domain.Example.com/path")

    assert raw == "Sub.Domain.Example.com"
    assert normalized == "sub.domain.example.com"


def test_parse_host_components_rejects_missing_host():
    with pytest.raises(ValueError):
        _parse_host_components("file:///tmp/news.csv")


def test_detect_duplicate_urls_returns_messages_for_duplicates():
    df = pd.DataFrame(
        [
            {
                "host_id": 1,
                "name": "Example A",
                "url_news": "https://example.com/feed",
                "_parsed_host_norm": "example.com",
            },
            {
                "host_id": 2,
                "name": "Example B",
                "url_news": "https://example.com/feed",
                "_parsed_host_norm": "example.com",
            },
            {
                "host_id": 3,
                "name": "Example C",
                "url_news": "https://another.com/feed",
                "_parsed_host_norm": "another.com",
            },
            {
                "host_id": 4,
                "name": "Example D",
                "url_news": "https://different.com/feed",
                "_parsed_host_norm": "example.com",
            },
        ]
    )

    messages = _detect_duplicate_urls(df)

    assert any("Duplicate url_news entries" in message for message in messages)
    assert any("Duplicate host values" in message for message in messages)


class _StubResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _StubSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self._id_sequence = 1
        self.added = []
        self.commits = 0
        self.rollback_called = False
        self.closed = False

    def execute(self, stmt):
        value = self._responses.pop(0) if self._responses else None
        return _StubResult(value)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = self._id_sequence
                self._id_sequence += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollback_called = True

    def close(self):
        self.closed = True


class _StubDatabaseManager:
    def __init__(self):
        self.engine = object()
        self.upsert_calls = []

    def upsert_candidate_links(self, df):
        self.upsert_calls.append(df.copy())


def _build_args(csv_path: str) -> SimpleNamespace:
    return SimpleNamespace(csv=csv_path)


def test_handle_load_sources_command_creates_dataset_and_sources(monkeypatch):
    csv_path = "/tmp/publinks.csv"
    source_df = pd.DataFrame(
        [
            {
                "host_id": 101,
                "name": "Example News",
                "city": "Columbia",
                "county": "Boone",
                "url_news": "https://example.com/feed",
                "media_type": "newspaper",
                "frequency": "weekly",
                "owner": "Local Media",
                "address1": "123 Main St",
                "address2": "Suite 200",
                "zip": 65201,
            }
        ]
    )

    stub_db = _StubDatabaseManager()
    stub_session = _StubSession([None, None, None])
    trigger_calls = []

    monkeypatch.setattr(
        load_sources.pd,
        "read_csv",
        lambda path: source_df.copy(),
    )
    monkeypatch.setattr(load_sources, "DatabaseManager", lambda: stub_db)

    def fake_sessionmaker(*, bind):
        assert bind is stub_db.engine
        return lambda: stub_session

    monkeypatch.setattr(load_sources, "sessionmaker", fake_sessionmaker)
    monkeypatch.setattr(
        load_sources,
        "trigger_gazetteer_population_background",
        lambda slug, logger: trigger_calls.append(slug),
    )

    exit_code = load_sources.handle_load_sources_command(_build_args(csv_path))

    assert exit_code == 0
    assert stub_session.commits == 1
    assert stub_session.closed is True
    assert trigger_calls == ["publinks-publinks_csv"]

    dataset = next(obj for obj in stub_session.added if isinstance(obj, Dataset))
    dataset_values = dataset.__dict__
    assert dataset_values["slug"] == "publinks-publinks_csv"
    assert dataset_values["meta"]["total_rows"] == len(source_df)

    source = next(obj for obj in stub_session.added if isinstance(obj, Source))
    source_values = source.__dict__
    assert source_values["host"] == "example.com"
    assert source_values["meta"]["address1"] == "123 Main St"

    dataset_source = next(
        obj for obj in stub_session.added if isinstance(obj, DatasetSource)
    )
    dataset_source_values = dataset_source.__dict__
    assert dataset_source_values["legacy_host_id"] == "101"
    assert dataset_source_values["dataset_id"] == dataset.id
    assert dataset_source_values["source_id"] == source.id

    assert len(stub_db.upsert_calls) == 1
    candidate_df = stub_db.upsert_calls[0]
    assert candidate_df.iloc[0]["source_host_id"] == "101"
    assert candidate_df.iloc[0]["dataset_id"] == dataset.id


def test_handle_load_sources_command_detects_duplicates_early(monkeypatch):
    duplicate_df = pd.DataFrame(
        [
            {
                "host_id": 1,
                "name": "Example A",
                "city": "Columbia",
                "county": "Boone",
                "url_news": "https://duplicate.com/a",
            },
            {
                "host_id": 2,
                "name": "Example B",
                "city": "Columbia",
                "county": "Boone",
                "url_news": "https://duplicate.com/b",
            },
        ]
    )

    monkeypatch.setattr(
        load_sources.pd,
        "read_csv",
        lambda path: duplicate_df.copy(),
    )
    monkeypatch.setattr(
        load_sources,
        "DatabaseManager",
        lambda: pytest.fail(
            "DatabaseManager should not be constructed on duplicate input"
        ),
    )

    exit_code = load_sources.handle_load_sources_command(_build_args("/tmp/dupes.csv"))

    assert exit_code == 1
