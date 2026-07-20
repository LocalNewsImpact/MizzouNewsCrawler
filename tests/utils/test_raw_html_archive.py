"""Tests for the raw HTML archive."""

import gzip
import types
from unittest.mock import Mock, patch

import pytest

from src.utils import raw_html_archive
from src.utils.raw_html_archive import (
    archive_html,
    build_object_path,
    fetch_html,
    reset_client_cache,
)


@pytest.fixture(autouse=True)
def _clean_client_cache():
    reset_client_cache()
    yield
    reset_client_cache()


@pytest.fixture
def mock_gcs(monkeypatch):
    """Patch the module's client factory and hand back the blob it writes to."""
    blob = Mock()
    bucket = Mock()
    bucket.blob.return_value = blob
    client = Mock()
    client.bucket.return_value = bucket
    monkeypatch.setattr(raw_html_archive, "_get_client", lambda: client)
    return client, bucket, blob


def test_object_path_is_date_and_host_partitioned():
    from datetime import datetime, timezone

    when = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
    path = build_object_path("https://www.komu.com/news/story.html", "abc-123", when)

    assert path == "2026/07/20/komu.com/abc-123.html.gz"


def test_object_path_tolerates_unparseable_url():
    assert "unknown/" in build_object_path("not a url", "abc-123")


def test_archive_uploads_gzipped_html_and_returns_uri(mock_gcs):
    _, _, blob = mock_gcs

    uri = archive_html(
        "https://example.com/story", "<html>body</html>", "art-1", "selenium"
    )

    assert uri.startswith("gs://")
    assert uri.endswith("art-1.html.gz")

    payload = blob.upload_from_string.call_args[0][0]
    assert gzip.decompress(payload).decode() == "<html>body</html>"


def test_archive_records_extraction_method_metadata(mock_gcs):
    _, _, blob = mock_gcs

    archive_html("https://example.com/s", "<html/>", "art-1", "squid_proxy")

    assert blob.metadata["extraction_method"] == "squid_proxy"


def test_archive_skips_empty_html(mock_gcs):
    _, _, blob = mock_gcs

    assert archive_html("https://example.com/s", "", "art-1") is None
    assert archive_html("https://example.com/s", None, "art-1") is None
    blob.upload_from_string.assert_not_called()


def test_archive_skips_oversized_payload(mock_gcs, monkeypatch):
    _, _, blob = mock_gcs
    monkeypatch.setenv("RAW_HTML_MAX_BYTES", "100")

    assert archive_html("https://example.com/s", "x" * 500, "art-1") is None
    blob.upload_from_string.assert_not_called()


def test_archive_disabled_by_env(monkeypatch, mock_gcs):
    _, _, blob = mock_gcs
    monkeypatch.setenv("RAW_HTML_ARCHIVE_ENABLED", "false")

    assert archive_html("https://example.com/s", "<html/>", "art-1") is None
    blob.upload_from_string.assert_not_called()


def test_archive_never_raises_when_gcs_fails(mock_gcs):
    _, _, blob = mock_gcs
    blob.upload_from_string.side_effect = RuntimeError("bucket on fire")

    assert archive_html("https://example.com/s", "<html/>", "art-1") is None


def test_archive_returns_none_without_a_client(monkeypatch):
    """No credentials (local dev, CI) must degrade silently, not explode."""
    monkeypatch.setattr(raw_html_archive, "_get_client", lambda: None)

    assert archive_html("https://example.com/s", "<html/>", "art-1") is None


def test_client_init_failure_is_cached():
    """A credential-less environment should log once, not once per article.

    A stub module is injected so this is deterministic whether or not
    google-cloud-storage is installed in the running venv.
    """
    stub = types.ModuleType("google.cloud.storage")
    stub.Client = Mock(side_effect=RuntimeError("no credentials"))

    with patch.dict("sys.modules", {"google.cloud.storage": stub}):
        assert raw_html_archive._get_client() is None
        assert raw_html_archive._get_client() is None

    assert stub.Client.call_count == 1


def test_fetch_round_trips_archived_html(mock_gcs):
    _, _, blob = mock_gcs
    blob.download_as_bytes.return_value = gzip.compress(b"<html>hi</html>")

    assert fetch_html("gs://bucket/2026/07/20/x.html.gz") == "<html>hi</html>"


def test_fetch_rejects_non_gcs_uri(mock_gcs):
    assert fetch_html("https://example.com/x.html") is None
    assert fetch_html("") is None
