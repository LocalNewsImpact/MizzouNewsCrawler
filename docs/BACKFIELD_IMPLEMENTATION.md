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
| `export_exclude_scopes` outside the seven non-point categories, or set without `scope` | Reject |

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

| Task | Result (measured 2026-08-21) |
|---|---|
| Prompt caching | **Active with no code change** — presets already put `{text}` last; warm calls report 1,856–1,920 cached tokens, $0.0002–0.0004 vs $0.00078 cold, ~80% hit rate in a burst |
| Preset consolidation | **Dropped** — combined vs separate agreement only 71–84% per dimension on 100 articles; a different classifier, not an optimisation |
| Content gate tuning | Threshold 5 confirmed on an unbiased 300 (no article ≥5; Oreo/consent stories score 4); corpus junk rate <0.3%; gate resampled to **head+middle windows** after head-only misclassified a good article; 10/11 on the adversarial set |
| Point resolution accuracy | **Open — human task.** The verification file is `backfield-cin-test/scope_geocode_report.csv` (38 resolved points, `suggested_point` column) |

**Exit:** met for the three measured tasks; point verification remains with the
reviewer and gates Phase 6's dataset enablement, not Phases 1–5.

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

**Executed 2026-08-21.** The Phase 1 migration was applied to production first
(head `e7a1c2b3d4f5` → `f8b2d3c4e5a6`), because the new syncs would otherwise
fail daily against tables that did not exist.

Transfer configs, project 145096615031, location `us`
(prefix `projects/145096615031/locations/us/transferConfigs/`):

| Table | Config id | Status |
|---|---|---|
| articles (widened) | `693ab8dd-0000-2226-891c-582429a83fdc` | pre-existing, filter now the three-status superset |
| article_enrichment | `6b11c241-0000-22e6-a83a-9898fbb3bd65` | created |
| article_places | `6b0c4aac-0000-2631-afe8-34c7e91d569b` | created |
| article_people | `6b11c263-0000-22e6-a83a-9898fbb3bd65` | created |
| article_organizations | `6abb5da1-0000-2369-ac2e-34c7e91a181b` | created |

All five daily at 07:00 UTC, `WRITE_TRUNCATE`, same connection.

**Trap, hit during execution: `bq update --transfer_config --params` REPLACES
the whole params object.** Passing only `query` silently dropped
`destination_table_name_template` and `write_disposition`, and the next run
failed with "A destination table must be set with SELECT statements." Any params
update must carry all three keys. The same replace-not-merge behaviour as
`gcloud run deploy --set-env-vars`.

**Exit — verified by manual runs:**
- Widened articles sync SUCCEEDED with **104,521 rows — identical** to the
  pre-change count and to production's superset count, queried the same day (the
  superset predicate equals `labeled` while no article carries a new status)
- All four new syncs SUCCEEDED, each landing **0 rows**
- The two-status form remains scheduled for Phase 7

**Rollback:** restore the previous inner query; correct while no article carries
a new status. The four new configs can simply be deleted.

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

## 5. Detailed contracts

The subsections below are the decisions an implementer would otherwise have to
make alone. They are part of the specification: departures are review findings,
not style choices.

### 5.1 Candidate queries

Steady state:

```sql
SELECT a.id, a.title, a.content, d.slug, s.city
FROM articles a
JOIN candidate_links cl ON cl.id = a.candidate_link_id
JOIN dataset_sources ds ON ds.source_id = cl.source_id
JOIN datasets d          ON d.id = ds.dataset_id
LEFT JOIN sources s      ON s.id = cl.source_id
WHERE d.slug = :dataset
  AND a.status = 'labeled'
  AND a.wire_check_status = 'complete'
  AND a.enrichment_attempts < :max_attempts
ORDER BY a.created_at
LIMIT :batch
FOR UPDATE OF a SKIP LOCKED
```

`FOR UPDATE SKIP LOCKED` follows the direct extraction path's pattern and makes
concurrent runs safe. Reprocessing adds the §8 version comparison as an `OR`
branch and drops the status filter for the two terminal statuses.

Backfill replaces the status predicate with `a.id = ANY(:ids)` and reports each
id that fails the remaining predicates, with which predicate failed.

### 5.2 Orchestrator algorithm

```
enrich_article(article, profile):
  steps = []
  if profile.content_gate:
      heuristic = boilerplate_score(article.content)          # free
      if heuristic >= HEURISTIC_REJECT:  return outcome(not_article, gate="heuristic")
      gate = run_content_gate(article)                        # truncated call
      if not gate.ok:                    return outcome(labeled)   # transient
      if gate.payload["verdict"] == "paywall":  return outcome(paywall)
      if not gate.payload["is_news"]:    return outcome(not_article)
      steps += [content_gate]
  scope = None
  if profile.scope:
      r = run_scope(article);  fail -> outcome(labeled)
      scope = r.payload["category"]; steps += [scope]
      if scope in profile.export_exclude_scopes:
          return outcome(out_of_scope)          # terminal; skips all remaining steps
  if profile.places and scope in POINT_SCOPES:               # never without scope
      r = run_places(article); fail -> outcome(labeled)
      steps += [places]
      point = resolve_point(r.payload, article.publication_city)
      if profile.geocode and point is None: ...               # §3 step 4
  for preset in profile.metadata_presets:
      r = run_preset(article, preset); fail -> outcome(labeled)
      steps += [preset]
  if profile.people:        run_people; fail -> outcome(labeled); steps += [people]
  if profile.organizations: run_organizations; likewise
  return outcome(enriched if steps else enrichment_skipped(profile_none))
```

Rules the pseudocode encodes, stated once:

- **Any transient failure aborts the article, not the batch**, leaves status
  `labeled`, increments `enrichment_attempts`, and discards partial results.
  Steps are cheap ($0.0008); partial-resume bookkeeping is not worth its bugs.
- **Gate rejection is terminal** and does not increment attempts.
- `POINT_SCOPES = {city_municipality, neighborhood_community}`.
- `places` without `scope` in a profile is a validation error (§3), because the
  gate on 54% of articles is the cost model.

### 5.3 Transient versus terminal

| Class | Examples | Effect |
|---|---|---|
| Transient | timeout, HTTP 429/5xx, malformed JSON, connection error | `labeled`, attempts += 1 |
| Terminal — content | gate verdicts | `not_article` / `paywall` |
| Terminal — exhausted | attempts == `ENRICHMENT_MAX_ATTEMPTS` | `enrichment_skipped` / `failed_max_attempts` |
| Configuration | invalid profile, missing key, unknown preset | **run fails at startup; no article is touched** |

Configuration errors must not burn attempts: a typo in a profile would otherwise
march every candidate to `failed_max_attempts`.

### 5.4 Field mappings, node payload → schema

Keys verified against real node output on 2026-08-20.

`place_extract` location → `article_places`:

| Payload | Column |
|---|---|
| `location.full` | `full_name` |
| `location.type` | `place_type` |
| `location.components.city` | `city` |
| `location.components.county` | `county` |
| `location.components.state.abbr` (dict) else the string | `state` |
| `location.components.address` | `address` |
| `description` | `description` |
| `original_text` | `mention_text` |

`person_extract` person → `article_people`:

| Payload | Column |
|---|---|
| `name`, `sort_key`, `title`, `affiliation` | same names |
| `type` | `person_type` |
| `role_in_story`, `nature`, `public_figure` | same names |
| `len(mentions)` | `mention_count` |
| `[m.text for m in mentions if m.quote]` | `quotes` (jsonb) |

`organization_extract` → `article_organizations`: `name`, `type → org_type`,
`organization_boundary → boundary`, `role_in_story`, `nature`,
`len(mentions) → mention_count`.

Payload fields not listed (`needs_review`, `review_*`, `nature_secondary_tags`,
`geocode_hints`) are dropped, deliberately: they serve backfield's review UI,
which is not deployed.

### 5.5 Point resolution

```
resolve_point(locations, publication_city):
  cities = unique normalized city components
  if len(cities) == 1:                        return (city, "single_city")
  if norm(publication_city) in cities:        return (publication_city, "publication_city")
  return None
```

`norm()` = lowercase, collapse whitespace, strip punctuation except internal
apostrophes ("Lee's Summit"), strip a leading "the". Coordinates come from a
GNIS lookup keyed on (place name, state); a miss leaves `lat/lon` null with the
place name still recorded.

### 5.6 Content gate

Heuristic: count of case-insensitive matches for `cookie(s)`, `consent`,
`privacy policy`, `advertising partner(s)`, `vendor list`, `manage preferences`,
`opt out` over the full text. `HEURISTIC_REJECT = 5`, pending Phase 0 tuning —
at 5 it selects exactly the one known-bad article in the sample and nothing
else.

Gate call: direct completion (not the `custom` preset), JSON response, sending
**two 800-character windows — head and middle** of
`f"Headline: {title}\n\n{content}"`. Head-only was tested and rejected in Phase
0: cleaning residue concentrates at the top and a known-good article whose text
opens with a cookie banner was misclassified. The prompt's decision rule is
"is a story present in either window" — furniture around a story does not change
the verdict, and the prompt says so explicitly. Verdicts `news` / `paywall` /
`not_news` map to pass / `paywall` / `not_article`. The prompt file lives in
`src/enrichment/prompts/content_gate.md`, versioned in `prompt_versions`.
Measured accuracy on the adversarial 11-article set: 10 of 11, with the vox-pop
limitation recorded in the proposal §3.

### 5.7 Cost accounting

`litellm`'s response `usage` supplies `prompt_tokens` and `completion_tokens`
per call; rates come from a config dict keyed by model id, not hardcoded
(`{"openrouter/deepseek/deepseek-v3.2": {"in": 0.25e-6, "out": 0.95e-6}}`).
`StepResult` carries tokens and cost; `article_enrichment.cost_usd` is their
sum. The ceiling check runs between articles, not between steps — an article is
never half-billed.

### 5.8 Scheduled queries for the new tables

One per table, following the existing four. Template:

```sql
SELECT * FROM EXTERNAL_QUERY(
  "mizzou-news-crawler.us.cloudsql_connection",
  "SELECT * FROM article_enrichment;");
```

Same for `article_places`, `article_people`, `article_organizations`. Full
refresh daily at 07:00 UTC, matching the articles sync so the joined state is
consistent within a day. No status filter: presence in these tables already
implies the article was processed.

### 5.9 CronJob schedule

`schedule: "30 */4 * * *"` — every four hours at :30, six runs a day, first
candidate enriched at most ~4h after labelling. Offset from the 07:00 UTC sync
so a run is not writing while the sync reads. `concurrencyPolicy: Forbid` plus
`SKIP LOCKED` makes an overrun harmless.

## 6. Delivery mechanics, verified against the repo

| Concern | Mechanism |
|---|---|
| Migrations in production | Alembic via the `migrator` image, built by `cloudbuild.yaml` and run as `k8s/jobs/run-alembic-migrations-with-smoke-test.yaml` — the Phase 1 revision rides this path, no new mechanism |
| Image build | Add an `enrichment` build step to `cloudbuild.yaml`, following the `processor` step, from a new `Dockerfile.enrichment` based on `Dockerfile.base` |
| Deploy trigger | `.github/workflows/build-and-deploy-services.yml` path filters must gain `src/enrichment/` — the existing filters were built per service and silently skip unlisted paths (this has bitten before; see `docs/` deploy-gotcha notes) |
| Namespace | `production`, as all existing CronJobs |
| BigQuery sync | Transfer configs live in project `mizzou-news-crawler`, location `us`; the four existing ids are listed by `bq ls --transfer_config` |

## 7. Cross-cutting requirements

| Requirement | Where |
|---|---|
| One article's failure never aborts a batch | `orchestrator.py`, per-article try |
| Commit per article, not per run | `repository.py` |
| Cost recorded per article; ceiling halts the run | `cost.py` |
| Rejection is terminal; failure is retryable | `orchestrator.py` |
| Alert on age of the oldest unenriched candidate | Phase 6 |
| `operator_bypass` path exists and is used in drills | Phase 6 |
| Structured logs carry `article_id`, `step`, `dataset` | all |

## 8. Risks

| Risk | Mitigation | Phase |
|---|---|---|
| Enriching sets a status the old export criterion misses | Widen before enriching | 2 |
| Reprocessing withdraws published rows | Version comparison, never a status reset; a named test | 5 |
| Backfield upgrade silently moves labels | Pin the commit; diff categories over the 100-article sample | 3 |
| OpenRouter outage withholds the corpus | `operator_bypass`, backlog alert, `failed_max_attempts` | 5–6 |
| Profile drift between datasets corrupts analysis | `steps_applied` recorded; consumers filter on it | 4 |
| Cost overrun | Per-run ceiling, `--dry-run` projection | 5 |

## 9. Not in scope

Entity canonicalization, embeddings, backfield's Stylebook or APIs, replacing our
CIN classifier, and the ~82,000 historical articles outside the supplied backfill
list. Each is recorded in §12 of the proposal.
