# Proposed Architecture & Implementation Plan

This proposal describes a prioritized architecture and implementation plan for the forked MizzouNewsCrawler-Scripts project.

Goals

- Stabilize and harden Phase 1 (CSV → SQLite/DB → crawler → extractor → ML) so it is reproducible and testable.
- Make the system configurable for local development and production (Postgres + cloud storage).
- Provide clear testing, CI, and incremental PRs so contributors can make safe changes.

High-level Architecture

1. Input: `sources/publinks.csv` or JSON site files
2. Loader: `src/cli/main.py` `load-sources` (CSV -> `candidate_links` table)
3. Discovery/Crawler: `src/crawler.NewsCrawler` — seed discovery, link filtering
4. Candidate storage: `candidate_links` table with statuses and metadata
5. Extraction: `src/crawler.ContentExtractor` -> `articles` table
6. ML & NER: `ml_results` and `locations` tables (pluggable model interface)
7. Telemetry & Jobs: `src/utils/telemetry.py` integrated with `jobs` table
8. Artifacts: `artifacts/` and `data/` for snapshots and parquet export

Key Design Decisions

- Database config: use `DATABASE_URL` environment variable. Default to `sqlite:///data/mizzou.db` for local dev.
- Idempotency: upsert helpers in `src/models/database.py` ensure safe re-runs.
- Separation of concerns: discovery/fetch/parsing/storage layers to be split into smaller modules during refactor.
- Telemetry: optional `TelemetryReporter` that can post to a configured endpoint; `OperationTracker` for local DB job tracking.

Prioritized Implementation Plan (sprint-sized PRs)

1. Foundation (PR-001)
   - Add `src/config.py` to centralize env vars and a `.env.example`.
   - Add `requirements-dev.txt` (already present) and `pre-commit` config (optional).
   - Minimal README updates (done).

2. Tests & CI (PR-002)
   - Add unit tests for `src/crawler/__init__.py` (is_valid_url, _is_likely_article, content extraction using fixtures).
   - Add tests for `src/models` upsert helpers (using in-memory SQLite).
   - Add GitHub Actions matrix runner: Python 3.11, run tests + flake8.

3. Config & DB layering (PR-003)
   - Implement `create_engine_from_env()` to read `DATABASE_URL`.
   - Ensure `DatabaseManager` accepts engine or URL; add tests for Postgres connection string parsing.

4. Telemetry & Jobs (PR-004)
   - Wire `OperationTracker` into CLI `load-sources` and `scripts/crawl.py` (start/complete/fail events).
   - Add optional `TELEMETRY_URL` env var; local ops stored in DB.

5. Docker + Local Compose (PR-005)
   - Provide `Dockerfile` for the app and `docker-compose.yml` with a Postgres service for integration testing.

6. Crawler refactor (PR-006)
   - Split crawler into discovery, fetcher, parser, and storage adapter interfaces.
   - Add plugin-style site rules and per-site adapters.

7. ML pipeline scaffolding (PR-007)
   - Provide `src/ml` stub with interfaces for classifier and NER models.
   - Add an example `analyze` command that runs a trivial classifier (e.g., keyword-based) and stores results.

Edge cases and considerations

- Empty or malformed CSV/JSON: `load-sources` must validate and fail gracefully.
- Slow/large inputs: crawler must respect `--delay` and have reasonable timeouts; consider rate-limiting per-domain.
- Duplicate articles due to redirects: deduplicate via `content_hash` and normalized URLs.
- Remote resource failures: transient network failures should be retried with backoff; persistent failures logged to `jobs` and candidate link error fields.
- Concurrent runs: locking or transaction isolation when multiple workers update the same DB.

Tests to add (minimal set)

- `tests/test_crawler_basic.py`
  - `test_is_valid_url()`
  - `test_is_likely_article()`
  - `test_extract_article_data_from_html()` (use small HTML fixture)

- `tests/test_db_upsert.py`
  - `test_upsert_candidate_link_creates()`
  - `test_upsert_candidate_link_updates()`
  - `test_upsert_article_idempotent()`

Quality Gates

Before merging major PRs run the following gates:

- Lint (flake8/black)
- Unit tests (pytest, coverage threshold e.g., 80%)
- Type checks (mypy) — optional as follow-up
- Integration smoke test (Docker Compose: app + Postgres)

Deliverables for phase 1 hardening

- `src/config.py` + `.env.example`
- `PROPOSAL.md` (this file)
- `ROADMAP.md` (already added)
- GitHub Actions CI config
- Initial unit tests and Docker Compose

Next steps (I can implement):

- Scaffold `src/config.py` and `.env.example` (low-risk) — I can do this now.
- Create initial unit tests for `src/crawler` and run them.

If you'd like me to start, I will scaffold `src/config.py`, `.env.example`, and one unit test for `src/crawler.is_valid_url` and run pytest locally. If there are preferences for Python versions or CI, tell me; otherwise I'll use Python 3.11+ compatible code.
