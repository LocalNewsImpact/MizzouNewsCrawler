# ROADMAP & Modules

This document lists the main modules, responsibilities, and suggested first PRs for the fork.

## Main modules and responsibilities

- `src/crawler/`
  - `__init__.py` — `NewsCrawler`, `ContentExtractor` implementations; discovery, fetching, and extraction logic.
  - Responsibility: Robust link discovery, page fetching, heuristics for filtering article URLs, and best-effort article parsing.

- `src/models/`
  - `__init__.py` — SQLAlchemy models, engine/session helpers, and convenience functions (`create_database_engine`, `create_tables`, `get_session`).
  - Responsibility: Database schema, engine creation, migration-friendly utilities.

- `src/models/database.py`
  - Database helpers: `DatabaseManager`, idempotent upsert helpers, Pandas integration, and export helpers.
  - Responsibility: High-level DB operations used by CLI/scripts.

- `src/cli/`
  - `main.py` — CLI entrypoint with commands: `load-sources`, `crawl`, `extract`, `analyze`, `populate-gazetteer`, `status`.
  - Responsibility: Orchestrate the pipeline, read/write DB, provide user-facing commands. Auto-triggers gazetteer population when new sources are loaded.

- `src/utils/`
  - `telemetry.py` — Operation tracking, `TelemetryReporter`, `OperationTracker` and job tracking helpers.
  - Responsibility: Observability, progress reporting, optional integration with external telemetry endpoints.

- `scripts/`
  - `crawl.py` — Simple standalone crawling script for quick runs outside the CLI.
  - `populate_gazetteer.py` — Geographic enhancement script that geocodes publisher locations and discovers nearby entities using OpenStreetMap.
  - Responsibility: Quick runs and demonstrations; useful for integration tests. Geographic data enrichment.

- `sources/`
  - `mizzou_sites.json`, `publinks.csv` (expected)
  - Responsibility: Seed data for crawling and source configuration.

- `example_workflow.py`
  - Demonstrates the full pipeline using CLI commands.

## Suggested first PRs (small, reviewable)

1. Add `.env.example` and a minimal `src/config.py` to centralize environment configuration (`DATABASE_URL`, `LOG_LEVEL`, `TELEMETRY_URL`).
2. Add unit tests for `src/crawler/__init__.py` covering `is_valid_url`, `_is_likely_article`, and simple HTML extraction using small HTML fixtures.
3. Add a lightweight `pytest` CI job (GitHub Actions) that runs unit tests and flake8.
4. Add a `Dockerfile` for local development and a minimal `docker-compose.yml` that runs SQLite and a worker container.
5. Wire `OperationTracker` into `scripts/crawl.py` so job events are persisted to the `jobs` table during sample crawls.

## Notes

- SQLite is the development default. Use `DATABASE_URL` to point to Postgres for production testing.
- The roadmap is intentionally incremental: small PRs first, then larger refactors.

***End of ROADMAP***
