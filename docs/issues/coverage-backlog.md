# Coverage Backlog: Priority Modules

**Summary:** Overall coverage is sitting at ~82.2%, comfortably above the 80% global floor. The modules below remain the biggest contributors to missed lines. Each section captures the gaps that still need tests and suggested approaches.

## ✅ Goals

- [x] Lift `versioning.py` to ≥80%
- [x] Lift `pipeline/entity_extraction.py` to ≥80%
- [x] Lift `services/llm/article_pipeline.py` to ≥80%
- [x] Lift `services/llm/orchestrator.py` to ≥80%
- [x] Lift `services/url_verification.py` to ≥80%
- [x] Lift `utils/process_tracker.py` to ≥80%

---

## `src/models/versioning.py`

- [x] Unit-test dataset lifecycle helpers (`create_dataset_version`, `claim_dataset_version`, `finalize_dataset_version`) including error cases.
- [x] Cover snapshot helpers:
  - [x] `_compute_file_checksum` with chunking.
  - [x] `_fsync_path` best-effort branches.
  - [x] `_compute_advisory_lock_id` deterministic output.
- [x] Exercise `export_dataset_version` success + error paths.
- [x] Exercise `export_snapshot_for_version` in both PyArrow and pandas fallbacks.
- [x] Simulate Postgres advisory-lock success/failure to cover claim rollback and unlock cleanup paths.

## `src/pipeline/entity_extraction.py`

- [x] Cover `_normalize_text` and Rot47 interplay.
- [x] Stub spaCy to exercise gazetteer overrides, EntityRuler skip, and duplicate suppression.
- [x] Hit `_map_to_category` branches (school/health/business etc.).
- [x] Cover `_score_match` fast and fuzzy matches plus no-match case.
- [x] Test `get_gazetteer_rows` filter combinations.
- [x] Test `attach_gazetteer_matches` direct, fuzzy, and empty scenarios.
  - Added comprehensive unit coverage in `tests/pipeline/test_entity_extraction.py`; targeted run passes functionally but, as with versioning, project-wide coverage enforcement still requires a full-suite execution to see aggregate increase.

## `src/services/llm/article_pipeline.py`

- [x] Cover `_iter_articles` filters and limits.
- [x] Cover `_render_prompt` defaults, publish-date formatting, and truncation.
- [x] Exercise `run` for dry-run, success, and failure persistence, verifying single commit.
- [x] Cover `_persist_result`/`_persist_failure` metadata wiring.
- [x] Test `load_prompt_template` success and missing file error.

  - Added focused coverage via `tests/services/llm/test_article_pipeline.py`, including dry-run vs. live persistence and failure serialization checks.
  - Patched pipeline serialization (`ProviderFailure` dict conversion, article ID coercion) to make tests green; module now sits at 98% coverage.

## `src/services/llm/orchestrator.py`

- [x] Cover `from_settings`, `list_providers`, and successful `generate` with vector store writes.
- [x] Capture error classifications for unavailable configuration, rate limit, provider error, etc.
- [x] Ensure failures list order is preserved and metadata passes through.
- [x] Cover `_store_vector_if_enabled` best-effort exception handling.

  - Added dedicated coverage in `tests/services/llm/test_orchestrator.py`, including task config propagation and vector store best-effort error handling.
  - Test run caught registry instantiation quirks; introduced `FakeProvider` helpers mirroring production signatures. Module now reports 100% line coverage.

## `src/services/llm/providers.py`

- [x] Cover `_import_module` fallbacks and missing-client branches across providers.
- [x] Exercise `_client_tuple` wiring for OpenAI, Anthropic, and Gemini when optional dependencies are absent or partially defined.
- [x] Verify `generate` translates configuration gaps, rate limits, and client errors into unified exceptions for each provider.
- [x] Capture `_decorate_metadata` defaults and response coalescing edge cases (list outputs, scalar outputs, nested content).

  - Expanded `tests/services/llm/test_providers.py` with 47 focused cases covering registry, providers, and coalescing helpers; targeted pytest run now passes and the module sits above 97% line coverage.

## `src/services/url_verification.py`

- [x] Exercise `_prepare_http_session` to populate default headers when missing and when existing headers are invalid.
- [x] Cover `_check_http_health` fallback-first failure modes and status propagation.
- [x] Verify `_attempt_get_fallback` timeout/request-exception handling and error messaging.
- [x] Ensure `verify_url` forwards fallback errors without StorySniffer calls on failure.
- [x] Cover `get_status_summary`, `setup_logging`, and CLI `main` status/runtime paths.
- [x] Confirm service loop stoppage toggles the `running` flag for graceful shutdown.


## `src/utils/process_tracker.py`

- [x] Cover `register_process`, `update_progress`, and `complete_process` against a temporary SQLite database.
- [x] Exercise `get_active_processes`, `get_processes_by_type`, and `cleanup_stale_processes` including cutoff handling.
- [x] Assert the singleton `get_tracker` wiring and formatting helpers via dedicated unit tests.

  - Added DB-backed coverage in `tests/utils/test_process_tracker_db.py`, ensuring CRUD flows, singleton access, and stale cleanup behaviors are verified. Module now reports 98% line coverage.


### Sprint Proposal

1. Land unit tests for `versioning.py` (largest single chunk of missed lines).
1. Follow with `entity_extraction.py` and `url_verification.py` (high traffic paths).
1. Finish with LLM modules and `process_tracker.py` to close the gap.

### Nice-to-haves

- [x] Incorporate fixtures/helpers in `tests/helpers/` for temporary SQLite + filesystem scaffolding. Added `sqlite_builder`, `create_sqlite_db`, and `filesystem_builder` utilities alongside unit coverage in `tests/helpers/test_support_helpers.py`.
- [x] Capture flaky external dependencies (spaCy, StorySniffer) with lightweight fakes. Introduced `FakeSpacyNlp` and `FakeStorySniffer` in `tests/helpers/externals.py` with reusable behaviours for deterministic testing.
