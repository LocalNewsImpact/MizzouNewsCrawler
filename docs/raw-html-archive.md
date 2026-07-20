# Raw HTML archive

Every article we persist also stores the page HTML it was extracted from, in
GCS, for **30 days**. `articles.raw_gcs_path` holds the object's `gs://` URI.

## Why

Extractor comparisons are only meaningful on identical input. Re-fetching a URL
later is not a control: the page may have changed, and bot-protected sites
return challenge pages to naive requests — so a re-fetch comparison ends up
measuring the proxy stack rather than the extractor. `scripts/extraction_quality_report.py`
documents this at length and deliberately refuses to offer a re-fetch mode.

With the archive, a candidate extractor can be replayed offline against the
exact bytes production parsed, which turns "did this change help?" into a
measurable question.

## Layout

```
gs://mizzou-news-crawler-raw-html/YYYY/MM/DD/<host>/<article_id>.html.gz
```

Date first so the retention window is legible when browsing the bucket; host
second so a per-publisher replay is a prefix listing rather than a full scan.

Objects are gzipped and stored as `application/gzip`. They are deliberately
*not* tagged `Content-Encoding: gzip` — GCS decompressively transcodes such
objects on download, which would hand replay tooling different bytes than were
uploaded.

## Retention

A bucket lifecycle rule deletes objects 30 days after creation:

```bash
gsutil lifecycle get gs://mizzou-news-crawler-raw-html
# {"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30}}]}
```

Retention is bucket configuration, not application logic — nothing in the code
deletes objects. To change the window, edit the lifecycle rule:

```bash
gcloud storage buckets update gs://mizzou-news-crawler-raw-html \
  --lifecycle-file=lifecycle.json
```

Note that `raw_gcs_path` rows outlive their objects. Anything reading the
archive must treat a missing object as normal for articles older than the
window; `fetch_html()` returns `None` rather than raising.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `RAW_HTML_ARCHIVE_ENABLED` | `true` | Set false to stop archiving |
| `RAW_HTML_BUCKET` | `mizzou-news-crawler-raw-html` | Target bucket |
| `RAW_HTML_MAX_BYTES` | `5242880` | Pages larger than this are skipped |

Access comes from workload identity (`mizzou-k8s-sa`, `roles/storage.objectAdmin`
on the bucket). Environments without credentials — local dev, CI, tests — log
once and no-op.

## Failure behavior

Archiving is observability and must never cost an article. Every failure path
(no client, no credentials, oversized page, upload error, an extractor that
can't supply HTML) returns `None`, the article is written with a NULL
`raw_gcs_path`, and extraction continues.

## Which HTML gets stored

An extraction may fetch a page several times as it falls back between methods
(mcmetadata → newspaper4k → beautifulsoup → selenium → squid proxy). The
largest response wins: challenge pages, consent walls and error stubs are all
far smaller than the article page worth replaying. The winning method is
recorded in the object's `extraction_method` metadata.

## Reading it back

```python
from src.utils.raw_html_archive import fetch_html

html = fetch_html(article.raw_gcs_path)  # None if expired or unreachable
```
