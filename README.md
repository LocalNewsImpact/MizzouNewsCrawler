# MizzouNewsCrawler-Scripts

[![CI](https://github.com/LocalNewsImpact/MizzouNewsCrawler-Scripts/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/LocalNewsImpact/MizzouNewsCrawler-Scripts/actions/workflows/ci.yml)

A CSV-to-Database-driven production version of MizzouNewsCrawler with SQLite backend.

## Overview

This project converts the original MizzouNewsCrawler into a production-ready script architecture with a two-phase approach:

- **Phase 1 — Script-based**: CSV-to-Database-driven crawler with CLI interface and SQLite backend

- **Phase 2 — Production**: Deploy on GKE with Postgres, orchestrate with Kubernetes jobs

## Getting Started

### Prerequisites

- Python 3.11 or newer (the codebase targets modern typing features, numpy 2.x, and Torch 2.x)
- `pip` and `virtualenv` tooling
- SQLite 3 (bundled with Python)
- Optional: Node.js 18+ if you want to run the markdown lint workflow under `npm`

### Installation

```bash
git clone https://github.com/LocalNewsImpact/MizzouNewsCrawler-Scripts.git
cd MizzouNewsCrawler-Scripts
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

If you use `pipx` or Conda, adapt the environment step accordingly. The repo ships a `requirements-dev.txt` with optional lint/test tools; install it via `pip install -r requirements-dev.txt` when you need the full contributor toolchain.

### First Run Checklist

1. Seed the SQLite database with crawler sources:

  ```bash
  python -m src.cli load-sources --csv sources/publinks.csv
  ```

1. Discover a small batch of URLs to confirm the pipeline wiring:

  ```bash
  python -m src.cli discover-urls --source-limit 10 --dry-run
  ```

1. Extract content and inspect the new telemetry-rich content cleaner output:

  ```bash
  python -m src.cli content-cleaning analyze-domains \
    --domain example.com \
    --dry-run \
    --verbose
  ```

1. When you're ready to persist cleaning results, rerun without `--dry-run`. The CLI now truncates article IDs in logs, records timing metadata, and writes removal details back into telemetry tables for downstream ML jobs.

### Manual enqueue batches

Use `scripts/manual_enqueue_urls.py` when you need to seed specific URLs directly into `candidate_links` without running discovery. Every upload is now tied to a dataset so the records remain traceable through verification, extraction, and analytics.

1. Populate the template at `reports/manual_enqueue_template.csv`. Leave the `dataset_id` column blank unless you want to attach the batch to an existing dataset UUID—the script will create a new dataset automatically and print its ID/slug after the insert runs.
1. Run the script from the project root:

   ```bash
   source venv/bin/activate
   python scripts/manual_enqueue_urls.py \
     --input reports/manual_enqueue_template.csv \
     --discovered-by "community-tip" \
     --priority 7 \
     --dataset-label "Community Tip Sheet Sept 2025"
   ```

   Use `--dataset-id` to reuse an existing dataset and `--dry-run` to preview the rows without touching the database.
1. Check the console output for the generated dataset ID. The same identifier is written onto each new `candidate_links` row so you can filter processing telemetry or backfills by batch later.

By default the script connects to the repository SQLite database. In tests you can monkeypatch `DatabaseManager` or set up a scratch database to keep local experiments isolated.

### Format requirements for `sources/publinks.csv`

The `load-sources` command expects a UTF-8 CSV whose headers match the schema below. Every row represents a single publication that the crawler can target.

| Column | Required | Purpose | Example |
| --- | --- | --- | --- |
| `host_id` | ✅ | Stable identifier from the original dataset. Kept as a string so that legacy numeric IDs survive round-trips. | `163` |
| `name` | ✅ | Display name of the outlet. Stored as `Source.canonical_name` and pushed into telemetry dashboards. | `Sikeston Standard Democrat` |
| `city` | ✅ | Primary city for coverage and reporting. Used when summarizing dataset stats. | `Sikeston` |
| `county` | ✅ | County (no "County" suffix needed). Powers geographic filters and CIN analytics. | `Scott` |
| `url_news` | ✅ | An HTTPS article URL or homepage for the outlet. The loader normalizes the host and seeds the initial `candidate_links` table from it. | `https://standard-democrat.com/story/2977919.html` |

The following fields are optional but strongly recommended because downstream jobs read them from `Source.meta` or the `candidate_links` table:

- `frequency` – Free-text publishing cadence (`daily`, `weekly`, `bi-weekly`, etc.). Defaults to `unknown` when omitted.
- `media_type` – One of `print native`, `digital_native`, `audio_broadcast`, `video_broadcast`, or other descriptive tags. The geo filter uses this to tune heuristics (broadcast outlets often contribute fewer URLs).
- `address1` / `address2`, `State`, `zip` – Mailing address metadata. The loader converts `zip` values to strings and stores them for gazetteer enrichment. Two-letter state abbreviations keep the downstream map clean.
- `owner` – Parent company or individual owner.
- `source` – Provenance tag (e.g., `research`, `UNC`, `media cloud`) that helps track how the record entered the dataset.

Cached entity columns capture precomputed coverage areas for the publication. Keep values pipe-delimited (`|`) with plain-text names; the strings are stored verbatim and later reused by the geography-aware filters:

- `cached_geographic_entities`
- `cached_institutions`
- `cached_schools`
- `cached_government`
- `cached_healthcare`
- `cached_businesses`
- `cached_landmarks`

Rows missing any required field are skipped, and duplicate `url_news` hosts collapse into existing `Source` records. When preparing new data drops, validate the header row and run `python -m src.cli load-sources --csv <path>` from a virtual environment to confirm the importer accepts your file.

For a fuller walkthrough (including the end-to-end workflow script and advanced tools), see the "Quick local setup and run" section further down in this document.

## Recent Maintenance (2025-09-27)

### Obituary and opinion detection

- The extraction pipeline now tags obituary and opinion pieces during the
  initial ingest step. Articles matching the new heuristics are stored with
  `status` values of `obituary` or `opinion`, and their detection metadata is
  preserved in `articles.metadata.content_type_detection` for review.
- Tagging these content types ensures they bypass entity extraction and ML
  classification. Downstream services ignore the new statuses without any
  additional configuration.
- Telemetry gains a `content_type_detection_telemetry` table (queried via
  `ComprehensiveExtractionTelemetry.get_content_type_detections`) so reviewers
  can audit heuristics and export high-signal samples for future model
  training.

## Recent Maintenance (2025-09-26)

### Content cleaning telemetry refresh

- `BalancedBoundaryContentCleaner.process_single_article` now returns rich `removal_details`, a `share_header_removed_text` payload, and honors `dry_run` so exploratory runs never mutate the database.
- Social-share headers are detected as a first-class pattern with telemetry logging, giving the CLI immediate insight into what was stripped before persisting updates.
- Telemetry sessions capture the full wire-detection story (including local byline overrides), allowing analytics jobs to distinguish suppressed wire content from genuine local stories.

### CLI content-cleaning commands

- Introduced a `_clean_with_balanced` helper in `src/cli/commands/content_cleaning.py` so every subcommand (`analyze-domains`, `apply-cleaning`, `clean-article`, and the new `clean-content`) shares the same telemetry wiring, dry-run guard, and segment metadata.
- Verbose output is now wrapped to within 79 columns and includes truncated article IDs, pattern classifications, and per-segment confidence/position data for easier triage.
- CLI dry runs mirror production writes: the helper collects processing time, character deltas, and removal payloads even when no database commit occurs.

## Recent Maintenance (2025-09-24)

### Telemetry alignment

- Confirmed that the gazetteer enrichment telemetry is still emitting the full four-event sequence (attempt → geocoding → OSM query → enrichment result). You can tail `gazetteer_telemetry.log` in the repo root to verify the JSON payloads or run a focused dry run with `python scripts/populate_gazetteer.py --address "Columbia, MO" --dry-run` to generate fresh events without mutating the database.
- Verified that `scripts/monitor_gazetteer.py` surfaces the `query_groups_used` counter so the slimmer grouped-query footprint remains visible in console summaries.
- The telemetry JSON continues to play nicely with pytest captures; if you need to confirm structure, `python -m pytest tests/test_telemetry_system.py -k gazetteer -vv` validates the schema the log writer emits.

### Metadata & cleaning fixes

- Normalized `articles.metadata` so that legacy single-quoted Python dict strings are re-serialized as valid JSON. This prevents downstream JSON extraction failures and allowed the classification pipeline to hydrate publication context again. The one-off cleanup snippet we ran is preserved below for future backfills:

  ```python
  import json
  import sqlite3
  from ast import literal_eval

  with sqlite3.connect("data/mizzou.db") as conn:
    rows = conn.execute(
      "SELECT id, metadata FROM articles WHERE metadata LIKE '{%'"
    ).fetchall()
    for article_id, raw in rows:
      try:
        normalized = json.dumps(literal_eval(raw))
      except (SyntaxError, ValueError):
        continue
      conn.execute(
        "UPDATE articles SET metadata = ? WHERE id = ?",
        (normalized, article_id),
      )
    conn.commit()
  ```

- After normalizing metadata, rerun the `clean_authors.py` smoke checks to ensure the Gazetteer-driven organization filters still match publication names pulled from metadata.
- Spot-check content-cleaning telemetry with `python detailed_content_analysis.py --domain example.com` to confirm that newly captured segments continue to hydrate the `content_cleaning_telemetry` tables without JSON parsing errors.

### CIN classifier rollout

- `models/productionmodel.pt` is now the default CIN checkpoint used by the CLI `analyze` command. The loader in `src/ml/article_classifier.py` remaps legacy `classifier_primary.*` keys so the model initializes cleanly on CPU. Expect an informational log confirming the resolved checkpoint path when the model loads.
- To refresh the label store after the checkpoint swap, we executed:

  ```bash
  source venv/bin/activate
  python -m src.cli analyze \
    --model-path models/productionmodel.pt \
    --label-version cin-2024q4 \
    --statuses cleaned local \
    --batch-size 32
  ```

  The first pass reprocessed the 50 provisional articles; a second run without `--limit` cleared the remaining 2,341 eligible records.
- The latest classification export lives in `reports/cin_labels_last14days_with_sources.csv`. It excludes wire stories, joins publication name/city/county metadata, and is written with UTF-8 encoding for compatibility with downstream analytics notebooks.
- When adding new CIN labels, continue filtering on `articles.source_is_wire = 0` and persist the joined dataset via pandas’ `to_csv(..., encoding="utf-8", index=False)` to match the sanitized export format.

## LLM summarization pipeline

### Why we summarize articles

- **Editorial context**: Each run yields a few sentences that restate the article’s subject, the main action, plus the provider metadata saved in `Article.meta["llm"].summary`. The pipeline does not emit CIN predictions or other structured outputs on its own.
- **Metadata smoke test**: The prompt template composes each request from the article title, author/byline, publish date, URL, and cleaned body text. If any of those fields are missing, the summary run highlights the gap (`unknown` placeholders surface immediately), making this an ideal checkpoint for validating DOM extraction rules.
- **Model comparison**: Because the summarisation run captures the same article metadata used by the CIN classifier, you can compare LLM-derived interpretations with the classifier’s Critical Information Needs output or the predictions from other providers when you need a sanity check.

### Configuration

Populate the relevant environment variables (see `.env.example` for a full list):

- `LLM_PROVIDER_SEQUENCE`: Comma-separated provider slugs in fallback order (default: `openai-gpt4.1,openai-gpt4.1-mini,claude-3.5-sonnet,gemini-1.5-flash`).
- `OPENAI_API_KEY`, `OPENAI_ORGANIZATION`: Credentials for GPT‑4.1 models.
- `ANTHROPIC_API_KEY`: Enables Claude 3.5 Sonnet.
- `GOOGLE_API_KEY`: Enables Gemini 1.5 Flash.
- `LLM_REQUEST_TIMEOUT`, `LLM_MAX_RETRIES`, `LLM_DEFAULT_MAX_OUTPUT_TOKENS`, `LLM_DEFAULT_TEMPERATURE`: Optional overrides for orchestration behavior.
- `VECTOR_STORE_PROVIDER` (plus provider-specific keys like `PINECONE_API_KEY`, `WEAVIATE_URL`, etc.): Turns on embedding/vector storage when available; the factory falls back to a no-op when unset.

### CLI usage

```bash
source venv/bin/activate
python -m src.cli llm status

# Generate summaries for the most recent "cleaned" articles without committing results
python -m src.cli llm run --statuses cleaned local --limit 10 --dry-run --show-failures

# Persist summaries for everything in "cleaned" status (omit --dry-run)
python -m src.cli llm run --statuses cleaned local --limit 50
```

- `llm status` prints the active provider order, which API keys are configured, and any vector-store integration that will be used.
- `llm run` orchestrates the provider sequence, writing summary metadata (or failure details) back to each article. Use `--dry-run` while tuning selectors and `--show-failures` to inspect per-provider errors.
- `--prompt-template` accepts a custom prompt file if you need domain-specific instructions for QA runs.

### Suggested QA workflow

1. Run your usual discovery/extraction path to populate `Article` rows with CIN predictions and cleaned content.
1. Execute `python -m src.cli llm run --statuses cleaned --limit 20 --dry-run --show-failures` to exercise the prompt template without committing results.
1. Inspect the console output (or the `Article.meta["llm"]` payload when not in dry-run mode) and confirm that the title/byline/publish date fields look correct, the summary echoes the Critical Information Needs classification already applied by the CIN model, and provider failures (if any) call out missing credentials or rate limits before you scale up batches.

## Architecture

**CSV-to-Database-Driven Design:**

1. Load `publinks.csv` into SQLite database (one-time setup)

1. All crawler operations are driven from database queries

1. Support filtering by ALL/HOST/COUNTY/CITY with configurable limits

1. Database tracks crawling progress and status

### Architectural Patterns & Solutions

**API Optimization Strategy:**

- **Grouped Query Pattern**: Logical grouping of related API calls to reduce total requests while maintaining comprehensive coverage

- **Rate Limiting & Backoff**: Respectful API usage with configurable delays and retry mechanisms

- **Fallback Mechanisms**: Graceful degradation when complex queries fail, with automatic fallback to individual calls

**Geographic Data Integration:**

- **OpenStreetMap Integration**: Comprehensive geographic entity discovery using OSM Overpass API

- **Intelligent Categorization**: 11-category system covering civic, commercial, recreational, and cultural entities

- **Query Optimization**: 67% API call reduction through smart filter grouping and wildcard replacement

**Error Handling & Resilience:**

- **Robust Query Processing**: Automatic handling of problematic OSM filters (e.g., `historic=*` wildcards)

- **Element Distribution Logic**: Accurate categorization of geographic entities based on OSM tags

- **Debug Instrumentation**: Comprehensive logging for monitoring, troubleshooting, and performance analysis

**Scalability Patterns:**

- **Database-Driven Operations**: All crawler activities driven by database state, enabling distributed processing

- **Modular Component Design**: Separated concerns for crawling, content extraction, geographic processing, and data storage

- **Background Processing**: Automatic gazetteer population triggered by data loading events

## Phase 1 Architecture

### Project Structure

```text
├── src/                    # Core business logic
│   ├── cli/               # Command-line interface
│   │   ├── main.py        # Main CLI entry point with all commands
│   │   └── commands/      # Modular command implementations
│   ├── crawler/           # Web crawling and URL discovery
│   │   ├── discovery.py   # Article URL discovery logic
│   │   └── scheduling.py  # Publication frequency and timing
│   ├── pipeline/          # Content processing pipeline
│   │   ├── crawler.py     # Web crawling implementation
│   │   ├── extractors.py  # Content extraction logic
│   │   ├── site_filters.py # Site-specific filtering rules
│   │   └── url_filters.py # URL validation and filtering
│   ├── services/          # External service integrations
│   │   └── url_verification.py # URL verification service
│   ├── models/            # SQLAlchemy database models
│   ├── utils/             # Shared utilities and processing
│   │   ├── byline_cleaner.py           # Advanced byline processing
│   │   ├── byline_telemetry.py         # Byline processing metrics
│   │   ├── content_cleaner_balanced.py # Boilerplate detection and removal
│   │   ├── content_cleaning_telemetry.py # Content cleaning metrics and ML data
│   │   ├── telemetry.py                # System-wide telemetry
│   │   ├── comprehensive_telemetry.py  # Extraction performance tracking
│   │   └── process_tracker.py          # Background process monitoring
│   ├── lookups/           # Geographic and entity lookups
│   └── config.py          # Configuration management
├── sources/               # Input data (publinks.csv, sites.json)
├── data/                  # SQLite databases and local storage
├── artifacts/             # Generated outputs and snapshots
├── tests/                 # Test suite
│   ├── test_telemetry_system.py    # Comprehensive extraction telemetry tests
│   ├── test_telemetry_api.py       # FastAPI dashboard endpoint tests
│   └── ...                         # Other test files
├── backend/               # FastAPI dashboard backend
│   └── app/
│       └── main.py        # Dashboard API endpoints for React integration
├── tools/                 # Development and maintenance scripts
├── requirements.txt       # Python dependencies
└── example_workflow.py    # Complete workflow demonstration
```

### Database Schema

- **candidate_links**: Source publications loaded from publinks.csv

- **articles**: Discovered article URLs and extracted content

- **extraction_telemetry_v2**: Comprehensive extraction performance tracking with method timings, HTTP metrics, and field-level success rates

- **http_error_summary**: Aggregated HTTP error tracking by host and status code

- **ml_results**: ML analysis results with model versioning

- **locations**: Extracted geographic entities

- **jobs**: Processing job tracking and audit trail

### Key Features

- **CLI Interface**: Complete command-line interface for all operations

- **Database-Driven**: All operations query SQLite database for sources

- **Flexible Filtering**: Support ALL/HOST/COUNTY/CITY filters with limits

- **Status Tracking**: Database tracks crawling progress and errors

- **Comprehensive Telemetry**: Real-time extraction performance monitoring with HTTP error tracking and dashboard API

- **Site Management**: Automated poor performer detection with pause/resume controls

- **Modular Design**: Core logic extracted to importable src/ modules

## Content Processing & Quality Assurance

The project includes sophisticated content processing and quality assurance systems to ensure accurate author attribution and content validation.

### Enhanced Byline Cleaning

The `BylineCleaner` system provides intelligent author name extraction with advanced filtering capabilities:

**Dynamic Publication Filtering:**

- **Gazetteer Integration**: Leverages database queries to identify publication and organization names dynamically

- **Fuzzy Matching**: Uses sequence matching to detect publication names with 80%+ similarity threshold

- **Smart Partial Removal**: Intelligently removes publication words while preserving author names in mixed content

**Advanced Name Processing:**

- **Comma Detection**: Handles comma-separated content like "Ava Gorton, Campus Activities" → returns "Ava Gorton"

- **First Name Protection**: Maintains common US English first names (60+ entries) to prevent removal by organization filtering

- **Type Classification**: Multi-level identification distinguishing names, emails, titles, and mixed content

- **Organization Pattern Recognition**: 11-category system covering educational, government, business, and media organizations

**Wire Service Handling:**

- **Automatic Detection**: Recognizes 25+ wire services and syndicated content sources

- **Preservation Logic**: Maintains attribution for legitimate news sources while filtering noise

**Quality Assurance:**

- **Length-Based Filtering**: Organization words >3 characters to prevent over-aggressive removal

- **Validation Pipeline**: Multi-step verification ensuring person names are preserved

- **Edge Case Resolution**: Handles complex scenarios like "Richard Nations" full name preservation

### Comprehensive Telemetry System

**Real-Time Processing Tracking:**

- **Transformation Steps**: Detailed logging of each byline processing stage

- **Confidence Scoring**: Dynamic confidence deltas for each cleaning operation

- **Performance Metrics**: Processing time and success rate monitoring

**Quality Metrics:**

- **Author Validation**: Classification of likely valid authors vs. noise detection

- **Manual Review Flagging**: Automatic identification of complex cases requiring human review

- **Success Rate Tracking**: Comprehensive statistics on cleaning effectiveness

**Debugging & Monitoring:**

- **Step-by-Step Logging**: Complete audit trail of text transformations

- **Error Classification**: Categorized error reporting for different failure modes

- **Session Management**: Unique tracking IDs for correlating processing across systems

### Story Validation & Content Quality

**Content Validation Pipeline:**

- **Publication Name Filtering**: Dynamic removal of publication names from author fields

- **Mixed Content Handling**: Intelligent separation of person names from organizational affiliations

- **Consistency Checking**: Cross-validation against known publication databases

**Database Integration:**

- **SQLAlchemy Integration**: Seamless database queries for publication and organization data

- **Caching System**: Optimized performance with publication name caching

- **Dynamic Updates**: Real-time integration with gazetteer data for organization recognition

### Content Cleaning & Boilerplate Detection

The project includes an advanced content cleaning system that automatically identifies and removes boilerplate content (navigation menus, sidebars, subscription prompts) while preserving legitimate article text.

**Intelligent Pattern Recognition:**

- **Balanced Boundary Detection**: Two-phase approach using rough candidate identification followed by precise boundary refinement to avoid clipping article content

- **Pattern Classification**: Multi-category system distinguishing sidebar content, subscription prompts, navigation menus, and footer elements

- **Confidence Scoring**: 0.0-1.0 confidence scale for removal decisions with detailed boundary quality assessment

**Persistent Pattern Library:**

- **Domain-Specific Storage**: Reusable boilerplate patterns saved per domain for efficient future processing

- **ML Training Distinction**: Persistent patterns (subscription, navigation, footer) marked for ML training; dynamic patterns (headlines, trending) captured for telemetry only

- **Cross-Domain Analysis**: Global pattern library enabling insights across multiple news sources

**Comprehensive Telemetry System:**

- **Session Tracking**: Complete audit trail of cleaning sessions with domain, article counts, and processing metrics

- **Segment-Level Logging**: Detailed capture of each detected boilerplate segment including position, confidence, occurrence frequency, and removal reasoning

- **Pattern Type Classification**: Automatic categorization into subscription, sidebar, navigation, trending, and other pattern types

- **ML-Ready Data Structure**: Telemetry schema designed for machine learning model training with feature extraction capabilities

**Quality Assurance:**

- **Boundary Validation**: Strict sentence boundary detection to prevent partial content removal

- **Position Consistency**: Analysis of content placement across articles to confirm boilerplate status

- **Manual Review Integration**: Flagging of complex patterns for human validation before automated removal

**CLI Analysis Tools:**

- **Domain-Specific Analysis**: `detailed_content_analysis.py` for examining boilerplate patterns within specific domains

- **Cross-Domain Insights**: `dry_run_content_cleaning.py` for analyzing patterns across entire database

- **Pattern Visualization**: `show_patterns.py` for viewing ML training vs telemetry pattern distinctions

## Gazetteer Telemetry System

The project includes a comprehensive telemetry system for monitoring gazetteer population processes, providing detailed insights into geographic data processing, API usage, and system performance.

### Telemetry Architecture

**GazetteerTelemetry Class:**

- **Structured JSON Logging**: All telemetry events recorded as structured JSON for easy parsing and analysis

- **Multi-Event Tracking**: Four distinct event types covering the complete gazetteer enrichment pipeline

- **Dual Output Support**: Configurable file and console logging for development and production environments

- **pytest Integration**: Proper logging configuration enables test capture with `caplog` for development workflow

### Telemetry Event Types

**1. Enrichment Attempt (`enrichment_attempt`)**

```json
{
  "timestamp": "2025-09-21T17:39:31.383301",
  "event": "enrichment_attempt",
  "source_id": "source-uuid-123",
  "source_name": "Example News Source",
  "location_data": {
    "city": "Columbia",
    "county": "Boone County",
    "state": "MO"
  }
}
```

**2. Geocoding Result (`geocoding_result`)**

```json
{
  "timestamp": "2025-09-21T17:39:31.387130",
  "event": "geocoding_result",
  "source_id": "source-uuid-123",
  "geocoding": {
    "method": "nominatim",
    "address_used": "Columbia, Boone County, MO",
    "success": true,
    "coordinates": {"lat": 38.9517, "lon": -92.3341},
    "error": null
  }
}
```

**3. OSM Query Result (`osm_query_result`)**

```json
{
  "timestamp": "2025-09-21T17:39:31.394615",
  "event": "osm_query_result",
  "source_id": "source-uuid-123",
  "osm_data": {
    "total_elements": 3070,
    "categories": {
      "schools": 105,
      "government": 46,
      "healthcare": 89,
      "businesses": 1183
    },
    "query_groups_used": 3,
    "radius_miles": 20
  }
}
```

**4. Enrichment Result (`enrichment_result`)**

```json
{
  "timestamp": "2025-09-21T17:39:31.402806",
  "event": "enrichment_result",
  "source_id": "source-uuid-123",
  "result": {
    "success": true,
    "total_inserted": 157,
    "categories_inserted": {
      "schools": 15,
      "businesses": 89,
      "government": 8
    },
    "failure_reason": null,
    "processing_time_seconds": 45.2
  }
}
```

### Geocoding Precision Levels

**Three-Tier Fallback System:**

1. **street_address**: Full address geocoding (most precise)
1. **city_county**: City + county + state fallback when address fails
1. **zip_code**: ZIP code-only geocoding (least precise, maximum coverage)

### Production Usage

**Telemetry Log File**: `gazetteer_telemetry.log` (structured JSON, one event per line)

**Running with Telemetry:**

```bash
# Production gazetteer population with full telemetry
python scripts/backfill_gazetteer_slow.py

# Single source telemetry testing
python scripts/populate_gazetteer.py --address "Columbia, MO" --dry-run

# Dataset-specific telemetry
python scripts/populate_gazetteer.py --dataset "publinks-2025-09"
```

### Test Suite

**Comprehensive Testing Infrastructure:**

- **7 pytest test cases** validating all telemetry functionality
- **JSON structure validation** ensuring proper event formatting
- **Parameter validation** for all telemetry methods
- **Logging integration testing** with pytest `caplog` support

**Running Telemetry Tests:**

```bash
# Run complete telemetry test suite
python -m pytest tests/test_actual_telemetry.py -v

# Run with logging output
python -m pytest tests/test_actual_telemetry.py -v -s --log-cli-level=INFO
```

**Test Coverage:**

- `test_log_enrichment_attempt`: Validates enrichment attempt logging
- `test_log_geocoding_result_success/failure`: Tests geocoding result tracking
- `test_log_osm_query_result`: Validates OSM query result logging
- `test_log_enrichment_result_success/failure`: Tests final outcome tracking
- `test_log_structure_consistency`: Ensures consistent JSON formatting

### Monitoring and Analysis

**Performance Metrics:**

- **API Usage Tracking**: Monitor OSM Overpass API calls and response times
- **Geocoding Success Rates**: Track precision levels and fallback usage
- **Processing Efficiency**: Monitor elements processed per source and timing
- **Error Analysis**: Categorize and track failure modes for improvement

**Data Quality Insights:**

- **Geographic Coverage**: Analyze OSM element distribution by category
- **Precision Analysis**: Understand geocoding accuracy across different location types
- **Source Quality**: Identify sources with problematic geographic data
- **Category Distribution**: Monitor which types of geographic entities are most/least common

**Production Monitoring:**

```bash
# Monitor real-time telemetry (requires tail)
tail -f gazetteer_telemetry.log | jq .

# Analyze geocoding success rates
grep "geocoding_result" gazetteer_telemetry.log | jq '.geocoding.success' | sort | uniq -c

# Review OSM data quality
grep "osm_query_result" gazetteer_telemetry.log | jq '.osm_data.total_elements' | sort -n
```

### Development Workflow

**No More Production Debugging:**

- **Comprehensive Test Suite**: All telemetry functionality validated before deployment
- **Local Testing**: Full telemetry validation without external API calls
- **Structured Logging**: Easy debugging with consistent JSON event format
- **pytest Integration**: Proper logging configuration enables development testing

**Development Best Practices:**

```bash
# Always run tests before production deployment
python -m pytest tests/test_actual_telemetry.py

# Use dry-run mode for telemetry validation
python scripts/populate_gazetteer.py --address "Test Address" --dry-run

# Monitor telemetry logs during development
tail -f gazetteer_telemetry.log | jq .
```

## Comprehensive Extraction Telemetry & Dashboard System

The project includes a comprehensive telemetry system for monitoring content extraction performance, HTTP errors, and site health, providing real-time insights for automated site management and React dashboard integration.

### Extraction Telemetry Architecture

**ExtractionMetrics Class:**

- **Method-Level Tracking**: Detailed timing and success tracking for each extraction method (newspaper4k, beautifulsoup, fallback)
- **HTTP Status Monitoring**: Automatic capture of HTTP status codes and error categorization (4xx_client_error, 5xx_server_error)
- **Field-Level Success**: Granular tracking of title, content, author, and date extraction success rates
- **Error Pattern Recognition**: Regex-based extraction of HTTP status codes from newspaper4k error messages

**ComprehensiveExtractionTelemetry Database:**

- **extraction_telemetry_v2**: Detailed extraction records with method timings, field success, and HTTP metrics
- **http_error_summary**: Aggregated HTTP error tracking by host and status code
- **Real-Time Aggregation**: Automatic rollup of error counts and performance statistics

### FastAPI Dashboard API Endpoints

**Telemetry Data Endpoints:**

```bash
# Overall extraction statistics and performance summary
GET /api/telemetry/summary?days=7

# HTTP error breakdown by host, status code, and time period
GET /api/telemetry/http-errors?days=7&host=example.com&status_code=403

# Extraction method performance analysis
GET /api/telemetry/method-performance?days=7

# Publisher-specific statistics and health metrics
GET /api/telemetry/publisher-stats?days=7&min_attempts=5

# Poor performing sites requiring attention
GET /api/telemetry/poor-performers?days=7&min_attempts=10&max_success_rate=25

# Field-level extraction success rates by method
GET /api/telemetry/field-extraction?days=7
```

**Site Management API:**

```bash
# Pause problematic sites based on performance thresholds
POST /api/site-management/pause
{
  "host": "problematic-site.com",
  "reason": "Poor performance: 0% success rate with 15 attempts"
}

# Resume paused sites after manual review
POST /api/site-management/resume
{
  "host": "fixed-site.com"
}

# List all currently paused sites
GET /api/site-management/paused

# Check individual site status
GET /api/site-management/status/example.com
```

### HTTP Error Detection & Tracking

**Automatic HTTP Status Extraction:**

- **Regex Pattern Matching**: Extracts HTTP status codes from newspaper4k error messages using pattern `Status code (\d+)`
- **Error Type Categorization**: Automatically categorizes errors as 3xx_redirect, 4xx_client_error, or 5xx_server_error
- **Publisher Error Aggregation**: Tracks error counts per host with first_seen and last_seen timestamps

**Error Tracking Examples:**

```python
# Error message: "Article `download()` failed with Status code 403"
# → Extracted: HTTP 403, Type: 4xx_client_error

# Error message: "HTTP Error: Status code 500 Internal Server Error"  
# → Extracted: HTTP 500, Type: 5xx_server_error

# Automatic site management recommendation based on error patterns
# → Sites with >80% error rates flagged for pause recommendation
```

### Dashboard Integration Features

**Real-Time Performance Monitoring:**

- **Success Rate Tracking**: Publisher-level success rates with configurable thresholds
- **Method Effectiveness**: Comparative performance of extraction methods across publishers
- **HTTP Error Patterns**: Identification of systematic HTTP error patterns by host
- **Field Extraction Quality**: Title, content, author extraction success rates per method

**Automated Site Management:**

- **Poor Performer Detection**: Automatic identification of sites with low success rates
- **Pause/Resume Controls**: API-driven site management with reason tracking
- **Human Feedback Loop**: Dashboard integration for manual site management decisions
- **Performance Threshold Alerts**: Configurable thresholds for automated recommendations

### Comprehensive Test Suite

**Test Coverage:**

- **Unit Tests**: ExtractionMetrics class functionality and HTTP status extraction
- **Integration Tests**: Database operations and ComprehensiveExtractionTelemetry methods
- **API Tests**: FastAPI endpoint functionality with mocked databases
- **End-to-End Tests**: Complete workflow simulation from extraction to dashboard data

**Running Telemetry Tests:**

```bash
# Run complete telemetry system test suite
python -m pytest tests/test_telemetry_system.py -v

# Test FastAPI endpoints
python -m pytest tests/test_telemetry_api.py -v

# Test HTTP error extraction functionality
python -c "
from src.utils.comprehensive_telemetry import ExtractionMetrics
metrics = ExtractionMetrics('test', 'test', 'https://test.com', 'test.com')
# ... test HTTP status extraction from error messages
"
```

**Production Integration:**

```bash
# Initialize telemetry system in extraction pipeline
from src.utils.comprehensive_telemetry import ExtractionMetrics, ComprehensiveExtractionTelemetry

# Start FastAPI backend for dashboard
uvicorn backend.app.main:app --reload --port 8000

# Access telemetry dashboard endpoints
curl http://localhost:8000/api/telemetry/summary?days=7
curl http://localhost:8000/api/telemetry/poor-performers?max_success_rate=50
```

## Quick Start

```bash
# Setup environment
pip install -r requirements.txt

# Load sources into database (one-time setup)
python -m src.cli load-sources --csv sources/publinks.csv

# Discover article URLs (smart scheduling)
python -m src.cli discover-urls --source-limit 10

# Extract content from discovered articles
python -m src.cli extract --limit 20

# Check status and results
python -m src.cli status

# Or run complete example workflow
python example_workflow.py
```

## CLI Usage

The project provides a comprehensive command-line interface through `python -m src.cli` (with `python -m src.cli.main` retained for backward compatibility) with the following commands:

### Core Workflow Commands

#### Load Sources (One-time Setup)

```bash
# Load publinks.csv into database
python -m src.cli load-sources --csv sources/publinks.csv

# Load with specific dataset label
python -m src.cli load-sources --csv sources/publinks.csv --dataset "publinks-2025-09"
```

#### URL Discovery

Discover article URLs using newspaper4k and storysniffer with intelligent scheduling:

```bash
# Discover URLs for sources due for collection (default behavior)
python -m src.cli discover-urls --source-limit 50

# Force discovery for all sources (ignore publication frequency)
python -m src.cli discover-urls --source-limit 10 --force-all

# Discover for specific source
python -m src.cli discover-urls --source-uuid 12345678-1234-1234-1234-123456789abc

# Discover with custom article limits and time range
python -m src.cli discover-urls --max-articles 100 --days-back 14 --source-limit 25

# Filter sources by name/URL pattern
python -m src.cli discover-urls --source-filter "missouri" --source-limit 20

# Target a single host (exact match on candidate host)
python -m src.cli discover-urls --host "standard-democrat.com" --max-articles 40

# Filter by location metadata
python -m src.cli discover-urls --county "St. Louis" --city "Ferguson" --host-limit 5

# Skip saturated sources that already have enough extracted articles
python -m src.cli discover-urls --existing-article-limit 75 --source-limit 30
```

**Key Options:**

- `--due-only`: Only process sources due for discovery (enabled by default)
- `--force-all`: Override scheduling and process all sources (disables `--due-only`)
- `--max-articles`: Articles to discover per source (default: 50); legacy alias `--article-limit`
- `--existing-article-limit`: Skip sources that already have at least this many extracted articles (also set when using `--article-limit`)
- `--source-filter` / `--source`: Match sources by name or URL substring
- `--host`, `--city`, `--county`: Filter sources by metadata fields from `publinks`
- `--host-limit`: Cap the number of unique hosts processed in one run
- `--days-back`: How far back to look for articles (default: 7 days)

#### Content Extraction

Extract article content from discovered URLs:

```bash
# Extract content from articles (default: 10 articles, 1 batch)
python -m src.cli extract

# Extract larger batches
python -m src.cli extract --limit 50 --batches 5

# Extract from specific source only
python -m src.cli extract --source "Columbia Missourian" --limit 25
```

### Deprecated Crawl Alias

The legacy `crawl` command now emits a deprecation warning and forwards all
arguments to `discover-urls`. Prefer running `discover-urls` directly so you get
access to the richer filtering options above. Example translation:

- Legacy: `python -m src.cli crawl --filter HOST --host standard-democrat.com --article-limit 10`
- Modern: `python -m src.cli discover-urls --host standard-democrat.com --article-limit 10`

All existing automation that still invokes `crawl` will continue to work, but
please plan to migrate scripts to `discover-urls` to avoid the warning and stay
on the supported path.

### Geographic Enhancement

#### Populate Gazetteer

Populate gazetteer table with geographic entities near publisher locations:

```bash
# Populate gazetteer for all datasets
python -m src.cli populate-gazetteer

# Populate gazetteer for specific dataset
python -m src.cli populate-gazetteer --dataset "publinks-2025-09"

# Test with specific address
python -m src.cli populate-gazetteer --address "Columbia, MO" --radius 25

# Dry run (no database writes)
python -m src.cli populate-gazetteer --dry-run --address "Columbia, MO"
```

### Monitoring and Analysis

#### Status and Process Monitoring

```bash
# Show crawling statistics
python -m src.cli status

# Show background processes
python -m src.cli status --processes

# Show detailed status for specific process
python -m src.cli status --process abc123

# Show active background processes queue
python -m src.cli queue
```

#### Discovery Reporting

Generate detailed reports on URL discovery outcomes:

```bash
# Generate summary discovery report (last 24 hours)
python -m src.cli discovery-report

# Generate detailed report for last 48 hours
python -m src.cli discovery-report --hours-back 48 --format detailed

# Report for specific operation
python -m src.cli discovery-report --operation-id abc123 --format json

# Export report in JSON format
python -m src.cli discovery-report --format json --hours-back 72
```

#### Source Management

```bash
# List all sources with UUIDs and details
python -m src.cli list-sources

# Filter sources by dataset
python -m src.cli list-sources --dataset "publinks-2025-09"

# Show HTTP status tracking for specific source
python -m src.cli dump-http-status --source-uuid 12345678-1234-1234-1234-123456789abc
```

### Data Versioning and Export

#### Dataset Version Management

```bash
# Create a new dataset version
python -m src.cli create-version --dataset candidate_links --tag v2025-09-21-1 --description "Updated source list"

# List all dataset versions
python -m src.cli list-versions

# List versions for specific dataset
python -m src.cli list-versions --dataset candidate_links

# Export a dataset version
python -m src.cli export-version --version-id 12345678-1234-1234-1234-123456789abc --output exports/candidate_links_v1.parquet
```

#### Snapshot Export

Create Parquet snapshots from database tables:

```bash
# Basic snapshot export
python -m src.cli export-snapshot \
  --version-id 12345678-1234-1234-1234-123456789abc \
  --table articles \
  --output artifacts/snapshots/articles_20250921.parquet

# Export with compression
python -m src.cli export-snapshot \
  --version-id 12345678-1234-1234-1234-123456789abc \
  --table candidate_links \
  --output artifacts/snapshots/sources_compressed.parquet \
  --snapshot-compression snappy

# Export with custom chunk size for large tables
python -m src.cli export-snapshot \
  --version-id 12345678-1234-1234-1234-123456789abc \
  --table articles \
  --output artifacts/snapshots/articles_large.parquet \
  --snapshot-chunksize 50000 \
  --snapshot-compression gzip
```

**Compression Options:** `snappy`, `gzip`, `brotli`, `zstd`, `none`

### ML Analysis

```bash
# Run ML analysis on extracted content
python -m src.cli analyze
```

### Common CLI Patterns

```bash
# Complete discovery and extraction workflow
python -m src.cli discover-urls --source-limit 20 --max-articles 50
python -m src.cli extract --limit 100 --batches 3
python -m src.cli status

# Targeted source processing
python -m src.cli discover-urls --source-filter "columbia" --force-all
python -m src.cli extract --source "Columbia Missourian"

# Create and export versioned snapshot
python -m src.cli create-version --dataset articles --tag v2025-09-21-final
python -m src.cli export-snapshot --version-id <VERSION_ID> --table articles --output final_articles.parquet
```

**Note**: All commands support `--log-level {DEBUG,INFO,WARNING,ERROR}` for controlling output verbosity.

### Populate Gazetteer

Populate gazetteer table with geographic entities (schools, businesses, landmarks, etc.) near publisher locations using OpenStreetMap data. This is automatically triggered when loading new sources, but can also be run manually.

```bash
# Populate gazetteer for all datasets
python -m src.cli populate-gazetteer

# Populate gazetteer for specific dataset
python -m src.cli populate-gazetteer --dataset "publinks-2025-09"

# Test with specific address
python -m src.cli populate-gazetteer --address "Columbia, MO" --radius 25

# Dry run (no database writes)
python -m src.cli populate-gazetteer --dry-run --address "Columbia, MO"
```

**Note**: Gazetteer population is automatically triggered in the background when new publisher/host records are loaded via `load-sources`. The process uses OpenStreetMap APIs and includes respectful rate limiting.

#### Batch Gazetteer Processing

For processing large numbers of sources, use the specialized backfill script with conservative rate limiting:

```bash
# Conservative batch processing with 5-8 second delays between sources
python scripts/backfill_gazetteer_slow.py

# Script features:
# - Rate limiting: 5-8 seconds between sources (respectful to OSM APIs)
# - Progress tracking: Shows completed vs total sources
# - Resume capability: Skips already-processed sources automatically
# - Comprehensive telemetry: Full JSON logging to gazetteer_telemetry.log
```

**Recommended for:**

- Initial population of large source datasets (100+ sources)
- Production environments where API rate limiting is critical
- Unattended batch processing with comprehensive monitoring

#### OSM Gazetteer Optimization

The gazetteer system has been optimized for efficiency and comprehensive coverage:

**Performance Optimization:**

- **API Call Reduction**: 67% fewer API calls (4 vs 12) through intelligent query grouping

- **Smart Grouping**: Logical category groups that maximize query efficiency while maintaining coverage

- **Rate Limiting**: Respectful API usage with appropriate delays between requests

**Comprehensive Geographic Coverage:**

- **11 Categories**: Schools, government, healthcare, businesses, landmarks, sports, transportation, religious, entertainment, economic, emergency

- **61 OSM Filters**: Complete filter set covering diverse geographic entities

- **3-Group Architecture**:

  - `civic_essential` (18 filters): schools, government, healthcare, emergency

  - `commercial_recreation` (25 filters): businesses, economic, entertainment, sports

  - `infrastructure_culture` (18 filters): transportation, landmarks, religious

**Technical Solutions:**

- **Fixed Historic Filter**: Replaced problematic `historic=*` wildcard with specific values (`historic=building`, `historic=monument`, `historic=memorial`, `historic=ruins`, `historic=archaeological_site`)

- **Element Distribution**: Intelligent categorization of OSM results back to specific categories

- **Fallback Mechanisms**: Robust error handling with individual query fallbacks for complex query failures

- **Debug Instrumentation**: Comprehensive logging for monitoring and troubleshooting

**Validation Results** (Columbia, MO test):

- **3,070 elements** discovered within 20-mile radius

- **100% success rate** across all category groups

- **Excellent coverage** of schools (105), transportation (1,257), sports (686), and other categories

- **Production verified** in both single-address and database modes

### Export a Snapshot (table -> Parquet)

Create a Parquet snapshot by exporting a database table for a given
dataset version. This command is useful when you want to materialize a
consistent snapshot of a table (e.g., `articles` or `candidate_links`) and
store it as a Parquet file for analysis or archival.

Usage:

```bash
# Basic: export the `articles` table for an existing version to a file
python -m src.cli export-snapshot \
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
python -m src.cli export-snapshot \
  --version-id 01234567-89ab-cdef-0123-456789abcdef \
  --table articles \
  --output artifacts/snapshots/articles_0123.parquet \
  --snapshot-compression snappy
```

## Workflow

### Primary Workflow (Recommended)

1. **Load Sources:** CSV → Database (candidate_links table) + **Auto-trigger gazetteer population**

1. **Discover URLs:** Smart discovery using publication frequency and timing → Store URLs in articles table

1. **Extract Content:** Process discovered articles → Extract and clean content → Update articles table

1. **Analyze:** ML processing → Store results in ml_results/locations tables

### Alternative Legacy Workflow

1. **Load Sources:** CSV → Database (candidate_links table) + **Auto-trigger gazetteer population**

1. **Crawl:** Query database → Discover article URLs → Store in articles table

1. **Extract:** Process articles → Extract content → Update articles table

1. **Analyze:** ML processing → Store results in ml_results/locations tables

**Geographic Enhancement**: When new sources are loaded, the system automatically triggers gazetteer population in the background. This process geocodes publisher locations and discovers nearby geographic entities (schools, businesses, landmarks, etc.) using OpenStreetMap APIs.

**Smart Discovery**: The `discover-urls` command uses intelligent scheduling based on publication frequency (daily, weekly, etc.) and last collection dates to optimize resource usage and respect publisher policies.

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

### Content Cleaning Tools

The project includes specialized tools for analyzing and implementing content cleaning:

```bash
# Dry run content cleaning across all articles
python dry_run_content_cleaning.py

# Detailed content analysis for a specific domain
python detailed_content_analysis.py douglascountyherald.com

# Show persistent pattern analysis (ML training vs telemetry patterns)
python show_patterns.py www.douglascountyherald.com

# View cross-domain pattern summary
python show_patterns.py --summary

# Test ML training vs telemetry pattern separation
python test_ml_telemetry.py
```

These tools use the `BalancedBoundaryContentCleaner` and `ContentCleaningTelemetry` systems to identify and remove boilerplate content while maintaining comprehensive tracking for quality assurance and machine learning applications.

## Running tests in VS Code

1. Install the recommended extensions (Python, Pylance) or accept the workspace recommendations.

1. Create and activate a virtual environment in the repository root (the default settings expect `.venv`):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

1. Open the Test Explorer in VS Code (View → Testing). The workspace is configured to use `pytest` and will discover tests under the `tests/` directory.

1. Run tests using the Test Explorer or run the `pytest: run all` task (Terminal → Run Task...). You can also run `pytest --cov=src --cov-report=term-missing --cov-fail-under=70` (or `make coverage`) in the integrated terminal; the repository enforces a 70% minimum line coverage threshold in CI. In addition, `src/utils/byline_cleaner.py` carries a dedicated 75% module floor enforced via a pytest session hook to protect the new regression suite.

1. To debug a single test, use the Run/Debug gutter controls in the test file or create a debug configuration and point `program` to your `pytest` binary.

## Phase 2 Migration (Future)

- **Cloud SQL**: Managed Postgres with connection pooling

- **GCS Storage**: Raw HTML and artifacts in cloud storage

- **Kubernetes**: Dagster orchestration on GKE

- **Monitoring**: Prometheus/Grafana observability stack

- **CI/CD**: GitHub Actions deployment pipeline

## Fork & Roadmap

This fork is focused on hardening the CSV-to-Database pipeline, improving modularity, and preparing the project for a phased migration to production infrastructure (Postgres, GCS, Kubernetes).

Short-term goals (this fork):

- ✅ **Geographic Enhancement**: Optimized OSM gazetteer integration with 67% API call reduction and comprehensive 11-category coverage

- ✅ **Content Processing Enhancement**: Advanced byline cleaning with dynamic publication filtering, gazetteer integration, comma detection, first name protection, and comprehensive telemetry system

- Stabilize and document the CLI-driven pipeline in `src/cli/main.py` and the example workflow in `example_workflow.py`.

- Improve test coverage for `src/crawler`, `src/models`, and `src/utils` and add CI checks.

- Make the codebase environment-configurable (use `python-dotenv` and a `config.py`) and add clear local dev instructions.

- ✅ **Telemetry System**: Lightweight telemetry using `src/utils/telemetry.py` with detailed transformation tracking, confidence scoring, and quality metrics

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

1. Run the example workflow (ensure `sources/publinks.csv` exists or use the included `sources/mizzou_sites.json` for a simple crawl):

```bash
# Run the full example workflow (uses the modular `src.cli` commands)
python example_workflow.py

# Or run a single script to crawl sample sites.json into SQLite
python scripts/crawl.py --sources sources/mizzou_sites.json --output-db data/mizzou.db --job-id local-001
```

1. Run tests (after adding tests):

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
