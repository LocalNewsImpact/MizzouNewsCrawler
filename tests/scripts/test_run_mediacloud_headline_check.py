import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from scripts import run_mediacloud_headline_check as cli
from src.services.wire_detection import mediacloud as mc

pytestmark = pytest.mark.local_scripts

REQUIRED_FIELDS = [
    "media_cloud_candidate",
    "article_id",
    "source",
    "url",
    "title",
    "extracted_at_utc",
]


def write_candidates_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.example.com/story", "example.com"),
        ("http://sub.domain.org/article", "sub.domain.org"),
        ("invalid:///url", ""),
        ("https://EXAMPLE.com", "example.com"),
    ],
)
def test_normalize_host(url: str, expected: str) -> None:
    assert mc.normalize_host(url) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2025-12-05T18:00:00Z", datetime(2025, 12, 5, 18, 0, tzinfo=timezone.utc)),
        (
            "2025-12-05T18:00:00+02:00",
            datetime(2025, 12, 5, 16, 0, tzinfo=timezone.utc),
        ),
        ("2025-12-05T18:00:00", datetime(2025, 12, 5, 18, 0, tzinfo=timezone.utc)),
        ("", None),
        ("not-a-date", None),
    ],
)
def test_parse_iso8601(value: str, expected: Any) -> None:
    assert mc.parse_iso8601(value) == expected


def test_load_candidates_filters_and_parses(tmp_path: Path) -> None:
    input_path = tmp_path / "candidates.csv"
    write_candidates_csv(
        input_path,
        [
            {
                "media_cloud_candidate": "x",
                "article_id": "42",
                "source": "daily-news",
                "url": "https://example.com/story",
                "title": "Headline",
                "extracted_at_utc": "2025-12-05T18:00:00Z",
            },
            {
                "media_cloud_candidate": "",
                "article_id": "99",
                "source": "other",
                "url": "https://other.com/story",
                "title": "Skip",
                "extracted_at_utc": "2025-12-05T19:00:00Z",
            },
        ],
    )

    records = cli.load_candidates(str(input_path))
    assert len(records) == 1
    record = records[0]
    assert record.article_id == "42"
    assert record.host == "example.com"
    assert record.extracted_at == datetime(2025, 12, 5, 18, 0, tzinfo=timezone.utc)


def test_load_candidates_missing_required_fields(tmp_path: Path) -> None:
    input_path = tmp_path / "bad.csv"
    with input_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["article_id", "title"])
        writer.writeheader()
        writer.writerow({"article_id": "1", "title": "Headline"})

    with pytest.raises(RuntimeError):
        cli.load_candidates(str(input_path))


def test_rate_limiter_waits_when_called_too_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = mc.RateLimiter(2.0)  # 30 seconds between calls

    times = iter([10.0, 10.4])  # record(), wait()
    monkeypatch.setattr(mc.time, "monotonic", lambda: next(times))

    sleep_calls: list[float] = []
    monkeypatch.setattr(mc.time, "sleep", sleep_calls.append)

    limiter.record()
    limiter.wait()

    assert len(sleep_calls) == 1
    assert pytest.approx(sleep_calls[0], rel=1e-3) == 29.6


@pytest.mark.parametrize("rate", [0, -1])
def test_rate_limiter_rejects_non_positive(rate: float) -> None:
    with pytest.raises(ValueError):
        mc.RateLimiter(rate)


def test_summarize_matches_excludes_origin_host() -> None:
    base = mc.MediaCloudArticle(
        article_id="1",
        source="test-source",
        url="https://example.com/story",
        title="Headline",
        extracted_at=datetime(2025, 12, 5, tzinfo=timezone.utc),
    )
    stories = [
        {"url": "https://other.com/story-a", "id": 101},
        {"url": "https://other.com/story-b", "id": 102},
        {"url": "https://example.com/story-c", "id": 103},
        {"url": "https://third.com/story-d", "id": 104},
    ]

    count, hosts, story_ids = mc.summarize_matches(base, stories)

    assert count == 3  # all non-origin IDs counted, including duplicates
    assert hosts == ["other.com", "third.com"]
    assert story_ids == ["101", "102", "104"]


def test_mediacloud_detector_story_list_window() -> None:
    captured: dict[str, Any] = {}

    class DummySearchApi:
        def story_list(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return [], None

    extracted_at = datetime(2025, 12, 5, 18, 0, tzinfo=timezone.utc)
    detector = mc.MediaCloudDetector(DummySearchApi(), rate_limiter=mc.RateLimiter(60))
    article = mc.MediaCloudArticle(
        article_id="123",
        source="source",
        url="https://example.com/story",
        title="Headline",
        extracted_at=extracted_at,
    )
    detector._story_list(article, mc.build_query("Headline"))

    assert captured["start_date"] == (extracted_at - timedelta(days=1)).date()
    assert captured["end_date"] == (extracted_at + timedelta(days=1)).date()
    assert captured["query"] == mc.build_query("Headline")
    assert captured["page_size"] == 100


def test_run_writes_results_and_respects_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"

    write_candidates_csv(
        input_path,
        [
            {
                "media_cloud_candidate": "x",
                "article_id": "1",
                "source": "daily",
                "url": "https://example.com/story-1",
                "title": "Headline One",
                "extracted_at_utc": "2025-12-05T18:00:00Z",
            },
            {
                "media_cloud_candidate": "x",
                "article_id": "2",
                "source": "daily",
                "url": "https://example.com/story-2",
                "title": "Headline Two",
                "extracted_at_utc": "2025-12-05T19:00:00Z",
            },
        ],
    )

    class StubDetector:
        instances: list["StubDetector"] = []

        def __init__(self) -> None:
            self.detect_calls: list[mc.MediaCloudArticle] = []
            StubDetector.instances.append(self)

        def detect(self, article: mc.MediaCloudArticle) -> mc.DetectionResult:
            self.detect_calls.append(article)
            return mc.DetectionResult(
                article=article,
                query=mc.build_query(article.title),
                story_count=2,
                matched_story_count=1,
                matched_hosts=["other.com"],
                matched_story_ids=["111"],
                status="ok",
            )

        @property
        def search_api(self) -> Any:
            class _Profile:
                @staticmethod
                def user_profile() -> dict[str, Any]:
                    return {"username": "tester", "roles": ["user"]}

            return _Profile()

    stub_detector = StubDetector()

    monkeypatch.setattr(
        cli,
        "MediaCloudDetector",
        MagicMock(from_token=MagicMock(return_value=stub_detector)),
    )

    args = argparse.Namespace(
        input=str(input_path),
        output=str(output_path),
        token="secret-token",
        rate=mc.DEFAULT_RATE_PER_MINUTE,
        limit=1,
        verbose=False,
    )

    rc = cli.run(args)
    assert rc == 0

    assert len(stub_detector.detect_calls) == 1

    with output_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "ok"
    assert row["media_cloud_story_count"] == "2"
    assert row["media_cloud_matched_story_count"] == "1"
    assert row["media_cloud_unique_hosts"] == "other.com"
    assert row["media_cloud_story_ids"] == "111"
    assert row["query"] == mc.build_query("Headline One")


def test_run_records_api_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_path = tmp_path / "input.csv"
    output_path = tmp_path / "output.csv"
    write_candidates_csv(
        input_path,
        [
            {
                "media_cloud_candidate": "x",
                "article_id": "3",
                "source": "daily",
                "url": "https://example.com/story",
                "title": "Headline",
                "extracted_at_utc": "2025-12-05T18:00:00Z",
            }
        ],
    )

    class ErrorDetector:
        def __init__(self) -> None:
            self._profile = {"username": "tester", "roles": ["user"]}

        def detect(self, article: mc.MediaCloudArticle) -> mc.DetectionResult:
            return mc.DetectionResult(
                article=article,
                query=mc.build_query(article.title),
                story_count=0,
                matched_story_count=0,
                matched_hosts=[],
                matched_story_ids=[],
                status="api_error:503",
            )

        @property
        def search_api(self) -> Any:
            class _Profile:
                @staticmethod
                def user_profile() -> dict[str, Any]:
                    return {"username": "tester", "roles": ["user"]}

            return _Profile()

    stub_detector = ErrorDetector()

    monkeypatch.setattr(
        cli,
        "MediaCloudDetector",
        MagicMock(from_token=MagicMock(return_value=stub_detector)),
    )

    args = argparse.Namespace(
        input=str(input_path),
        output=str(output_path),
        token="secret-token",
        rate=mc.DEFAULT_RATE_PER_MINUTE,
        limit=None,
        verbose=False,
    )

    rc = cli.run(args)
    assert rc == 0

    with output_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 1
    row = rows[0]
    assert row["status"].startswith("api_error")
    assert row["media_cloud_story_count"] == "0"
    assert row["media_cloud_matched_story_count"] == "0"


def test_run_requires_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEDIACLOUD_API_TOKEN", raising=False)

    args = argparse.Namespace(
        input=str(tmp_path / "input.csv"),
        output=str(tmp_path / "output.csv"),
        token=None,
        rate=mc.DEFAULT_RATE_PER_MINUTE,
        limit=None,
        verbose=False,
    )

    rc = cli.run(args)
    assert rc == 1

    assert not Path(args.output).exists()
