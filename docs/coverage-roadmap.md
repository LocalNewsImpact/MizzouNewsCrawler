# Test Coverage Roadmap (Baseline 2025-09-30)

## 1. Baseline metrics

Command: `pytest --cov=src --cov-report=term --cov-report=xml --cov-fail-under=70`

- Total line coverage: **69.97%** (477 passed, 2 skipped). The gate remains at `--cov-fail-under=70`, so the most recent full-suite run tripped the threshold by **0.03 percentage points**; follow-up work below targets low-coverage modules to clear the bar.
- Coverage strengths: CLI surface area, telemetry store, and most utility packages continue to exceed 85% line coverage thanks to the existing unit suites.
- Immediate gaps remain in discovery edge cases (homepage/storysniffer fallbacks), scheduling heuristics, and portions of the crawler orchestration glue code.

> **Known skips:** `tests/test_versioning_concurrent_stress.py` and `tests/test_versioning_postgres.py` remain skip-marked pending Postgres fixture availability. No failing tests in the latest run.

> **Status legend:** ✅ Completed · ⏳ In progress · 🔜 Planned

| Module | Coverage | Notes |
| --- | --- | --- |
| `src/crawler/discovery.py` | 61% | Happy-path, mixed, duplicate-only, and RSS outage E2E tests now land; homepage/storysniffer fallbacks still sparse. |
| `src/crawler/__init__.py` | 71% | Shared crawler helpers inching toward the 75% gate; driver lifecycle paths remain uncovered. |
| `src/crawler/scheduling.py` | 74% | Frequency matrix, metadata fallbacks, host-limit pruning, and existing-article thresholds now exercised by unit + due-only E2E suites; telemetry failure-path drills remain. |
| `src/services/url_verification.py` | 71% | Timeout/backoff and GET fallback flows covered; long-lived load-shedding remains in backlog. |
| `src/services/url_verification_worker.py` | 94% | Async worker load-shedding + recovery scenarios covered via service-level tests. |
| `src/models/database.py` | 66% | Upsert/lock regression suite landed; schema drift helpers remain untested. |
| `src/reporting/county_report.py` | 97% | County report coverage now guards CSV export + wire attribution joins. |
| `src/cli/commands/gazetteer.py` | 68% | New geocode cache throttling tests cover wait/backoff; request failure/backfill flow still pending. |
| `src/cli/commands/content_cleaning.py` | 79% | CLI flag permutations largely covered; streaming-mode regressions outstanding. |
| `src/cli/commands/extraction.py` | 85% | Failure fallbacks + batch controls validated via CLI and E2E harnesses. |
| `src/cli/commands/extraction_backup.py` | 93% | Backup command now tied into shared fixtures. |
| `src/cli/commands/crawl.py` | 95% | Legacy alias now backed by targeted CLI tests; forwarding defaults and validation thoroughly covered. |
| `src/cli/commands/http_status.py` | 98% | CLI fixtures exercise source/host filtering, lookup resolution, JSON output, and error logging. |
| `src/utils/content_cleaner_balanced.py` | 59% | Rule-set still has large gaps around outlier HTML normalization; follow-up fixtures required. |
| `src/utils/content_cleaner_twophase.py` | 88% | Recent fixture refactor lifted baseline. |
| `src/utils/url_utils.py` | 86% | Dedupe normalization tests preserve high coverage. |
| `src/pipeline/text_cleaning.py` | 89% | Remains the gold standard for pipeline module coverage. |
| `src/telemetry/store.py` | 98% | Async flush, schema caching, and singleton guard remain well covered. |

### Baseline actions

- ✅ 2025-09-28: Upload `coverage.xml` to CI artifact store via GitHub Actions `coverage-<python>` artifact.
- ✅ 2025-09-28: Emit `coverage-summary.md` per run for module-level review in pull requests.
- ✅ 2025-09-30: Full-suite coverage run (477 passed, 2 skipped, 69.97% total) archived to `coverage.xml`; next delta focuses on `src/cli/commands/gazetteer.py` and `src/models/database.py` hot spots to clear the 70% gate in CI.

## 2. Golden-path audit (must hit 100% via smoke/E2E)

Status key: ✅ completed · ⏳ in progress · 🔜 planned

### Discovery → Candidate storage

- ✅ Completed
  - Unit coverage via `tests/crawler/test_discovery_helpers.py`; CLI smoke ensures command wiring.
  - 2025-09-29: Extended discovery smoke test to confirm persisted candidate records retain `status="discovered"`.
  - 2025-09-30: Added telemetry-focused unit tests covering storysniffer success/failure handling and newspaper4k NO_FEED fallbacks.
  - 2025-09-30: Added mixed-outcome regression ensuring telemetry persistence in `tests/e2e/test_discovery_pipeline.py::test_run_discovery_records_mixed_outcome_in_telemetry`.
  - 2025-10-03: Added `tests/e2e/test_discovery_pipeline.py::test_multi_source_prioritization_telemetry` to exercise multi-source discovery (RSS + homepage + storysniffer) and assert aggregated telemetry covers site failure logging plus mixed-method prioritization heuristics.
  - 2025-09-29: Added failure-path golden tests `tests/e2e/test_discovery_pipeline.py::test_run_discovery_duplicate_only_records_outcome` and `::test_run_discovery_rss_timeout_uses_fallback_and_records_failure` covering duplicate detection, RSS outage retries, telemetry, and metadata persistence.
- ⏳ In progress
  - _None — continuing to monitor regression dashboards for newly introduced discovery sources._

### Verification batching

- ✅ Completed
  - `tests/services/test_url_verification.py` exercises batching & counters.
  - 2025-09-28: Added HTTP failure coverage (timeouts and HTTP 5xx) with retry assertions.
  - 2025-09-29: Added HTTP GET fallback regression via `tests/services/test_url_verification.py::test_verify_url_fallbacks_to_get_on_403`, ensuring sites that block HEAD requests remain verifiable.
- 🔜 Planned
  - Expand load-shedding coverage for long-lived verification queues (blocked on async worker refactor).

### Extraction → Gazetteer enrichment → Analysis

- ✅ Completed
  - Partial coverage via extraction command tests and county pipeline smoke runs.
  - 2025-09-30: Added `tests/e2e/test_extraction_analysis_pipeline.py` to seed SQLite, stub extraction/cleaning/entity services, run `handle_extraction_command`, apply ML labels, and assert county report output with telemetry + gazetteer matches.
  - 2025-09-30: Added cached HTML offline regressions in `tests/test_extraction_methods.py` to assert we honor stored snapshots without falling back to network fetches and record method attribution correctly.
  - 2025-10-02: Added extractor failure/gazetteer-miss regression coverage and aligned the ORM `Article.wire` column with reporting SQL usage via reusable E2E harness helpers.

### County orchestration task

- ✅ Completed
  - CLI tests cover argument parsing; pipeline smoke run verifies process startup.
  - 2025-10-01: Added `tests/e2e/test_county_pipeline_golden_path.py` to drive discovery → verification → extraction → analysis with deterministic stubs and assert telemetry, reports, and queue transitions.
  - 2025-10-03: Scoped failure-path scenarios for multi-county orchestration loops and verification retry exhaustion, capturing requirements in `docs/coverage-roadmap.md` and aligning fixtures with queue telemetry expectations.
  - 2025-09-29: Added `tests/e2e/test_county_pipeline_golden_path.py::test_county_pipeline_verification_retry_exhaustion` to capture multi-county queue draining, forced verification retry exhaustion, and telemetry persistence.
- ⏳ In progress
  - _None — monitoring future county ingest regressions._
- 🔜 Planned
  - Extend county pipeline harness to stress-test load shedding during simultaneous severe weather alerts.

### Telemetry API/reporting

- ✅ Completed
  - API unit tests exist with mocked DB to validate endpoints.
  - 2025-10-03: Finalized telemetry E2E scenario design, enumerating discovery/extraction dashboard assertions and wiring fixtures into the shared harness.
  - 2025-10-04: Added `tests/e2e/test_telemetry_dashboard_golden_path.py` verifying discovery/extraction updates persist to dashboards and guarding against regression via snapshot comparisons.
  - 2025-10-05: Added `tests/test_telemetry_store.py` covering async flush/shutdown, schema DDL caching, connection context cleanup, and `get_store` singleton access.
- ⏳ In progress
  - _None — continuing to monitor dashboard regressions._
- 🔜 Planned
  - Extend telemetry coverage to include failure-path dashboards (e.g., verification outage alerts) once new extraction harness fixtures stabilize.

_Outcome goal:_ introduce pytest E2E suites (`tests/e2e/test_pipeline_xxx.py`) with seeded SQLite + stubbed external services to cover each primary success narrative.

## 3. External integrations & failure modes

| Dependency | Interaction | Current tests | Gaps |
| --- | --- | --- | --- |
| HTTP RSS feeds (`requests`, `feedparser`) | Fetch & parse feeds; handle 3xx/4xx/5xx, timeouts. | Unit tests mostly mock happy path. | Need contract tests for status codes, slow responses, malformed XML, retries/skip logic. |
| `newspaper4k` subprocess | CPU-heavy article discovery via multiprocessing. | Limited unit coverage (stubbed). | Add tests for timeouts, build-disabled branches, temporary file cleanup. |
| StorySniffer | ML prediction for homepage scraping. | Minimal coverage through unit mocks. | Add integration test with sample HTML + failure prediction to assert filtering. |
| Gazetteer service | HTTP API for geographic enrichment. | `tests/test_gazetteer_integration.py` uses local fixtures; `tests/test_geocode_cache.py` covers throttling waits/backoff. | Extend to 5xx handling and schema drift scenarios. |
| Verification service | External HTTP call for URL health. | Unit tests now cover batching, timeout/backoff, 403 fallback, and simulated 429/5xx responses. | Extend coverage to async worker load-shedding once the refactor lands. |
| SQLite/Postgres access (`sqlalchemy`) | Upserts, retries, lock handling. | Some unit coverage in `tests/models/test_database_manager.py`. | Add tests simulating lock contention & transaction rollbacks. |
| NLP/Extraction (`spacy`, custom models) | Content extraction + labeling. | Real-world extraction tests exist but rely on live network for some URLs. | Introduce cached HTML fixtures + offline model invocation to ensure determinism. |
| Telemetry API (FastAPI) | REST endpoints for metrics. | API tests exist. | Add failures for DB downtime and schema migration mismatches. |

## 4. Roadmap to target coverage (pre-Kubernetes)

### Phase 1 – Institutionalize metrics (Week 1)

- ✅ 2025-10-02: Added CI job coverage step to upload `coverage.xml`, HTML report, and Markdown summary per PR.
- ✅ 2025-09-29: Raised `pytest.ini` default and CI gate to `--cov-fail-under=70` now that the dashboard fixtures are stable.

### Phase 2 – Core module uplift (Weeks 2–4)

- ✅ **Mandatory** `src/crawler/discovery.py`: factor helper functions, add parameterized tests for RSS/homepage/newspaper/storysniffer branches, include duplicate-handling regressions (no deferral allowed).
  - ✅ 2025-10-02: Extracted RSS/homepage helper utilities with normalized URL dedupe plumbing and expanded `tests/crawler/test_discovery_helpers.py` to cover homepage sniff, RSS skip logic, and duplicate regressions across newspaper4k/storysniffer branches.
- ✅ **Mandatory** `src/services/url_verification.py`: cover timeout/backoff, failure states, and metrics increments.
  - ✅ 2025-10-02: Hardened `tests/services/test_url_verification.py` with HTTP 5xx retry, timeout, and telemetry/metrics assertions; verified service loop honors limits and failure bookkeeping.
- ✅ **Mandatory** `src/models/database.py`: unit-test upsert flows with simulated lock contention and ensure ORM compatibility with reporting outputs.
  - ✅ 2025-09-28: Added targeted upsert coverage in `tests/models/test_database_manager.py`, simulating lock contention, verifying retry counters, and asserting metadata/wire persistence for reporting.
- ✅ **Mandatory** reporting exports: guard CSV/XLSX generation and data joins for county output pipelines.
  - ✅ 2025-09-28: Landed `tests/reporting/test_county_report.py` and `tests/reporting/test_csv_writer.py` with shared fixtures to validate DataFrame transforms, wire attribution, and filesystem cleanup.
  - ✅ 2025-09-28: Added `tests/cli/commands/test_extraction.py` covering parser defaults, success/failure control flow, and driver cleanup for `handle_extraction_command`.
  - ✅ 2025-09-29: Added `tests/e2e/test_discovery_pipeline.py` validating discovery → candidate storage happy path with stub telemetry.
  - ✅ 2025-09-29: Expanded `tests/cli/commands/test_content_cleaning.py` and `test_extraction_backup.py` with CLI context fixtures and database stubs, reinforcing the null-on-missing policy for extraction outputs; `content_cleaning`, `extraction`, and `extraction_backup` now each exceed 75% coverage (current: 79% / 85% / 93%).
  - ✅ 2025-09-29: Removed URL-slug headline fallback from the crawler and added regression coverage to ensure fields remain null or empty arrays when extraction methods cannot populate them.
  - ✅ 2025-10-05: Added `tests/cli/commands/test_crawl.py` to lock in legacy alias validation, forwarding defaults, and ALL filter wiring; `crawl` command now sits at 95% coverage.
  - ✅ 2025-09-29: Added `tests/cli/commands/test_http_status.py` covering parser wiring, host/source filters, lookup resolution, JSON output, and failure logging; `http_status` command now exceeds 90% coverage.

### Phase 3 – Golden-path smoke tests (Weeks 3–5)

#### ✅ Completed

- Established pytest `@pytest.mark.e2e` suite using seeded SQLite DB + stub services.
- 2025-09-30: Seeded deterministic extraction → analysis golden-path via `tests/e2e/test_extraction_analysis_pipeline.py` covering content extraction, cleaning, gazetteer enrichment, classification, telemetry, and county report generation.
- 2025-09-30: Registered the `pytest` `e2e` marker to keep smoke suites discoverable without warnings.
- 2025-10-01: Added `tests/e2e/test_county_pipeline_golden_path.py` to validate the county orchestration CLI end-to-end with telemetry and report assertions.
- 2025-10-02: Expanded the extraction analysis suite with failure-path coverage, reusable harness helpers, and ORM alignment for `Article.wire` to keep county reports and telemetry in sync.
- 2025-09-29: Added failure-path orchestration regression coverage ensuring discovery/verification/extraction/analysis CLI failures raise `PipelineError` via `tests/test_county_pipeline.py`.
- 2025-10-06: Added scheduling cadence regression coverage via `tests/test_scheduling.py::test_should_schedule_discovery_frequency_matrix` and due-only host-limit/existing-article scenarios in `tests/e2e/test_discovery_pipeline.py`, capturing telemetry + metadata updates for scheduling decisions.

#### ⏳ In progress

- ✅ 2025-09-29: Achieved 100% line coverage across discovery → verification → extraction → analysis orchestration surfaces via expanded `tests/test_county_pipeline.py` (CLI flag wiring, `_run_cli_step` dry-run/error handling, module entrypoint).
- Finalize telemetry dashboard failure-path assertions once dashboard fixtures settle.

### Phase 4 – Integration & resilience harness (Weeks 5–7)

#### 🔜 Planned

- Create reusable HTTP stub server fixtures to emulate external services (RSS, Gazetteer, Verification).
- Add tests for timeout, retry exhaustion, and schema drift; document contracts.
- Expand to `spacy`/ML extraction by caching inference outputs.

### Phase 5 – Enforcement & maintenance (Weeks 7–8)

- Raise `--cov-fail-under` incrementally (65% → 70% → 75%).
- ✅ 2025-10-06: Added pytest session hook enforcing a 75% per-module floor for `src/utils/byline_cleaner.py` to guard the regression suite during refactors.
- Automate weekly coverage trend report; alert on regressions.
- Evaluate mutation testing or diff coverage checks for critical modules.

## 5. Success criteria

- **Unit tests:** Core crawler, service, and CLI modules sustain 75–85% line coverage with stable suites.
- **Golden paths:** Every primary pipeline flow validated end-to-end in <5 minutes of runtime with deterministic fixtures.
- **Integrations:** Each external dependency has at least one integration test exercising success and critical failure modes.
- **Governance:** Coverage gates enforced in CI with dashboards shared ahead of Kubernetes migration.
