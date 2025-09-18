# Data Versioning Strategy

This document describes a lightweight dataset versioning design for the MizzouNewsCrawler project.

Goals

- Track multiple versions of the same dataset (e.g., `candidate_links`) over time without duplicating the entire dataset.
- Allow immutable snapshots for reproducibility while enabling incremental updates (deltas).
- Provide a simple API to create new versions, list versions, and access a specific version's data.
- Integrate with job tracking and telemetry so data provenance is recorded with each job.

Core concepts

- Dataset: Logical collection, e.g. `candidate_links`, `articles`, `ml_results`.
- DatasetVersion: A version record that points to a set of changes (delta) and optional snapshot.
- Snapshot: Optional full snapshot location (Parquet file path) for immutable archival.
- Delta: A table of changes (inserts/updates/deletes) applied since previous version.

Schema (minimal)

- `dataset_versions` table (new):
  - `id` (PK) - UUID
  - `dataset_name` - e.g., `candidate_links`
  - `version_tag` - human-friendly tag (e.g., `v2025-09-18-1`)
  - `created_at` - timestamp
  - `created_by_job` - foreign key to `jobs.id` (optional)
  - `snapshot_path` - optional path to Parquet snapshot
  - `description` - optional text
  - `parent_version` - id of previous version (nullable)

- `dataset_deltas` table (new):
  - `id` (PK)
  - `dataset_version_id` (FK -> dataset_versions.id)
  - `operation` - `insert`|`update`|`delete`
  - `record_id` - id of affected record (candidate_links.id)
  - `payload` - JSON of the new values (for insert/update)
  - `changed_at` - timestamp
  - `changed_by_job` - job id that caused the change

Operational model

- Creating a new version:
  1. Start job with `OperationTracker` (job created in `jobs` table).
  2. When loading sources or applying changes, write deltas to `dataset_deltas` with `dataset_version_id` set to new version record (or temp staging id).
  3. Optionally, after a stable run, export a snapshot to Parquet and record `snapshot_path` on `dataset_versions`.

- Accessing a version:
  - If snapshot exists, read the Parquet snapshot.
  - Otherwise, rebuild by applying deltas to the parent snapshot (or base) in sequence.

Advantages

- Efficient storage: small deltas instead of full copies.
- Reproducibility: snapshots provide a point-in-time view; deltas allow reconstructing history.
- Auditability: every change is linked to a job id and timestamp.

Edge cases

- Long delta chains: periodically compact deltas into a snapshot (compaction job).
- Concurrent writers: ensure transactional writes or use a locking mechanism for version creation.
- Large snapshots: store in cloud storage (GCS/S3) and keep only references in the DB.

API / CLI ergonomics

- `python -m src.cli.main create-version --dataset candidate_links --tag v2025-09-18-1 --description "Initial load"`
- `python -m src.cli.main list-versions --dataset candidate_links`
- `python -m src.cli.main export-version --dataset candidate_links --version-id <id> --output artifacts/candidate_links_v1.parquet`

Integration with OAuth & Access Control

- Versions and snapshots are metadata and can be protected by OAuth scopes.
- Scope examples: `dataset.read`, `dataset.write`, `dataset.version.create`, `dataset.artifact.read`.

Next steps

- Add `src/models/versioning.py` with SQLAlchemy models for `DatasetVersion` and `DatasetDelta`.
- Add schema creation helper `create_versioning_tables(engine)` and integrate into `create_tables`.
- Add CLI commands for simple version creation and listing.
