"""Contracts for the data/infra stack: pandas (+numpy/pyarrow), feedparser,
rapidfuzz, warcio, requests surface.

pandas appears in 11 src files (BigQuery export, reporting, dataset loaders);
pandas 3.x is a breaking major — these tests pin the operations we actually
perform.
"""

from __future__ import annotations

import io

import pytest


class TestPandasNumpyPyarrow:
    """Call sites: src/pipeline/bigquery export, reporting, dataset loads —
    DataFrame construction, dtype coercion, groupby/agg, parquet roundtrip,
    to_dict(orient='records'), read_csv."""

    def test_dataframe_core_operations(self):
        pd = pytest.importorskip("pandas")

        df = pd.DataFrame(
            {
                "host": ["a.com", "b.com", "a.com"],
                "n_articles": [3, 5, 2],
                "published": pd.to_datetime(["2026-03-05", "2026-03-06", "2026-03-07"]),
            }
        )
        grouped = df.groupby("host", as_index=False)["n_articles"].sum()
        assert grouped.loc[grouped["host"] == "a.com", "n_articles"].item() == 5
        records = df.to_dict(orient="records")
        assert records[0]["host"] == "a.com"
        # NaN/None handling used by exports
        assert pd.isna(pd.NA)

    def test_read_csv_from_buffer(self):
        pd = pytest.importorskip("pandas")

        df = pd.read_csv(io.StringIO("url,text\nhttp://a.com/x,hello\n"))
        assert df.iloc[0]["text"] == "hello"

    def test_parquet_roundtrip_via_pyarrow(self, tmp_path):
        pd = pytest.importorskip("pandas")
        pytest.importorskip("pyarrow")

        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        path = tmp_path / "roundtrip.parquet"
        df.to_parquet(path)
        back = pd.read_parquet(path)
        assert back.equals(df)

    def test_numpy_surface(self):
        np = pytest.importorskip("numpy")

        arr = np.array([0.2, 0.8])
        assert float(arr.mean()) == pytest.approx(0.5)
        # np.float64 JSON-serialization boundary we hit in telemetry
        assert isinstance(arr[0].item(), float)


class TestFeedparser:
    """Call site: src/crawler RSS discovery — feedparser.parse on fetched
    bytes; entries[].link/title/published are read."""

    def test_parse_rss_entries(self, rss_xml):
        feedparser = pytest.importorskip("feedparser")

        feed = feedparser.parse(rss_xml)
        assert not feed.bozo
        entry = feed.entries[0]
        assert entry.link.endswith("/city-council-budget/")
        assert "Budget" in entry.title
        assert entry.published_parsed is not None


class TestRapidfuzz:
    """Call site: gazetteer entity matching — fuzz.ratio / process.extractOne."""

    def test_fuzz_and_extract_one(self):
        rapidfuzz = pytest.importorskip("rapidfuzz")

        assert rapidfuzz.fuzz.ratio("Jefferson City", "Jeferson City") > 90
        best = rapidfuzz.process.extractOne(
            "Boone Cnty", ["Boone County", "Cole County"]
        )
        assert best[0] == "Boone County"


class TestWarcio:
    """Call site: Minnesota/WARC import — iterate records from an archive."""

    def test_warc_write_read_roundtrip(self):
        warcio_writer = pytest.importorskip("warcio.warcwriter")
        warcio_iterator = pytest.importorskip("warcio.archiveiterator")
        status_headers_mod = pytest.importorskip("warcio.statusandheaders")

        buf = io.BytesIO()
        writer = warcio_writer.WARCWriter(buf, gzip=False)
        headers = status_headers_mod.StatusAndHeaders(
            "200 OK", [("Content-Type", "text/html")], protocol="HTTP/1.1"
        )
        record = writer.create_warc_record(
            "https://www.example-gazette.com/",
            "response",
            payload=io.BytesIO(b"<html>hi</html>"),
            http_headers=headers,
        )
        writer.write_record(record)

        buf.seek(0)
        records = list(warcio_iterator.ArchiveIterator(buf))
        assert records and records[0].rec_type == "response"
        assert records[0].rec_headers.get_header("WARC-Target-URI") == (
            "https://www.example-gazette.com/"
        )
