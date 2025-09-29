# Test Coverage Roadmap (Baseline 2025-09-28)

## 1. Baseline metrics

Command: `pytest --cov=src --cov-report=term --cov-report=xml --cov-fail-under=0`

- Total line coverage: **62%** (352 passed, 2 skipped)
- Coverage strengths: CLI command modules (`src/cli/cli_modular.py`, `src/cli/main.py`), reporting helpers, and several utility packages already exceed 90%.
- Immediate gaps concentrate in discovery/orchestration, service integrations, and large text-cleaning utilities.

> **Status legend:** ✅ Completed · ⏳ In progress · 🔜 Planned

| Module | Coverage | Notes |
| --- | --- | --- |
| `src/crawler/discovery.py` | 56% | Core discovery engine; heavy branching across RSS, homepage, newspaper4k, storysniffer, and recent URL normalization. |
| `src/crawler/__init__.py` | 70% | Shared crawler helpers; still below 75% target. |
| `src/crawler/scheduling.py` | 51% | Retry window logic and host throttling under-tested. |
| `src/services/url_verification.py` | 44% | Critical batching/backoff logic missing edge-case coverage. |
| `src/models/database.py` | 69% | Fresh unit isolation now covers candidate/article upserts plus lock contention retry helpers. |
| `src/reporting/county_reporter.py` | 72% | New regression tests exercise CSV/XLSX export flows and guard wire attribution serialization. |
| `src/cli/commands/content_cleaning.py` | 60% | Multiple execution paths with complex flag handling. |
| `src/cli/commands/extraction.py` | 60% | Needs coverage for failure fallbacks and batch controls. |
| `src/cli/commands/extraction_backup.py` | 40% | Sparse tests; high priority before Kubernetes migration. |
| `src/utils/content_cleaner_balanced.py` | 45% | Large rule-set; candidates for property-based/unit sampling. |
| `src/utils/content_cleaner_twophase.py` | 12% | Essentially untested; consider pruning or covering. |
| `src/utils/url_utils.py` | 86% | Recently added dedupe normalization tests lifted coverage. |
| `src/pipeline/text_cleaning.py` | 89% | Strong coverage—serves as model for other pipeline modules. |

### Baseline actions

- ✅ 2025-09-28: Upload `coverage.xml` to CI artifact store via GitHub Actions `coverage-<python>` artifact.
- ✅ 2025-09-28: Emit `coverage-summary.md` per run for module-level review in pull requests.

## 2. Golden-path audit (must hit 100% via smoke/E2E)

Status key: ✅ completed · ⏳ in progress · 🔜 planned

### Discovery → Candidate storage

- ✅ Completed
  - Unit coverage via `tests/crawler/test_discovery_helpers.py`; CLI smoke ensures command wiring.
  - 2025-09-29: Extended discovery smoke test to confirm persisted candidate records retain `status="discovered"`.
  - 2025-09-30: Added telemetry-focused unit tests covering storysniffer success/failure handling and newspaper4k NO_FEED fallbacks.
  - 2025-09-30: Added mixed-outcome regression ensuring telemetry persistence in `tests/e2e/test_discovery_pipeline.py::test_run_discovery_records_mixed_outcome_in_telemetry`.
  - 2025-10-03: Added `tests/e2e/test_discovery_pipeline.py::test_multi_source_prioritization_telemetry` to exercise multi-source discovery (RSS + homepage + storysniffer) and assert aggregated telemetry covers site failure logging plus mixed-method prioritization heuristics.
- ⏳ In progress
  - _None — continuing to monitor regression dashboards for newly introduced discovery sources._

### Verification batching

- ✅ Completed
  - `tests/services/test_url_verification.py` exercises batching & counters.
  - 2025-09-28: Added HTTP failure coverage (timeouts and HTTP 5xx) with retry assertions.
  - 2025-10-03: Added multi-batch dequeue regression ensuring retry exhaustion still persists telemetry via `tests/services/test_url_verification.py::test_multi_batch_retry_exhaustion_persists_telemetry` and companion smoke coverage in `tests/e2e/test_discovery_pipeline.py`.
- 🔜 Planned
  - Expand load-shedding coverage for long-lived verification queues (blocked on async worker refactor).

### Extraction → Gazetteer enrichment → Analysis

- ✅ Completed
  - Partial coverage via extraction command tests and county pipeline smoke runs.
  - 2025-09-30: Added `tests/e2e/test_extraction_analysis_pipeline.py` to seed SQLite, stub extraction/cleaning/entity services, run `handle_extraction_command`, apply ML labels, and assert county report output with telemetry + gazetteer matches.
  - 2025-10-02: Added extractor failure/gazetteer-miss regression coverage and aligned the ORM `Article.wire` column with reporting SQL usage via reusable E2E harness helpers.

### County orchestration task

- ✅ Completed
  - CLI tests cover argument parsing; pipeline smoke run verifies process startup.
  - 2025-10-01: Added `tests/e2e/test_county_pipeline_golden_path.py` to drive discovery → verification → extraction → analysis with deterministic stubs and assert telemetry, reports, and queue transitions.
  - 2025-10-03: Scoped failure-path scenarios for multi-county orchestration loops and verification retry exhaustion, capturing requirements in `docs/coverage-roadmap.md` and aligning fixtures with queue telemetry expectations.
  - 2025-10-04: Implemented `tests/e2e/test_county_pipeline_failure_paths.py` exercising multi-county dequeue loops, forced verification retry exhaustion, and asserting telemetry persistence plus recovery routing.
- ⏳ In progress
  - _None — monitoring future county ingest regressions._
- 🔜 Planned
  - Extend county pipeline harness to stress-test load shedding during simultaneous severe weather alerts.

### Telemetry API/reporting

- ✅ Completed
  - API unit tests exist with mocked DB to validate endpoints.
  - 2025-10-03: Finalized telemetry E2E scenario design, enumerating discovery/extraction dashboard assertions and wiring fixtures into the shared harness.
  - 2025-10-04: Added `tests/e2e/test_telemetry_dashboard_golden_path.py` verifying discovery/extraction updates persist to dashboards and guarding against regression via snapshot comparisons.
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
| Gazetteer service | HTTP API for geographic enrichment. | `tests/test_gazetteer_integration.py` uses local fixtures. | Expand to cover rate limiting, 5xx, and schema drift. |
| Verification service | External HTTP call for URL health. | Unit tests stub successes; no network fault cases. | Add integration harness to simulate 429/500, exponential backoff, and permanent failure classification. |
| SQLite/Postgres access (`sqlalchemy`) | Upserts, retries, lock handling. | Some unit coverage in `tests/models/test_database_manager.py`. | Add tests simulating lock contention & transaction rollbacks. |
| NLP/Extraction (`spacy`, custom models) | Content extraction + labeling. | Real-world extraction tests exist but rely on live network for some URLs. | Introduce cached HTML fixtures + offline model invocation to ensure determinism. |
| Telemetry API (FastAPI) | REST endpoints for metrics. | API tests exist. | Add failures for DB downtime and schema migration mismatches. |

## 4. Roadmap to target coverage (pre-Kubernetes)

### Phase 1 – Institutionalize metrics (Week 1)

- ✅ 2025-10-02: Added CI job coverage step to upload `coverage.xml`, HTML report, and Markdown summary per PR.
- ✅ 2025-10-02: Raised `pytest.ini` default to `--cov-fail-under=60` (also enforced in CI now that the dashboard is live).

### Phase 2 – Core module uplift (Weeks 2–4)

- ✅ **Mandatory** `src/crawler/discovery.py`: factor helper functions, add parameterized tests for RSS/homepage/newspaper/storysniffer branches, include duplicate-handling regressions (no deferral allowed).
  - ✅ 2025-10-02: Extracted RSS/homepage helper utilities with normalized URL dedupe plumbing and expanded `tests/crawler/test_discovery_helpers.py` to cover homepage sniff, RSS skip logic, and duplicate regressions across newspaper4k/storysniffer branches.
- ✅ **Mandatory** `src/services/url_verification.py`: cover timeout/backoff, failure states, and metrics increments.
  - ✅ 2025-10-02: Hardened `tests/services/test_url_verification.py` with HTTP 5xx retry, timeout, and telemetry/metrics assertions; verified service loop honors limits and failure bookkeeping.
- ✅ **Mandatory** `src/models/database.py`: unit-test upsert flows with simulated lock contention and ensure ORM compatibility with reporting outputs.
  - ✅ 2025-09-28: Added targeted upsert coverage in `tests/models/test_database_manager.py`, simulating lock contention, verifying retry counters, and asserting metadata/wire persistence for reporting.
- ✅ **Mandatory** reporting exports: guard CSV/XLSX generation and data joins for county output pipelines.
  - ✅ 2025-09-28: Landed `tests/reporting/test_county_report.py` and `tests/reporting/test_csv_writer.py` with shared fixtures to validate DataFrame transforms, wire attribution, and filesystem cleanup.
- **Mandatory** CLI command modules (content cleaning/extraction/extraction_backup): design fixture CLI contexts; reach ≥75% coverage (must land before Phase 3 closes).
  - ✅ 2025-09-28: Added `tests/cli/commands/test_extraction.py` covering parser defaults, success/failure control flow, and driver cleanup for `handle_extraction_command`.
  - ✅ 2025-09-29: Added `tests/e2e/test_discovery_pipeline.py` validating discovery → candidate storage happy path with stub telemetry.

### Phase 3 – Golden-path smoke tests (Weeks 3–5)

#### ✅ Completed

- Established pytest `@pytest.mark.e2e` suite using seeded SQLite DB + stub services.
- 2025-09-30: Seeded deterministic extraction → analysis golden-path via `tests/e2e/test_extraction_analysis_pipeline.py` covering content extraction, cleaning, gazetteer enrichment, classification, telemetry, and county report generation.
- 2025-09-30: Registered the `pytest` `e2e` marker to keep smoke suites discoverable without warnings.
- 2025-10-01: Added `tests/e2e/test_county_pipeline_golden_path.py` to validate the county orchestration CLI end-to-end with telemetry and report assertions.
- 2025-10-02: Expanded the extraction analysis suite with failure-path coverage, reusable harness helpers, and ORM alignment for `Article.wire` to keep county reports and telemetry in sync.

#### ⏳ In progress

- Ensure discovery → verification → extraction → analysis success scenario hits 100% line coverage across orchestration surfaces.
- 2025-10-01: Designing county failure-path smoke tests (multi-county queue draining + verification retry exhaustion) and telemetry dashboard golden-path.

#### 🔜 Planned

- Add failure-path golden tests (duplicate detection, RSS outage) with assertions on telemetry + retries.

### Phase 4 – Integration & resilience harness (Weeks 5–7)

#### 🔜 Planned

- Create reusable HTTP stub server fixtures to emulate external services (RSS, Gazetteer, Verification).
- Add tests for timeout, retry exhaustion, and schema drift; document contracts.
- Expand to `spacy`/ML extraction by caching inference outputs.

### Phase 5 – Enforcement & maintenance (Weeks 7–8)

- Raise `--cov-fail-under` incrementally (65% → 70% → 75%).
- Automate weekly coverage trend report; alert on regressions.
- Evaluate mutation testing or diff coverage checks for critical modules.

## 5. Success criteria

- **Unit tests:** Core crawler, service, and CLI modules sustain 75–85% line coverage with stable suites.
- **Golden paths:** Every primary pipeline flow validated end-to-end in <5 minutes of runtime with deterministic fixtures.
- **Integrations:** Each external dependency has at least one integration test exercising success and critical failure modes.
- **Governance:** Coverage gates enforced in CI with dashboards shared ahead of Kubernetes migration.
