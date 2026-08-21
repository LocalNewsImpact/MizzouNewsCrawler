# Backfield enrichment — implementation specification

Work plan for [BACKFIELD_ENRICHMENT.md](BACKFIELD_ENRICHMENT.md). That document
states what is being built and why, and is the reference for every measured
figure. This one states what to write, in what order, and what must be true
before each step is considered finished.

Section references such as §8 point at the proposal.

---

## 1. Module layout

All new code lives under `src/enrichment/`. Nothing in `src/pipeline/` changes.

```
src/enrichment/
  __init__.py
  adapter.py          # the only module that imports backfield
  profiles.py         # dataset profile resolution and validation
  gate.py             # boilerplate heuristic + content gate
  resolve.py          # point resolution (single city / publication city)
  orchestrator.py     # per-article step sequencing and status transitions
  repository.py       # all reads and writes; no backfield imports
  cost.py             # per-call cost accounting and the run ceiling
  types.py            # dataclasses crossing module boundaries

src/cli/commands/enrichment.py     # add_enrichment_parser, per cli_modular.py
alembic/versions/<rev>_enrichment_tables.py
k8s/enrichment-cronjob.yaml
tests/enrichment/                  # unit
tests/integration/test_enrichment.py
tests/fixtures/enrichment/         # recorded node responses
```

**`adapter.py` is the only file permitted to import `agate_runtime` or
`agate_nodes`.** A backfield upgrade that changes a signature must be repairable
in one file. Enforce it with a test that greps the tree.

## 2. Interfaces

Fix these before writing implementations; the phases below depend on them.

```python
# types.py
@dataclass(frozen=True)
class ArticleInput:
    id: str
    title: str
    content: str
    dataset_slug: str
    publication_city: str | None

@dataclass(frozen=True)
class StepResult:
    step: str                  # 'scope' | 'places' | 'people' | ...
    ok: bool
    payload: dict | None
    error: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal

@dataclass(frozen=True)
class EnrichmentOutcome:
    article_id: str
    status: str                # enriched | enrichment_skipped | not_article |
                               # paywall | labeled   (labeled = retry)
    skip_reason: str | None
    steps_applied: list[str]
    results: list[StepResult]
    total_cost_usd: Decimal
```

```python
# adapter.py — one function per node, all synchronous, all pure
def run_scope(article: ArticleInput, model: str) -> StepResult: ...
def run_places(article: ArticleInput, model: str) -> StepResult: ...
def run_people(article: ArticleInput, model: str) -> StepResult: ...
def run_organizations(article: ArticleInput, model: str) -> StepResult: ...
def run_preset(article: ArticleInput, preset: str, model: str) -> StepResult: ...
def run_content_gate(article: ArticleInput, model: str, prefix_chars: int = 800) -> StepResult: ...
```

The adapter composes `f"Headline: {title}\n\n{content}"`, calls the node, and
converts exceptions into `StepResult(ok=False)`. It never raises for a model
failure. It never writes to the database.

```python
# orchestrator.py
def enrich_article(article: ArticleInput, profile: Profile) -> EnrichmentOutcome: ...
```

Pure given a stubbed adapter. All step ordering, gating and status logic lives
here, which is what makes §11's unit tests possible without a database.

## 3. Configuration

```python
# profiles.py
@dataclass(frozen=True)
class Profile:
    version: int
    content_gate: bool
    scope: bool
    places: bool
    geocode: bool
    people: bool
    organizations: bool
    metadata_presets: tuple[str, ...]
```

Stored at `datasets.metadata -> 'enrichment_profile'`. Absent means the default:

```json
{ "version": 1, "content_gate": true, "scope": false, "places": false,
  "geocode": false, "people": false, "organizations": false,
  "metadata_presets": [] }
```

Gate on, everything else off (§7). A new dataset costs nothing and still refuses
to export cookie text.

Validation rules, enforced on read:

| Rule | On violation |
|---|---|
| `metadata_presets` ⊆ the six production presets | Reject the profile, fail the run |
| `information_needs` present | Reject — excluded from production (§12) |
| `geocode` true while `places` false | Reject — geocoding needs extracted places |
| `version` missing or not an integer | Reject |

Environment:

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | Secret Manager, mounted |
| `ENRICHMENT_MODEL` | Default `openrouter/deepseek/deepseek-v3.2` |
| `ENRICHMENT_CONCURRENCY` | Default 10 |
| `ENRICHMENT_MAX_ATTEMPTS` | Default 3 |
| `ENRICHMENT_SPEND_CEILING_USD` | Per run; the run halts on breach |
| `GEOCODIO_API_KEY` | Only if any profile sets `geocode` |

## 4. Phases

Each phase is one pull request. A phase is finished when its exit criteria hold,
not when the code is written.

### Phase 0 — Measurement spikes

No production code. Answers the questions §4 and §3 leave open.

| Task | Output |
|---|---|
| Prompt caching | Cost per article with the article last in the message, against the $0.0067–0.0075 baseline |
| Preset consolidation | Agreement between six separate calls and one combined call on 100 articles, per category |
| Content gate tuning | Heuristic threshold and gate accuracy on a sample drawn **without** the length bias in the existing 100 |
| Point resolution accuracy | Human verification of the 38 resolved points |

**Exit:** each measured and written into §4/§3. If consolidation degrades any
category, it is dropped and not revisited.

**Rollback:** none; nothing ships.

### Phase 1 — Schema

Alembic revision creating the four tables and two columns exactly as §9
specifies.

**Exit:**
- Migration applies and rolls back against a copy of the production schema
- `tests/integration/test_enrichment.py::test_migration_roundtrip` passes
- No writer exists yet; tables are empty in production

**Rollback:** `alembic downgrade`. Tables are unreferenced.

### Phase 2 — Export criterion widened

**This precedes any enrichment run and must not be reordered.**

The export mechanism, verified against the live project on 2026-08-20, is **not
Datastream**. It is four BigQuery **scheduled queries** (`bq ls
--transfer_config`), of which "Sync Articles from Cloud SQL" runs daily at 07:00
UTC as a **full refresh**:

```sql
WITH ranked AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY id
    ORDER BY extracted_at DESC) AS rn
  FROM EXTERNAL_QUERY("mizzou-news-crawler.us.cloudsql_connection",
    "SELECT * FROM articles WHERE status = 'labeled';"))
SELECT * EXCEPT(rn) FROM ranked WHERE rn = 1;
```

Consequences that shape this phase:

- The filter is `status = 'labeled'` **alone** — the `wire_check_status`
  condition in the code comments is not in the deployed query.
  `mizzou_analytics.articles` holds 104,521 rows, equal to the `labeled` count.
- Because it is a full refresh, an article whose status changes to `enriched`
  disappears from BigQuery at the **next 07:00 run**. The withdrawal hazard in
  §8 is a certainty under the current query, not an edge case.
- The proposal's assumption that new tables replicate automatically is wrong.
  **Each new table in Phase 1 needs its own scheduled query**, created alongside
  the migration (four `EXTERNAL_QUERY` transfers, following the existing ones).

Work:

1. Edit the transfer config's inner query to
   `SELECT * FROM articles WHERE status IN ('labeled','enriched','enrichment_skipped')`
2. Add the four scheduled queries for the new tables (they return zero rows
   until Phase 5 writes)
3. Record the transfer-config ids in this document

**Exit:**
- The widened query is live; the next scheduled run produces an identical row
  count (no article yet carries a new status)
- Four new transfers exist and succeed, each currently syncing zero rows
- The two-status form is scheduled for Phase 7, not now

**Rollback:** restore the previous inner query; correct while no article carries
a new status.

### Phase 3 — Adapter and node wrappers

`adapter.py`, `types.py`, and recorded fixtures.

**Exit:**
- Each of the six functions returns a populated `StepResult` against the live API
- Malformed and truncated responses produce `ok=False` rather than raising
- Fixtures committed under `tests/fixtures/enrichment/`, captured from real calls
- A test asserts no module outside `adapter.py` imports backfield

**Rollback:** unreferenced code.

### Phase 4 — Orchestrator, gate, resolution, profiles

The decision logic, still with no database and no CLI.

**Exit:** the §11 unit table passes in full, specifically —
- Full profile → `enriched`; empty → `enrichment_skipped` / `profile_none`
- Gate rejection → `not_article` or `paywall`
- Failure → `labeled`, attempts incremented; exhausted → `failed_max_attempts`
- `regional`, `statewide`, `national`, `international`, `other` never reach places
- Point resolution matches the four cases in §3
- Invalid profiles rejected per §3's table

**Rollback:** unreferenced code.

### Phase 5 — Repository and CLI

`repository.py` and `src/cli/commands/enrichment.py`, following the existing
`add_*_parser` convention.

```
news-crawler enrich run       --dataset SLUG [--limit N] [--dry-run] [--concurrency N]
news-crawler enrich backfill  --ids-file PATH [--dry-run]
news-crawler enrich status    [--dataset SLUG]
news-crawler enrich reprocess --dataset SLUG --profile-version N [--dry-run]
```

The binary is `news-crawler` (`prog` in `src/cli/cli_modular.py`).

`--dry-run` resolves candidates, prints the plan and the projected cost, and
makes no model call and no write.

**Exit:**
- Integration tests in §11 pass against real Postgres
- **`test_reprocessing_never_withdraws_rows` passes** — the §8 failure mode
- Ids on a backfill list that are not candidates are reported with a reason and
  counted; totals reconcile
- A run halts on the spend ceiling and leaves committed work intact

**Rollback:** CLI is additive; nothing invokes it automatically yet.

### Phase 6 — Steady state on one dataset

Image built from `Dockerfile.base` per §6, and `k8s/enrichment-cronjob.yaml`
composed from the existing patterns, verified in the repo:

- `concurrencyPolicy: Forbid`, `ttlSecondsAfterFinished` — as
  `k8s/cleanup-cronjob.yaml`
- Spot scheduling — the `cloud.google.com/gke-spot` toleration plus node
  affinity, as `k8s/lehigh-extraction-job.yaml`
- Database access — `USE_CLOUD_SQL_CONNECTOR` with `CLOUD_SQL_INSTANCE` and the
  `cloudsql-db-credentials` secret, as `k8s/crawler-cronjob.yaml`. No proxy
  sidecar.
- Resources — 512Mi request / 1Gi limit / 250m CPU (§6)

The OpenRouter key is a new Kubernetes secret in the `production` namespace; the
existing `cloudsql-db-credentials` pattern is the precedent.

Enable on one dataset with a partial profile — `content_gate` and `scope` only.

**Exit after seven days:**
- No article stuck at `labeled` beyond two scheduled runs
- Cost per article within 20% of the Phase 0 measurement
- The gate's rejection rate is stable and its rejections spot-checked
- Backlog alert fires in a deliberate failure drill

**Rollback:** suspend the CronJob. Articles remain at `labeled`, which the Phase 2
criterion still exports.

### Phase 7 — Full profile, backfill, and criterion tightening

In this order:

1. Widen the dataset profile to the full six presets plus people and
   organizations; bump `profile_version`; let reprocessing fill the gap (§8)
2. Run the supplied backfill list
3. Once every candidate carries a terminal status, tighten the scheduled
   query's inner filter to `status IN ('enriched', 'enrichment_skipped')`

**Exit:**
- `select count(*) from articles where status='labeled' and wire_check_status='complete'` is zero for the dataset, or every remainder is explained
- BigQuery row count is unchanged across the tightening
- Backfill totals reconcile against the supplied list

**Rollback:** revert to the superset criterion. Enrichment data is additive and
need not be removed.

## 5. Delivery mechanics, verified against the repo

| Concern | Mechanism |
|---|---|
| Migrations in production | Alembic via the `migrator` image, built by `cloudbuild.yaml` and run as `k8s/jobs/run-alembic-migrations-with-smoke-test.yaml` — the Phase 1 revision rides this path, no new mechanism |
| Image build | Add an `enrichment` build step to `cloudbuild.yaml`, following the `processor` step, from a new `Dockerfile.enrichment` based on `Dockerfile.base` |
| Deploy trigger | `.github/workflows/build-and-deploy-services.yml` path filters must gain `src/enrichment/` — the existing filters were built per service and silently skip unlisted paths (this has bitten before; see `docs/` deploy-gotcha notes) |
| Namespace | `production`, as all existing CronJobs |
| BigQuery sync | Transfer configs live in project `mizzou-news-crawler`, location `us`; the four existing ids are listed by `bq ls --transfer_config` |

## 6. Cross-cutting requirements

| Requirement | Where |
|---|---|
| One article's failure never aborts a batch | `orchestrator.py`, per-article try |
| Commit per article, not per run | `repository.py` |
| Cost recorded per article; ceiling halts the run | `cost.py` |
| Rejection is terminal; failure is retryable | `orchestrator.py` |
| Alert on age of the oldest unenriched candidate | Phase 6 |
| `operator_bypass` path exists and is used in drills | Phase 6 |
| Structured logs carry `article_id`, `step`, `dataset` | all |

## 7. Risks

| Risk | Mitigation | Phase |
|---|---|---|
| Enriching sets a status the old export criterion misses | Widen before enriching | 2 |
| Reprocessing withdraws published rows | Version comparison, never a status reset; a named test | 5 |
| Backfield upgrade silently moves labels | Pin the commit; diff categories over the 100-article sample | 3 |
| OpenRouter outage withholds the corpus | `operator_bypass`, backlog alert, `failed_max_attempts` | 5–6 |
| Profile drift between datasets corrupts analysis | `steps_applied` recorded; consumers filter on it | 4 |
| Cost overrun | Per-run ceiling, `--dry-run` projection | 5 |

## 8. Not in scope

Entity canonicalization, embeddings, backfield's Stylebook or APIs, replacing our
CIN classifier, and the ~82,000 historical articles outside the supplied backfill
list. Each is recorded in §12 of the proposal.
