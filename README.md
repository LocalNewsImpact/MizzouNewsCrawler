# MizzouNewsCrawler-Scripts

A CSV-to-Database-driven production version of MizzouNewsCrawler with SQLite backend.

## Overview

This project converts the original MizzouNewsCrawler into a production-ready script architecture with a two-phase approach:

- **Phase 1 — Script-based**: CSV-to-Database-driven crawler with CLI interface and SQLite backend
- **Phase 2 — Production**: Deploy on GKE with Postgres, orchestrate with Kubernetes jobs

## Architecture

**CSV-to-Database-Driven Design:**

1. Load `publinks.csv` into SQLite database (one-time setup)
2. All crawler operations are driven from database queries
3. Support filtering by ALL/HOST/COUNTY/CITY with configurable limits
4. Database tracks crawling progress and status

## Phase 1 Architecture

### Project Structure

```
├── src/                    # Core business logic
│   ├── crawler/           # Web crawling and content extraction
│   ├── models/            # SQLAlchemy database models
│   ├── cli/               # Command-line interface scripts
│   └── utils/             # Shared utilities
├── sources/               # Input data (publinks.csv)
├── requirements.txt       # Python dependencies
└── example_workflow.py    # Complete workflow demonstration
```

### Database Schema

- **candidate_links**: Source publications loaded from publinks.csv
- **articles**: Discovered article URLs and extracted content
- **ml_results**: ML analysis results with model versioning
- **locations**: Extracted geographic entities
- **jobs**: Processing job tracking and audit trail

### Key Features

- **CLI Interface**: Complete command-line interface for all operations
- **Database-Driven**: All operations query SQLite database for sources
- **Flexible Filtering**: Support ALL/HOST/COUNTY/CITY filters with limits
- **Status Tracking**: Database tracks crawling progress and errors
- **Modular Design**: Core logic extracted to importable src/ modules

## Quick Start

```bash
# Setup environment
pip install -r requirements.txt

# Run complete example workflow
python example_workflow.py
```

## CLI Usage

### Load Sources (One-time Setup)

```bash
# Load publinks.csv into database
python -m src.cli.main load-sources --csv sources/publinks.csv
```

### Crawl with Filtering

```bash
# Crawl ALL sources with limits
python -m src.cli.main crawl --filter ALL --host-limit 10 --article-limit 5

# Crawl single host
python -m src.cli.main crawl --filter HOST --host "standard-democrat.com" --article-limit 10

# Crawl by location
python -m src.cli.main crawl --filter COUNTY --county "Scott" --host-limit 5 --article-limit 3
python -m src.cli.main crawl --filter CITY --city "Sikeston" --article-limit 5
```

### Extract Content

```bash
# Extract content from discovered articles
python -m src.cli.main extract --limit 50
```

### Check Status

```bash
# Show crawling statistics
python -m src.cli.main status
```

### Export a Snapshot (table -> Parquet)

Create a Parquet snapshot by exporting a database table for a given
dataset version. This command is useful when you want to materialize a
consistent snapshot of a table (e.g., `articles` or `candidate_links`) and
store it as a Parquet file for analysis or archival.

Usage:

```bash
# Basic: export the `articles` table for an existing version to a file
python -m src.cli.main export-snapshot \
  --version-id <VERSION_UUID> \
  --table articles \
  --output artifacts/snapshots/articles_<VERSION_UUID>.parquet
```

Options:

- `--version-id` (required): the `id` of the `DatasetVersion` record to claim and finalize.
- `--table` (required): the database table name to export (e.g., `articles`).
- `--output` (required): destination Parquet file path.
- `--snapshot-chunksize` (optional): rows per chunk when streaming from the database (default: `10000`). Increase for fewer round-trips; decrease to lower memory usage.
- `--snapshot-compression` (optional): Parquet compression. Choose one of `snappy`, `gzip`, `brotli`, `zstd`, or `none`. The value `none` disables compression. Default is `None` (no compression).

Notes:

- If the project is running against Postgres and an advisory lock is available, the exporter will try to acquire a Postgres advisory lock and perform the export inside a `REPEATABLE READ` transaction to produce a consistent snapshot visible to that transaction.
- If `pyarrow` is installed the exporter will stream rows into a Parquet writer. Otherwise the exporter falls back to `pandas.DataFrame.to_parquet`.
- The exporter writes to a temporary file and atomically replaces the final path once the write completes (best-effort `fsync` to improve durability).

Example with compression:

```bash
python -m src.cli.main export-snapshot \
  --version-id 01234567-89ab-cdef-0123-456789abcdef \
  --table articles \
  --output artifacts/snapshots/articles_0123.parquet \
  --snapshot-compression snappy
```

## Workflow

1. **Load Sources:** CSV → Database (candidate_links table)
2. **Crawl:** Query database → Discover article URLs → Store in articles table
3. **Extract:** Process articles → Extract content → Update articles table
4. **Analyze:** ML processing → Store results in ml_results/locations tables

## Usage

```bash
# Run full pipeline
papermill notebooks/0_crawler.ipynb artifacts/crawler_output.ipynb -p run_date 2024-01-01

# Import existing CSV data
python scripts/migrate_csv.py --input-dir ../MizzouNewsCrawler/processed

# View run history
python scripts/list_jobs.py
```

## Development

```bash
# Run tests
pytest tests/

# Database migrations
alembic upgrade head

# Lint code
pre-commit run --all-files
```

## Running tests in VS Code

1. Install the recommended extensions (Python, Pylance) or accept the workspace recommendations.
2. Create and activate a virtual environment in the repository root (the default settings expect `.venv`):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

1. Open the Test Explorer in VS Code (View → Testing). The workspace is configured to use `pytest` and will discover tests under the `tests/` directory.

2. Run tests using the Test Explorer or run the `pytest: run all` task (Terminal → Run Task...). You can also run `pytest -q` in the integrated terminal.

3. To debug a single test, use the Run/Debug gutter controls in the test file or create a debug configuration and point `program` to your `pytest` binary.

## Phase 2 Migration (Future)

- **Cloud SQL**: Managed Postgres with connection pooling
- **GCS Storage**: Raw HTML and artifacts in cloud storage
- **Kubernetes**: Dagster orchestration on GKE
- **Monitoring**: Prometheus/Grafana observability stack
- **CI/CD**: GitHub Actions deployment pipeline

## Fork & Roadmap

This fork is focused on hardening the CSV-to-Database pipeline, improving modularity, and preparing the project for a phased migration to production infrastructure (Postgres, GCS, Kubernetes).

Short-term goals (this fork):

- Stabilize and document the CLI-driven pipeline in `src/cli/main.py` and the example workflow in `example_workflow.py`.
- Improve test coverage for `src/crawler`, `src/models`, and `src/utils` and add CI checks.
- Make the codebase environment-configurable (use `python-dotenv` and a `config.py`) and add clear local dev instructions.
- Add lightweight telemetry using `src/utils/telemetry.py` that can optionally send events to an HTTP endpoint.
- Prepare database layering so SQLite is used for local dev and Postgres for production (use `DATABASE_URL` env var and connection helpers in `src/models/__init__.py`).

Medium-term goals:

- Split the crawler into reusable components: discovery, fetching, parsing, and storage adapters.
- Add idempotent job orchestration (job queue / lightweight scheduler) and integrate `OperationTracker` from `src/utils/telemetry.py` with database `jobs` table.
- Provide Dockerfiles and Helm charts for deploying worker jobs to Kubernetes.

Long-term goals:

- Migrate storage to managed Postgres and Cloud Storage for raw HTML/artifacts.
- Provide CI/CD pipelines, monitoring (Prometheus + Grafana), and automated model deployment for ML steps.

Quick local setup and run

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the example workflow (ensure `sources/publinks.csv` exists or use the included `sources/mizzou_sites.json` for a simple crawl):

```bash
# Run the full example workflow (uses `src.cli.main` commands)
python example_workflow.py

# Or run a single script to crawl sample sites.json into SQLite
python scripts/crawl.py --sources sources/mizzou_sites.json --output-db data/mizzou.db --job-id local-001
```

3. Run tests (after adding tests):

```bash
pytest tests/
```

Contributing & Next Steps

- If you're working on the fork, pick items from the roadmap and open a small PR with focused changes (one area per PR): tests, config, telemetry wiring, DB migration helpers, or Docker/CI.
- I'll continue by drafting a proposed architecture and a prioritized implementation plan (breaking tasks into issues/PRs). If you'd like I can also scaffold a `config.py`, add a `.env.example`, and create initial unit tests for `src/crawler`.

Local markdown checks

If you don't want to install Node-based tools, there's a small, dependency-free
script that performs common markdown checks and safe fixes. Run it from the
repository root:

```bash
python tools/markdownlint_check.py    # show issues
python tools/markdownlint_check.py --apply   # apply safe fixes in-place
```

This script handles a subset of rules (tab replacement, trailing spaces,
blank lines around fenced code blocks and lists, and ordered-list numbering).

Node-based markdownlint (optional)

If you prefer the full Node-based `markdownlint` toolchain, install dev
dependencies and run the provided scripts (requires `npm`):

```bash
# install dev dependencies
npm install

# run checks
npm run lint:md

# run autofix (use with caution)
npm run lint:md:fix
```
