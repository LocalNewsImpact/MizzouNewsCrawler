# Enrichment split: specification and migration plan

The roadmap for moving enrichment out of this repository. Every table,
column, file, image, role, workflow and test is named; the order of
operations is fixed; each step has the check that proves it and the way
back if it fails. The reasoning is in
[SPLITTING_ENRICHMENT.md](SPLITTING_ENRICHMENT.md); this document is the
work.

Measured against `main` on 2026-09-05, datadesk `main`, and
`lnic-contracts` v0.3.0.

---

## 0. Decisions this specification takes

| Decision | Taken | Because |
| --- | --- | --- |
| Repository name | `LocalNewsImpact/lnic-classify` | Set 2026-09-05; the crawler and datadesk keep their names |
| Source layout | `src/enrichment/` kept verbatim; history carried with `git filter-repo` | A `git mv` diff, `blame` preserved, no import rewrites in the moved tests |
| Enrichment's own status lives in | `article_enrichment.status`, three values | One writer per column; `articles.status` stops at `labeled` for enrichment |
| Attempt counter lives in | new table `article_enrichment_attempts` | `article_enrichment` has five NOT NULL provenance columns; an attempt with no verdict cannot be a row there |
| Re-selection signal | `text_hash` mismatch, or a review decision newer than the row | Enrichment cannot be signalled through a column it no longer writes; both signals already exist on the row |
| A reviewer's "paywall" type | recorded as a decision that enrichment executes on its next run | Datadesk cannot INSERT an `article_enrichment` row (provenance columns); two writers of one column is the drift the split removes |
| Export criterion | `articles.status = 'labeled'` **and** `article_enrichment.status IN ('enriched','enrichment_skipped')` | The crawler's status says the article is real; enrichment's says it went through; a human exclusion on `articles.status` leaves the export regardless |
| Database role | `enrichment_rw`, no UPDATE on `articles` | The boundary is enforced by Postgres, as datadesk's already is |
| Migrations | own alembic chain, version table `alembic_version_enrichment`; one baseline squash + one change migration | The seven crawler migrations stay as history; production is stamped at the baseline |
| Image | `python:3.11-slim`, built by the shared `image-build.yml` through WIF | No `mizzou-base`, no Cloud Build trigger, the suite's pattern |
| Read-side shapes | declared in `lnic-contracts` as data, with a DDL helper for tests | `crawler-schema` today is a datadesk command over a live database, not a declaration |
| Base image dependency of the gazetteer script | `scripts/populate_gazetteer.py` keeps a 30-line census-centroid lookup and its own copy of `census_places.csv` | The one import into `src/enrichment/` from the rest of the tree (`place_geoid`, line 211) |

Nothing here is a parallel-write design. `cronjob/mizzou-enrichment` is
suspended (measured 2026-09-05: `SUSPEND=True`, no run in 15 days), so
the cut-over is a switch with a rollback, not a dual-running window.

---

## 1. The end state

| | Today | After |
| --- | --- | --- |
| Repositories writing enrichment tables | crawler | `lnic-classify` |
| Writers of `articles.status` | crawler, enrichment, datadesk | crawler, datadesk |
| Writers of `articles.enriched_at`, `articles.enrichment_attempts` | enrichment | nobody; columns dropped |
| Enrichment's verdict | `articles.status` | `article_enrichment.status` |
| Attempt counter | `articles.enrichment_attempts` | `article_enrichment_attempts.attempts` |
| Export filter (BigQuery) | `status IN ('enriched','enrichment_skipped')` | `a.status = 'labeled' AND ae.status IN (…)` |
| Enrichment image | `mizzou-base` (10 GB) + wheels | `python:3.11-slim` + wheels (~350 MB) |
| Enrichment's database identity | `mizzou_user` (owner of everything) | `enrichment_rw` |
| Status vocabulary | convention in three repositories | `lnic_contracts.article_status`, asserted in three repositories |
| `lnic-contracts` | v0.3.0 | v0.4.0 |

---

## 2. The new repository

### 2.1 Layout

Origin column: `moved` is a path in this repository carried with history;
`new` is written for the split.

```
lnic-classify/
├── .github/
│   ├── CODEOWNERS                              new
│   └── workflows/
│       ├── ci.yml                              new   calls python-checks.yml@ci-v1, integration: true
│       ├── conforms.yml                        new   calls conforms.yml@ci-v1
│       ├── build.yml                           new   calls image-build.yml@ci-v1 on push to main
│       └── deploy.yml                          new   migrate job, then kubectl set image
├── alembic/
│   ├── env.py                                  new   version_table="alembic_version_enrichment"
│   ├── script.py.mako                          new
│   └── versions/
│       ├── 0001_baseline.py                    new   squash of the seven crawler migrations (§4.3)
│       └── 0002_status_text_hash_attempts.py   new   the columns and table the split adds (§4.4)
├── alembic.ini                                 new
├── docker-compose.test.yml                     new   postgres:16 on :5436 for make test-db
├── Dockerfile                                  moved from Dockerfile.enrichment, rebased on python:3.11-slim (§2.6)
├── Makefile                                    new   the targets conforms.yml requires (§2.4)
├── infra/sql/
│   ├── create_enrichment_role.sql              new   §4.6
│   └── apply.sh                                new   copy of datadesk's infra/sql/apply.sh
├── k8s/
│   ├── enrichment-cronjob.yaml                 moved from k8s/enrichment-cronjob.yaml (§6.2)
│   ├── migrate-job.tpl.yaml                    new   §6.3
│   └── versions.env                            new   ENRICHMENT_TAG only
├── pyproject.toml                              new   ruff, mypy, pytest config; no version (not a package)
├── requirements.txt                            new   §2.5
├── requirements-dev.txt                        new
├── scripts/
│   ├── setup-hooks.sh                          new   installs the pre-push hook conforms.yml checks for
│   └── ci/test.sh, test-integration.sh         new   copies of the crawler's, minus the crawler's marks
├── src/__init__.py                             new   empty; `python -m src.enrichment`
├── src/enrichment/
│   ├── __init__.py                             moved
│   ├── __main__.py                             new   `python -m src.enrichment` → cli.main()
│   ├── adapter.py                              moved, unchanged
│   ├── cli.py                                  moved from src/cli/commands/enrichment.py (§3.2)
│   ├── cost.py                                 moved, unchanged
│   ├── db.py                                   new   §3.1
│   ├── fips.py                                 moved, unchanged
│   ├── gate.py                                 moved, unchanged
│   ├── orchestrator.py                         moved, unchanged
│   ├── profiles.py                             moved, unchanged
│   ├── repository.py                           moved, changed (§3.3)
│   ├── resolve.py                              moved, unchanged
│   ├── types.py                                moved, changed (§3.4)
│   ├── prompts/content_gate.md, focus.md       moved
│   └── reference/census_counties.csv, census_places.csv   moved
├── tests/
│   ├── conftest.py                             new   builds the crawler's read-side tables from the contract (§7.3)
│   ├── enrichment/test_adapter.py              moved, unchanged (20 tests)
│   ├── enrichment/test_fips.py                 moved, unchanged (22 tests)
│   ├── enrichment/test_orchestrator.py         moved, unchanged (33 tests)
│   ├── enrichment/test_cli.py                  moved from tests/cli/commands/test_enrichment_command.py, changed (§7.2)
│   ├── enrichment/test_db.py                   new
│   ├── enrichment/test_contract.py             new   status vocabulary assertion (§5.4)
│   ├── integration/test_repository.py          moved from tests/integration/test_enrichment.py, rewritten (§7.4)
│   ├── integration/test_migrations.py          new
│   └── integration/test_role.py                new   the grants, exercised (§7.4)
└── vendor/backfield/*.whl                      moved (6 wheels, 852 KB)
```

`src/enrichment/data/` is untracked in this repository and does not move.
`sitecustomize.py` does not move: it is a `newspaper` cache shim plus a
`sys.path` fix, and the image sets `PYTHONPATH=/app`.

### 2.2 Carrying history

```sh
git clone --no-local git@github.com:LocalNewsImpact/MizzouNewsCrawler.git lnic-classify
cd lnic-classify
git filter-repo \
  --path src/enrichment/ \
  --path src/cli/commands/enrichment.py \
  --path vendor/backfield/ \
  --path Dockerfile.enrichment \
  --path k8s/enrichment-cronjob.yaml \
  --path tests/enrichment/ \
  --path tests/cli/commands/test_enrichment_command.py \
  --path tests/integration/test_enrichment.py \
  --path-rename src/cli/commands/enrichment.py:src/enrichment/cli.py \
  --path-rename Dockerfile.enrichment:Dockerfile \
  --path-rename tests/cli/commands/test_enrichment_command.py:tests/enrichment/test_cli.py \
  --path-rename tests/integration/test_enrichment.py:tests/integration/test_repository.py
git remote add origin git@github.com:LocalNewsImpact/lnic-classify.git
```

The repository is created empty first (`gh repo create LocalNewsImpact/lnic-classify --private`);
the org ruleset applies to it on creation. The first push is the filtered
history followed by one commit adding everything marked `new`.

### 2.3 Rulesets

The org ruleset "Main is reached by pull request" (22350227) applies
without action. One per-repo ruleset is created, a copy of the crawler's
"Required checks" (8488585) with the check names `lint`, `test`,
`integration`, `conforms`, bypass `OrganizationAdmin` mode `pull_request`
(or `always`, whichever the org ruleset carries after the current change).

```sh
gh api repos/LocalNewsImpact/MizzouNewsCrawler/rulesets/8488585 \
  | jq '{name,target,enforcement,bypass_actors,conditions,rules}
         | .rules[0].parameters.required_status_checks
           = [{"context":"lint"},{"context":"test"},{"context":"integration"},{"context":"conforms"}]' \
  > ruleset.json
gh api -X POST repos/LocalNewsImpact/lnic-classify/rulesets --input ruleset.json
```

Verify: `gh api repos/LocalNewsImpact/lnic-classify/rulesets --jq '.[].name'` lists both.

### 2.4 Makefile

`conforms.yml` requires that `make lint`, `make test`, `make test-integration`
exist, that a pre-push hook runs them, that no repository-local coverage
floor is set, and that `make test` runs `lnic_contracts.coverage_floor`.

```make
PY := .venv/bin/python

setup:
	python3.11 -m venv .venv
	$(PY) -m pip install -q -r requirements.txt -r requirements-dev.txt
	$(PY) -m pip install -q vendor/backfield/*.whl
	scripts/setup-hooks.sh

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

typecheck:
	$(PY) -m mypy src

test:
	scripts/ci/test.sh            # pytest -m 'not integration' --cov=src --cov-report=xml
	$(PY) -m lnic_contracts.coverage_floor coverage.xml

test-db:
	docker compose -f docker-compose.test.yml up -d --wait

test-integration: test-db
	DATABASE_URL=postgresql+pg8000://postgres:postgres@127.0.0.1:5436/test \
	scripts/ci/test-integration.sh   # alembic upgrade head; pytest -m integration

check: lint typecheck test test-integration
```

In CI, `test-integration` runs without `test-db`: the shared workflow
provides `PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`, and
`scripts/ci/test-integration.sh` composes `DATABASE_URL` from them when
`DATABASE_URL` is unset. The crawler's `scripts/ci/test-integration.sh`
already does this.

### 2.5 Dependencies

`requirements.txt` is the subset of the crawler's `requirements-base.txt`
that `src/enrichment/` imports, pinned at the versions the crawler pins:

```
sqlalchemy==<crawler pin>
pg8000==<crawler pin>
cloud-sql-python-connector[pg8000]==<crawler pin>
alembic==<crawler pin>
litellm==<crawler pin>
lnic-contracts @ https://github.com/LocalNewsImpact/lnic-contracts/archive/refs/tags/v0.4.0.tar.gz
```

The six backfield wheels install from `vendor/` in `make setup` and in the
Dockerfile, as today. Everything else in `requirements-base.txt` (torch,
spaCy, scikit-learn, newspaper, Selenium, the crawler's HTTP stack) does
not install.

The pin values are read from `requirements-base.txt` at the time of the
move; the Dockerfile's `verify-dependencies` step (§2.6) is what proves
the list is complete.

### 2.6 Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt vendor/backfield/ ./vendor/
RUN pip install --no-cache-dir -r requirements.txt vendor/*.whl
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./
ENV PYTHONPATH=/app BACKFIELD_COMMIT=c842d044
# The image imports everything it will need at run time, at build time.
RUN python -c "from src.enrichment.adapter import _load; \
  [_load(n) for n in ('article_metadata','place_extract','person_extract','organization_extract')]; \
  import litellm, alembic, lnic_contracts.article_status"
CMD ["python", "-m", "src.enrichment", "run", "--dataset", "Mizzou-Missouri-State"]
```

The `RUN python -c` line is the crawler's `verify-dependencies` Cloud Build
step moved into the build, so a missing pin fails the image, not the
CronJob.

### 2.7 Workflows

`ci.yml`:

```yaml
name: ci
on:
  pull_request:
  push:
    branches: [main]
jobs:
  checks:
    uses: LocalNewsImpact/lnic-contracts/.github/workflows/python-checks.yml@ci-v1
    with:
      typecheck: true
      integration: true
      pip-cache: true
```

`conforms.yml` calls `conforms.yml@ci-v1` with no inputs.

`build.yml`, on push to `main` and `workflow_dispatch`:

```yaml
jobs:
  image:
    uses: LocalNewsImpact/lnic-contracts/.github/workflows/image-build.yml@ci-v1
    with:
      image: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/enrichment
      dockerfile: Dockerfile
      inputs_to_hash: "Dockerfile requirements.txt vendor src alembic alembic.ini"
      project: mizzou-news-crawler
      workload_identity_provider: ${{ vars.WIF_PROVIDER }}
      service_account: enrichment-deploy@mizzou-news-crawler.iam.gserviceaccount.com
      also_tag: latest
```

`deploy.yml`, `workflow_run` on `build.yml` success (and `workflow_dispatch`
with a tag input): authenticates through the same WIF provider, gets
`mizzou-cluster` credentials (`us-central1-a`), renders
`k8s/migrate-job.tpl.yaml` with the built tag, applies it, waits
(`kubectl wait --for=condition=complete --timeout=600s`), then
`kubectl set image cronjob/mizzou-enrichment enrichment=<image>:<tag>` and
commits the tag to `k8s/versions.env`. A failed migration job stops the
workflow before the CronJob's image changes.

The image tag is the composite action `image-tag`'s output (a hash of
`inputs_to_hash`), as in datadesk; `versions.env` records it for the
manual path.

### 2.8 GCP identity (one-time)

The `github` WIF pool and provider exist in `mizzou-news-crawler`
(145096615031); the provider's attribute condition is
`assertion.repository=='LocalNewsImpact/MizzouNewsCrawler'`.

```sh
gcloud iam workload-identity-pools providers update-oidc github \
  --project=mizzou-news-crawler --location=global --workload-identity-pool=github \
  --attribute-condition="assertion.repository in ['LocalNewsImpact/MizzouNewsCrawler','LocalNewsImpact/lnic-classify']"

gcloud iam service-accounts create enrichment-deploy --project=mizzou-news-crawler \
  --display-name="lnic-classify GitHub Actions"
gcloud artifacts repositories add-iam-policy-binding mizzou-crawler \
  --project=mizzou-news-crawler --location=us-central1 \
  --member="serviceAccount:enrichment-deploy@mizzou-news-crawler.iam.gserviceaccount.com" \
  --role=roles/artifactregistry.writer
gcloud projects add-iam-policy-binding mizzou-news-crawler \
  --member="serviceAccount:enrichment-deploy@mizzou-news-crawler.iam.gserviceaccount.com" \
  --role=roles/container.developer
gcloud iam service-accounts add-iam-policy-binding \
  enrichment-deploy@mizzou-news-crawler.iam.gserviceaccount.com --project=mizzou-news-crawler \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/145096615031/locations/global/workloadIdentityPools/github/attribute.repository/LocalNewsImpact/lnic-classify"

gh variable set WIF_PROVIDER --repo LocalNewsImpact/lnic-classify \
  --body "projects/145096615031/locations/global/workloadIdentityPools/github/providers/github"
```

Verify: a `workflow_dispatch` of `build.yml` pushes an image;
`gcloud artifacts docker images list us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/enrichment --limit=1`
shows it.

---

## 3. Code

### 3.1 `src/enrichment/db.py` (new)

Replaces the borrowed `DatabaseManager` and the 163-line
`src/models/cloud_sql_connector.py`. Same two modes the CronJob and the
tests use today, nothing else.

```python
"""The one connection enrichment opens. DATABASE_URL for tests and local
runs; the Cloud SQL connector in production. No ORM."""
import os
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker

class ConfigurationError(RuntimeError): ...

def engine_from_env(env=os.environ) -> Engine:
    if url := env.get("DATABASE_URL"):
        return create_engine(url, pool_pre_ping=True, future=True)
    if env.get("USE_CLOUD_SQL_CONNECTOR", "").lower() == "true":
        from google.cloud.sql.connector import Connector
        connector = Connector()
        def connect():
            return connector.connect(
                env["CLOUD_SQL_INSTANCE"], "pg8000",
                user=env["DATABASE_USER"], password=env["DATABASE_PASSWORD"], db=env["DATABASE_NAME"],
            )
        return create_engine("postgresql+pg8000://", creator=connect, pool_pre_ping=True, future=True)
    raise ConfigurationError("set DATABASE_URL, or USE_CLOUD_SQL_CONNECTOR=true with CLOUD_SQL_INSTANCE, DATABASE_USER, DATABASE_PASSWORD, DATABASE_NAME")

def session_factory(engine: Engine):
    return sessionmaker(bind=engine, future=True)
```

### 3.2 `src/enrichment/cli.py` (moved, changed)

From `src/cli/commands/enrichment.py`. Changes:

- Line 136 `from src.models.database import DatabaseManager` → `from src.enrichment.db import engine_from_env, session_factory`; the session factory handed to `_process` is `session_factory(engine_from_env())`.
- The `status` verb's query (counts of `a.status IN ('labeled','enriched','enrichment_skipped','not_article','paywall')`) becomes a `LEFT JOIN article_enrichment ae` and reports: `labeled` with no row (waiting), rows by `ae.status`, and `article_enrichment_attempts` rows at `attempts >= max` (exhausted).
- Verbs `run`, `backfill`, `reprocess` are unchanged in signature; `argparse` replaces the crawler's `cli_modular` registration; `__main__.py` calls `main(sys.argv[1:])`.
- Environment variables unchanged: `ENRICHMENT_CONCURRENCY` (10), `ENRICHMENT_MAX_ATTEMPTS` (3), `ENRICHMENT_SPEND_CEILING_USD`, `BACKFIELD_COMMIT`, `ENRICHMENT_MODEL`.

### 3.3 `src/enrichment/repository.py` (moved, changed)

Everything that touched `articles` as a writer changes; every write to the
five owned tables is unchanged.

**Selection.** Two statements in one transaction replace `_CANDIDATE_SQL`
and `_REPROCESS_SQL` (they differ only by the `since` floor, which stays a
bound parameter). `FOR UPDATE` on `articles` requires UPDATE privilege on
the table, which `enrichment_rw` does not hold, so the lock moves to the
attempts row.

```sql
-- 1. Make sure every candidate has an attempts row to lock.
INSERT INTO article_enrichment_attempts (article_id)
SELECT a.id FROM articles a
JOIN candidate_links cl ON cl.id = a.candidate_link_id
JOIN dataset_sources ds ON ds.source_id = cl.source_id
JOIN datasets d ON d.id = ds.dataset_id
WHERE d.slug = :dataset AND a.status = 'labeled'
ON CONFLICT (article_id) DO NOTHING;

-- 2. Select and lock.
SELECT a.id, a.title, a.content, a.text_hash, d.slug AS dataset_slug,
       s.city AS publication_city,
       coalesce(nullif(s.metadata::json->>'state',''), d.metadata::json->>'default_state') AS publication_state,
       rd.value AS decision
FROM articles a
JOIN candidate_links cl ON cl.id = a.candidate_link_id
JOIN dataset_sources ds ON ds.source_id = cl.source_id
JOIN datasets d          ON d.id = ds.dataset_id
LEFT JOIN sources s      ON s.id = cl.source_id
JOIN article_enrichment_attempts at ON at.article_id = a.id
LEFT JOIN article_enrichment ae     ON ae.article_id = a.id
LEFT JOIN LATERAL (
    SELECT d.value FROM json_each(a.metadata::json->'review_decided') d
    WHERE d.value->>'stage' = 'enrichment'
      AND d.value->>'decision' IN ('restore', 'reject')
      AND (ae.enriched_at IS NULL OR (d.value->>'at')::timestamptz > ae.enriched_at)
    ORDER BY d.value->>'at' DESC LIMIT 1
) rd ON true
WHERE d.slug = :dataset
  AND a.status = 'labeled'
  AND a.wire_check_status IN ('complete', 'local')
  AND at.attempts < :max_attempts
  AND (
        ae.article_id IS NULL                                    -- never enriched
     OR ae.text_hash IS DISTINCT FROM a.text_hash                -- the body changed
     OR rd.value IS NOT NULL                                     -- a person asked
  )
  AND (CAST(:since AS date) IS NULL OR a.created_at >= CAST(:since AS date))
ORDER BY a.created_at
LIMIT :batch
FOR UPDATE OF at SKIP LOCKED;
```

`json_each` over a `json` column is the same operation
`s.metadata::json->>'state'` already performs per row. The `LATERAL` runs
only for rows that pass the earlier predicates; on the largest dataset
that is the `labeled` rows with an `article_enrichment` row
(19,238 on 2026-09-04), every four hours. No index is added until it is
measured to need one.

**Reset on a decision.** When `decision` is present and its `decision` is
`restore`, `at.attempts` is set to 0 in the same transaction before the
article is processed: a person asked for another run and the cap must
not refuse it.

**Executing a reviewer's type.** When `decision` is present with
`decision = 'reject'` and `type = 'paywall'` (the key added in §5.3), the
orchestrator is not called. `persist_outcome` writes an
`article_enrichment` row with `status = 'enrichment_skipped'`,
`skip_reason = 'paywall_stub'`, `steps_applied = '[]'`, `model = 'none'`,
`prompt_versions = '{}'`, `cost_usd = 0`, `content_gate_verdict = 'paywall'`,
the profile version and `BACKFIELD_COMMIT` of the runtime, and
`text_hash = a.text_hash`. `skip_reason = 'paywall_stub'` is the value
datadesk's queue already reads (`PAYWALL_STUB_SKIP_REASONS`). A `reject`
with any other type, or none, is not selected: those set `articles.status`
to a crawler value and the article is no longer `labeled`.

**`persist_outcome`.** The three `articles` writes go.

| Today | After |
| --- | --- |
| `labeled` outcome → `UPDATE articles SET enrichment_attempts = enrichment_attempts + 1` (line 342) | `UPDATE article_enrichment_attempts SET attempts = attempts + 1, last_attempted_at = now(), last_error = :error WHERE article_id = :id` |
| terminal outcome → `INSERT … ON CONFLICT (article_id) DO UPDATE` into `article_enrichment` (lines 445–470) | same, plus `status = :status, text_hash = :text_hash` in both the insert and the `DO UPDATE SET` list |
| terminal outcome → `UPDATE articles SET status = :status, enriched_at = :now WHERE id = :id` (line 691) | removed |
| — | `UPDATE article_enrichment_attempts SET attempts = 0, last_error = NULL WHERE article_id = :id` on a terminal outcome, so a later `text_hash` change starts with a clean cap |

`EXPORTABLE_STATUSES` and `TERMINAL_STATUSES` are deleted from this
module and imported from `lnic_contracts.article_status` (§5.1).
`select_by_ids` (the `backfill` list report) reports against
`article_enrichment.status` and the attempts table instead of
`articles.status`.

`dataset_profile` (reads `datasets.metadata->'enrichment_profile'`) is
unchanged.

### 3.4 `src/enrichment/types.py` (moved, changed)

`ArticleInput` gains `text_hash: str | None` and
`decision: dict | None = None`. `EnrichmentOutcome.status` is typed against
the contract: `enriched | enrichment_skipped | not_article`, or `labeled`
meaning "no verdict, count the attempt". The stale `paywall` in the
comment goes; the orchestrator has mapped the gate's `paywall` verdict to
`enrichment_skipped` since `_GATE_VERDICT_STATUS` (orchestrator.py:41).

### 3.5 Crawler: `scripts/populate_gazetteer.py`

Line 211 `from src.enrichment.fips import place_geoid as census_place_geoid`
is the one import into `src/enrichment/` from the rest of this tree. It
uses the result's `lat`/`lon` only (line 1685). Replacement:
`src/utils/census_places.py`, ~30 lines: load
`src/utils/reference/census_places.csv` once, `place_centroid(city, state) -> (lat, lon) | None`
with the same suffix stripping `fips._strip_suffix` applies. The CSV
(1.6 MB, the public Census Gazetteer file) is copied; it is reference
data, not a definition either repository owns. `.gitignore` line 158
(`!src/enrichment/reference/*.csv`) becomes `!src/utils/reference/*.csv`.

---

## 4. Database

One database, `mizzou`, instance `mizzou-news-crawler:us-central1:mizzou-db-prod-ssd`.

### 4.1 Tables enrichment owns after the split

Columns as created by the seven crawler migrations
(`f8b2d3c4e5a6` … `e4a7b8c9d0f1`), plus the additions marked **new**.

**`article_enrichment`** — one row per article enrichment has finished with.

| Column | Type | Constraint |
| --- | --- | --- |
| article_id | TEXT | PK, FK `articles.id` ON DELETE CASCADE |
| **status** | TEXT | **new**; NOT NULL; CHECK IN ('enriched','enrichment_skipped','not_article') |
| **text_hash** | TEXT | **new**; `articles.text_hash` at the time of the write; NULL only on the paywall-decision path when the article has none |
| profile_version | INTEGER | NOT NULL |
| steps_applied | JSON | NOT NULL; GIN index |
| skip_reason | TEXT | |
| backfield_commit | TEXT | NOT NULL |
| model | TEXT | NOT NULL |
| prompt_versions | JSON | NOT NULL |
| cost_usd | NUMERIC(10,6) | |
| enriched_at | TIMESTAMPTZ | NOT NULL DEFAULT CURRENT_TIMESTAMP |
| is_news_content | BOOLEAN | |
| content_gate_verdict | TEXT | (`28a393d67304`) |
| content_gate_reason | TEXT | |
| scope, subject, topic, format, timeframe, user_need | TEXT | |
| scope_confidence, subject_confidence, topic_confidence, format_confidence, timeframe_confidence, user_need_confidence | REAL | |
| rationales | JSON | |
| point_place, point_method | TEXT | |
| point_lat, point_lon | DOUBLE PRECISION | |
| point_gnis | TEXT | |
| point_geoid, point_geoid_level | TEXT | (`a9c3d4e5f6b7`) |
| point_zcta | TEXT | (`e4a7b8c9d0f1`) |
| geoids | JSON | (`c2e5f6a7b8d9`) |
| geo_skip_reason | TEXT | (`d3f6a7b8c9e0`) |

Index **new**: `article_enrichment (status)`.

**`article_enrichment_attempts`** — **new**; one row per article enrichment
has looked at, whether or not it finished.

| Column | Type | Constraint |
| --- | --- | --- |
| article_id | TEXT | PK, FK `articles.id` ON DELETE CASCADE |
| attempts | INTEGER | NOT NULL DEFAULT 0 |
| last_attempted_at | TIMESTAMPTZ | |
| last_error | TEXT | |

**`article_places`**, **`article_people`**, **`article_organizations`**,
**`article_geoids`** — unchanged; columns as in `f8b2d3c4e5a6`,
`b1d4e5f6a7c8` (`article_places.geoid`, `geoid_level`) and `c2e5f6a7b8d9`
(`article_geoids`, unique on `(article_id, geoid)`).

### 4.2 Columns that leave `articles`

| Column | Added by | Dropped by |
| --- | --- | --- |
| `enriched_at` | crawler `f8b2d3c4e5a6` | crawler migration `drop_enrichment_columns` (step 9, §8) |
| `enrichment_attempts` | crawler `f8b2d3c4e5a6` | same |

`articles.status` keeps its column and its crawler vocabulary. The values
`enriched` and `enrichment_skipped` stop being written by anyone; the
backfill (§4.5) returns the rows carrying them to `labeled`.

### 4.3 `0001_baseline.py`

`CREATE TABLE` for the five tables exactly as they stand at crawler head
`e4a7b8c9d0f1`, in one migration, `down_revision = None`. Its `downgrade`
raises: the baseline of a chain that owns production tables is not
reversible by design.

Production is **stamped** at `0001`
(`alembic stamp 0001`; `env.py` names the version table), never
upgraded to it: the tables exist. A fresh database (CI, a local run)
upgrades through it.

`alembic/env.py` passes `version_table="alembic_version_enrichment"` to
`context.configure` in both offline and online modes, and reads the URL
from `src.enrichment.db.engine_from_env()` so the migrate job and the CLI
open the database the same way.

### 4.4 `0002_status_text_hash_attempts.py`

```python
def upgrade():
    op.add_column("article_enrichment", sa.Column("status", sa.Text(), nullable=True))
    op.add_column("article_enrichment", sa.Column("text_hash", sa.Text(), nullable=True))
    op.create_table(
        "article_enrichment_attempts",
        sa.Column("article_id", sa.Text(), sa.ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
    )
    # Backfill (§4.5) runs here, in the same transaction, when the
    # articles columns exist; a fresh database has nothing to backfill.
    op.execute(BACKFILL_SQL)
    op.alter_column("article_enrichment", "status", nullable=False)
    op.create_check_constraint("article_enrichment_status_check", "article_enrichment",
                               "status IN ('enriched','enrichment_skipped','not_article')")
    op.create_index("ix_article_enrichment_status", "article_enrichment", ["status"])

def downgrade():
    # Reverse of the backfill: put enrichment's verdict back on articles.status.
    op.execute(RESTORE_SQL)
    op.drop_index("ix_article_enrichment_status")
    op.drop_constraint("article_enrichment_status_check", "article_enrichment")
    op.drop_table("article_enrichment_attempts")
    op.drop_column("article_enrichment", "text_hash")
    op.drop_column("article_enrichment", "status")
```

`BACKFILL_SQL` is guarded: it runs only when
`information_schema.columns` shows `articles.enrichment_attempts`, so the
migration is the same file on production (where the columns exist until
step 9) and in CI (where they never do).

### 4.5 Backfill

Measured before it runs, with the counts recorded in the PR:

```sql
SELECT a.status, ae.article_id IS NOT NULL AS has_row, count(*)
FROM articles a LEFT JOIN article_enrichment ae ON ae.article_id = a.id
WHERE a.status IN ('enriched','enrichment_skipped','not_article') OR ae.article_id IS NOT NULL
GROUP BY 1, 2 ORDER BY 1, 2;
SELECT count(*) FROM articles WHERE enrichment_attempts > 0;
```

Then, in order, inside migration `0002`:

```sql
-- 1. Enrichment's verdict, from the column it wrote.
UPDATE article_enrichment ae SET status = a.status
FROM articles a WHERE a.id = ae.article_id AND a.status IN ('enriched','enrichment_skipped');

-- 2. Rows whose article has since been given a crawler or human status:
--    the verdict is derived from the row's own columns.
UPDATE article_enrichment SET status = CASE
    WHEN content_gate_verdict = 'not_news' THEN 'not_article'
    WHEN skip_reason IS NOT NULL            THEN 'enrichment_skipped'
    ELSE 'enriched' END
WHERE status IS NULL;

-- 3. The body each row enriched is the body the article has now.
UPDATE article_enrichment ae SET text_hash = a.text_hash
FROM articles a WHERE a.id = ae.article_id;

-- 4. Reviewer paywall decisions that wrote the status without a row
--    (datadesk TYPE_BECOMES['paywall']). Provenance is the sentinel.
INSERT INTO article_enrichment (article_id, status, text_hash, profile_version, steps_applied,
    skip_reason, backfield_commit, model, prompt_versions, cost_usd, content_gate_verdict)
SELECT a.id, 'enrichment_skipped', a.text_hash, 0, '[]', 'paywall_stub', 'backfill', 'none', '{}', 0, 'paywall'
FROM articles a LEFT JOIN article_enrichment ae ON ae.article_id = a.id
WHERE a.status = 'enrichment_skipped' AND ae.article_id IS NULL;

-- 5. The attempt counter.
INSERT INTO article_enrichment_attempts (article_id, attempts)
SELECT id, enrichment_attempts FROM articles WHERE enrichment_attempts > 0
ON CONFLICT (article_id) DO NOTHING;

-- 6. articles.status stops carrying enrichment's values.
UPDATE articles SET status = 'labeled' WHERE status IN ('enriched','enrichment_skipped');
```

`not_article` on `articles.status` is left where it is: whether
enrichment's gate or a reviewer wrote it, it excludes the article from
the export today and continues to, and the two writers cannot be told
apart on the row.

`RESTORE_SQL` (downgrade, and the rollback in §8):

```sql
UPDATE articles a SET status = ae.status
FROM article_enrichment ae
WHERE ae.article_id = a.id AND a.status = 'labeled' AND ae.status IN ('enriched','enrichment_skipped');
UPDATE articles a SET enrichment_attempts = at.attempts
FROM article_enrichment_attempts at WHERE at.article_id = a.id;
```

Step 4's rows are re-created as `articles.status = 'enrichment_skipped'`
by the first statement, so the restore is complete.

### 4.6 The role: `infra/sql/create_enrichment_role.sql`

The pattern is datadesk's `infra/sql/create_crawler_write_role.sql`, run
as `mizzou_user` by `infra/sql/apply.sh` through the Cloud SQL proxy.

```sql
CREATE ROLE enrichment_rw LOGIN PASSWORD :'password';

-- Read side: the declared shape, nothing more.
GRANT USAGE ON SCHEMA public TO enrichment_rw;
GRANT SELECT ON articles, candidate_links, sources, datasets, dataset_sources TO enrichment_rw;
GRANT REFERENCES (id) ON articles TO enrichment_rw;      -- the FK from its own tables

-- Owned tables: full DML, and ownership so its migrations can ALTER them.
ALTER TABLE article_enrichment          OWNER TO enrichment_rw;
ALTER TABLE article_places              OWNER TO enrichment_rw;
ALTER TABLE article_people              OWNER TO enrichment_rw;
ALTER TABLE article_organizations       OWNER TO enrichment_rw;
ALTER TABLE article_geoids              OWNER TO enrichment_rw;
GRANT CREATE ON SCHEMA public TO enrichment_rw;          -- article_enrichment_attempts, alembic_version_enrichment

-- Nothing on articles beyond SELECT. No UPDATE, so FOR UPDATE on it fails too.
```

Ownership transfer keeps existing grants: `datadesk_rw`'s
`UPDATE (skip_reason, geo_skip_reason, scope, scope_confidence)` on
`article_enrichment` survives. `mizzou_user` remains superuser-equivalent
on the instance and keeps SELECT on everything through `PUBLIC`/owner
rules already in place; the crawler never writes these tables after
step 8 and has a test saying so (§7.5).

The password is generated at apply time, stored once:

```sh
gcloud secrets create enrichment-db-password --project=mizzou-news-crawler --data-file=-
kubectl -n production create secret generic enrichment-db-credentials \
  --from-literal=username=enrichment_rw --from-literal=password="$(gcloud secrets versions access latest --secret=enrichment-db-password)" \
  --from-literal=database=mizzou \
  --from-literal=instance-connection-name=mizzou-news-crawler:us-central1:mizzou-db-prod-ssd
```

Verify, as `enrichment_rw`:
`UPDATE articles SET status = status WHERE false;` → `permission denied`;
`SELECT 1 FROM articles LIMIT 1 FOR UPDATE;` → `permission denied`;
`INSERT INTO article_enrichment_attempts (article_id) VALUES ('x') ON CONFLICT DO NOTHING;` → succeeds (FK fails on the fake id, which is the point).

### 4.7 BigQuery

Transfer config `693ab8dd-0000-2226-891c-582429a83fdc` ("Sync Articles
from Cloud SQL", daily 07:00 UTC, `WRITE_TRUNCATE`): the inner query's
filter becomes

```sql
a.status = 'labeled'
AND EXISTS (SELECT 1 FROM article_enrichment ae
            WHERE ae.article_id = a.id AND ae.status IN ('enriched','enrichment_skipped'))
```

`bq update --transfer_config --params` replaces the whole params object
(recorded in BACKFIELD_IMPLEMENTATION.md): the update carries `query`,
`destination_table_name_template` and `write_disposition` together, read
back first with `bq show --format=prettyjson --transfer_config <name>`.

Transfer config `6b11c241-0000-22e6-a83a-9898fbb3bd65` (`article_enrichment`):
confirm the query selects `*`; if it names columns, add `status` and
`text_hash`.

Check after the first run following the switch: the `mizzou_analytics.articles`
row count equals the Postgres count of the new filter.

---

## 5. `lnic-contracts` v0.4.0

Three additions. Each is a shape; none is behaviour. Each consumer
accepts the shape with a test and changes nothing else on the bump.

### 5.1 `article_status.py`

```python
"""What articles.status and article_enrichment.status may hold, and who writes what."""

#: articles.status — the crawler's pipeline state machine. Written by the
#: crawler, and by datadesk on review.
CRAWLER_STATUSES = ("discovered", "extracted", "cleaned", "labeled", "paused", "in_review",
                    "wire", "obituary", "opinion", "weather", "paywall", "not_article",
                    "out_of_scope", "error")
#: The one status enrichment selects.
ENRICHMENT_SELECTS = "labeled"
#: article_enrichment.status — written by enrichment only.
ENRICHMENT_STATUSES = ("enriched", "enrichment_skipped", "not_article")
#: Which of those the export takes, together with articles.status == ENRICHMENT_SELECTS.
EXPORTED = ("enriched", "enrichment_skipped")
#: Written by datadesk on review. Every value is a CRAWLER_STATUS.
REVIEW_WRITES = ("paused", "cleaned", "labeled", "in_review", "not_article", "obituary",
                 "opinion", "weather", "wire", "out_of_scope")
```

`CRAWLER_STATUSES` is enumerated from the crawler's write sites on
2026-09-05 (`grep` of `status =` literals in `src/`) plus `in_review`
(`review_note.IN_REVIEW`) and the two datadesk-only values. The crawler's
assertion test (§7.5) is what makes the list authoritative: a value it
writes that the contract lacks fails the crawler's suite, and the fix is
a contract release.

### 5.2 `crawler_schema.py`

The read-side shape, as data. Column names and Postgres types for the
five tables enrichment reads, restricted to the columns it reads.

```python
TABLES: dict[str, dict[str, str]] = {
    "articles": {"id": "text", "candidate_link_id": "text", "title": "text", "content": "text",
                 "text_hash": "text", "status": "text", "wire_check_status": "text",
                 "metadata": "json", "created_at": "timestamp"},
    "candidate_links": {"id": "text", "source_id": "text"},
    "sources": {"id": "text", "city": "text", "metadata": "json"},
    "datasets": {"id": "text", "slug": "text", "metadata": "json"},
    "dataset_sources": {"dataset_id": "text", "source_id": "text"},
}
PRIMARY_KEYS = {"articles": "id", "candidate_links": "id", "sources": "id", "datasets": "id"}

def ddl(tables=TABLES) -> list[str]:
    """CREATE TABLE statements for a test database. Types are the declared
    Postgres types; nothing else is asserted."""
```

`ddl()` is a tool over the declaration in the same sense as
`coverage_floor.py`: it has no opinion about any consumer. Datadesk's
`tests/conftest.py` (which hand-writes the same DDL today) can adopt it
later; not part of this work.

### 5.3 `review_note.py`: the decision's type

`DECISION_OPTIONAL_KEYS = ("type",)`; `build_decision` takes
`type: str | None = None` and records it when given; `record_decision`
does not require it. `type` is the content type the reviewer chose
(datadesk's `TYPE_BECOMES` keys). Existing decision records are unchanged
and remain readable.

### 5.4 Consumers' tests on the bump

| Repository | Test | Asserts |
| --- | --- | --- |
| crawler | `tests/test_status_vocabulary_is_the_contract.py` | every `articles.status` literal written under `src/` is in `CRAWLER_STATUSES`; `review_hold` writes `IN_REVIEW`; no literal under `src/` is in `ENRICHMENT_STATUSES` |
| crawler | `tests/test_read_side_shape_is_declared.py` | for each table in `crawler_schema.TABLES`, the ORM model has the column and its SQLAlchemy type maps to the declared Postgres type |
| enrichment | `tests/enrichment/test_contract.py` | `repository` writes only `ENRICHMENT_STATUSES`; selects only `ENRICHMENT_SELECTS`; `EXPORTED ⊂ ENRICHMENT_STATUSES` |
| datadesk | `tests/test_status_vocabulary_is_the_contract.py` | `TYPE_BECOMES` values and `REWIND_TO` values are in `REVIEW_WRITES`; `EXPORTED_STATUSES` is the contract's `EXPORTED`; no datadesk write site holds an `ENRICHMENT_STATUSES` value |

Datadesk pins v0.2.0 today (`requirements.txt:36`); its bump to v0.4.0
takes v0.3.0's decision records with it, which it already uses through
its own copy — the bump removes that.

---

## 6. Deployment

### 6.1 Images

| Image | Built by | From | Deploys to |
| --- | --- | --- | --- |
| `…/mizzou-crawler/enrichment:<tag>` | `lnic-classify` `build.yml` (image-build.yml, WIF) | `python:3.11-slim` | `cronjob/mizzou-enrichment` |
| `…/mizzou-crawler/enrichment` via `build-enrichment-manual` (Cloud Build) | crawler | `mizzou-base` | retired at step 10 |

### 6.2 `k8s/enrichment-cronjob.yaml` (moved)

Diff against the current manifest:

```diff
             - name: DATABASE_USER
               valueFrom:
                 secretKeyRef:
-                  name: cloudsql-db-credentials
+                  name: enrichment-db-credentials
                   key: username
   (same for DATABASE_PASSWORD → password, DATABASE_NAME → database)
-          image: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/enrichment:${ENRICHMENT_TAG}
+          image: us-central1-docker.pkg.dev/mizzou-news-crawler/mizzou-crawler/enrichment:${ENRICHMENT_TAG}   # unchanged path; tag now from lnic-classify/k8s/versions.env
```

Schedule `30 */4 * * *`, `concurrencyPolicy: Forbid`,
`activeDeadlineSeconds: 10800`, service account `mizzou-app`, spot
tolerations, `ENRICHMENT_SPEND_CEILING_USD=5.00`, `openrouter-credentials`,
requests `250m/512Mi`, limit `1Gi`: unchanged.

### 6.3 `k8s/migrate-job.tpl.yaml` (new)

The crawler's `k8s/deploy-migration-job.tpl.yaml` with: image the
enrichment image, command
`["python", "-m", "alembic", "upgrade", "head"]`, env from
`enrichment-db-credentials`, label `app: enrichment-migrator`. Rendered
and applied by `deploy.yml` (§2.7); `backoffLimit: 1`.

### 6.4 Crawler removals (step 10)

| Path | Action |
| --- | --- |
| `Dockerfile.enrichment`, `gcp/cloudbuild/cloudbuild-enrichment.yaml`, `k8s/enrichment-cronjob.yaml` | delete |
| `src/enrichment/`, `src/cli/commands/enrichment.py`, `vendor/backfield/` | delete |
| `tests/enrichment/`, `tests/cli/commands/test_enrichment_command.py`, `tests/integration/test_enrichment.py` | delete |
| `.github/workflows/build-and-deploy-services.yml` | remove the `enrichment` detect regex, output, `build-enrichment` job, and `enrichment` from the `services` description |
| `.github/workflows/validate-gcp-triggers.yml:62` | remove `build-enrichment-manual` |
| `k8s/versions.env` | remove `ENRICHMENT_TAG` |
| `scripts/update-versions-env.sh` | remove `--enrichment` |
| `scripts/validate-dockerfile-deps.sh:26` | remove `Dockerfile.enrichment` |
| `src/cli/cli_modular.py:113` | remove `"enrich": "enrichment"` |
| `.gitignore:152–158` | `src/utils/reference/*.csv` (§3.5) |
| `alembic/versions/` | the seven files stay; a new migration drops the two `articles` columns (§4.2) |
| Cloud Build trigger `build-enrichment-manual` | `gcloud builds triggers delete build-enrichment-manual --project=mizzou-news-crawler` |
| `docs/BACKFIELD_*.md`, `BUILD_AND_CI_ARCHITECTURE.md` | pointers to the new repository |

---

## 7. Tests

### 7.1 Enrichment: moved unchanged

| File | Tests | Imports |
| --- | --- | --- |
| `tests/enrichment/test_fips.py` | 22 | `src.enrichment.fips` |
| `tests/enrichment/test_adapter.py` | 20 | `src.enrichment.adapter`, `litellm_stub` fixture |
| `tests/enrichment/test_orchestrator.py` | 33 | `src.enrichment.orchestrator`, `.types`, `.profiles` |

75 tests, self-contained today (stdlib, pytest, `src.enrichment` only).
They run under the new repository without an edit.

### 7.2 Enrichment: moved and changed

`tests/enrichment/test_cli.py` (17 tests, from
`test_enrichment_command.py`): the `db(monkeypatch)` fixture patches
`src.enrichment.db.engine_from_env` instead of
`src.models.database.DatabaseManager`; the `status` verb's tests assert the
new report shape (§3.2). Test count unchanged; three new tests:
`engine_from_env` with `DATABASE_URL`, with the connector variables, and
with neither (`ConfigurationError`), in `tests/enrichment/test_db.py`.

### 7.3 Enrichment: `tests/conftest.py` (new)

The integration database is built from two sources: the crawler's
read-side tables from `lnic_contracts.crawler_schema.ddl()`, then
enrichment's own tables from `alembic upgrade head` on its chain. That is
exactly what production looks like from `enrichment_rw`'s point of view,
and the crawler's own schema is never in this repository.

### 7.4 Enrichment: integration (rewritten)

`tests/integration/test_repository.py`, from
`tests/integration/test_enrichment.py`. Same seeding style (`TestRepository.db`
fixture: upgrade, seed, cleanup). Each existing test is kept under its
name with its assertion moved to the new columns, plus the new ones:

| Test | Asserts |
| --- | --- |
| `writes_all_four_tables_and_flips_status` | four tables written; `article_enrichment.status = 'enriched'`; `text_hash` equals the article's; **`articles.status` still `labeled`; `articles.updated_at` untouched** |
| `idempotency_second_run_selects_nothing` | unchanged |
| `labeled_outcome_writes_only_the_attempt_counter` | `article_enrichment_attempts.attempts` incremented, `last_error` set; no `article_enrichment` row; nothing on `articles` |
| `export_criterion_matches_only_terminal_statuses` | the §4.7 predicate over seeded rows: `labeled`+`enriched` in; `labeled`+`not_article` out; `not_article`+`enriched` out; `labeled` with no row out |
| `reprocessing_never_withdraws_rows` | unchanged |
| `legacy_wire_check_local_is_a_candidate` | unchanged |
| `steady_state_since_floors_the_candidates` | unchanged |
| `backfill_list_accounts_for_every_id` | report reads `article_enrichment.status` and the attempts table |
| `partial_failure_leaves_others_committed` | unchanged |
| `out_of_scope_does_not_export_and_is_not_reprocessed` | `articles.status = 'out_of_scope'` is never selected and never exported |
| **`a_changed_body_is_selected_again`** | update `articles.text_hash`; the article is selected; after the run `ae.text_hash` matches and it is not selected |
| **`a_restore_decision_is_selected_again_and_resets_the_cap`** | write a `review_decided` entry (stage `enrichment`, `restore`, `at` after `enriched_at`) with `attempts = 3`; selected; `attempts` reset |
| **`an_accept_decision_is_not_selected`** | same with `accept`; not selected |
| **`a_paywall_reject_writes_enrichment_skipped_without_a_model_call`** | `reject` + `type: paywall`; row written with `skip_reason = 'paywall_stub'`, `model = 'none'`, `cost_usd = 0`; the orchestrator stub was not called |
| **`a_reject_with_another_type_is_not_selected`** | `reject` + `type: obituary` with `articles.status = 'obituary'`; not selected |
| **`the_attempts_row_is_the_lock`** | two sessions; the second's select skips the first's locked row |
| **`the_cap_holds`** | `attempts = max_attempts`; not selected |

`tests/integration/test_migrations.py`: `0001` + `0002` on a fresh
database; `0002` downgrade and re-upgrade; `0002` upgrade against a
database seeded with the pre-split shape (the `articles` columns present,
rows in every status combination of §4.5) asserting each backfill step's
outcome and that `RESTORE_SQL` returns `articles.status` exactly.

`tests/integration/test_role.py`: applies `create_enrichment_role.sql`
against the test database (as the superuser the CI service provides),
reconnects as `enrichment_rw`, and asserts the three verifications in
§4.6 plus a full `persist_outcome` succeeding.

### 7.5 Crawler

| File | Change |
| --- | --- |
| `tests/test_review_hold.py` | `apply_hold("enriched", …)` cases become `apply_hold("labeled", …)`; a held article's `status_before` is a `CRAWLER_STATUSES` value |
| `tests/test_deploy_filters_match_the_dockerfiles.py` | drop the `enrichment` expectation |
| `tests/test_every_workload_gets_the_tag_that_was_built.py` | drop `ENRICHMENT_TAG` |
| `tests/test_the_dockerfile_validator_can_fail.py` | drop `Dockerfile.enrichment` from the list it validates |
| `tests/test_gazetteer_integration.py`, `test_geocode_cache.py`, `test_actual_telemetry.py` | unchanged imports; `populate_gazetteer` now imports `src.utils.census_places` |
| **new** `tests/test_status_vocabulary_is_the_contract.py` | §5.4 |
| **new** `tests/test_read_side_shape_is_declared.py` | §5.4 |
| **new** `tests/test_utils_census_places.py` | `place_centroid("Columbia", "MO")` returns the Census centroid; unknown city returns `None` |
| **new** `tests/test_no_migration_touches_enrichment_tables.py` | every `alembic/versions/*.py` with a revision after `e4a7b8c9d0f1` names none of the five tables |
| **new** `tests/integration/test_articles_drop_enrichment_columns.py` | the crawler's drop migration round-trips |

### 7.6 Datadesk

`tests/conftest.py` (lines 124, 132): the `articles` DDL loses
`enrichment_attempts` and `enriched_at`; `article_enrichment` gains
`status`, `text_hash`; `article_enrichment_attempts` is added.
`explorer/models.py`: `Article` loses the two fields (line 192 and the
`enriched_at` field); `ArticleEnrichment` (line 336 region) gains
`status`, `text_hash`; new unmanaged `ArticleEnrichmentAttempt`.

Code that changes, with the test file that covers each:

| Module | Change | Tests |
| --- | --- | --- |
| `review/dispositions.py` | `EXPORTED_STATUSES` (204) and `ENRICHMENT_FINISHED` (217) from the contract; `_enrichment_is_done_with_it` reads `ArticleEnrichment.status`; `TYPE_BECOMES["paywall"]` → `"labeled"` and the decision carries `type="paywall"` (§5.3); `REWIND_TO[ENRICHMENT]` stays `labeled` (now a no-op status write; the decision record is what re-selects) | `test_a_chosen_type_decides_the_status.py`, `test_extraction_dispositions.py`, `test_disposition_paths_are_real.py` (its `enrichment_attempts` reads become the attempts table), `test_the_extraction_queue_can_be_worked.py` |
| `review/queue.py` | `PAYWALL_STUB`, `SCOPE_MISLABEL` (332–334) match on `ArticleEnrichment.status = 'enrichment_skipped'` + `skip_reason`; the queue window (87–94) keys on the enrichment row, not `articles.status` | `test_review_queue.py`, `test_the_queue_window_and_scope_verbs.py` |
| `review/kernel.py:73` | comment and predicate to the row | same |
| `explorer/dashboard.py` | `enriched` / `enrichment_skipped` / `exported_unenriched` counted from `ArticleEnrichment.status` joined to `Article.status == 'labeled'` | `test_dashboard.py` |
| `explorer/costs.py` | unchanged (already reads `ArticleEnrichment.enriched_at`) | `test_costs.py` |
| `explorer/views.py:603` | order by the enrichment row's `enriched_at` (already the row) | `test_article_detail.py` |
| `visuals/corpus.py:452–459` | `ENRICHED_STATUSES` from the contract; the subset joins the row | `test_builder_steps.py` (685–738) |
| `explorer/templatetags/datadesk.py:166` | labels keyed on the row's status | `test_article_detail.py:299` |
| `templates/explorer/article_detail.html:122,159`, `review/queue.html`, `landing.html` | render the row's status | same |
| `infra/sql/create_crawler_write_role.sql` | `GRANT SELECT ON article_enrichment_attempts TO datadesk_rw` | `make crawler-schema` |
| `requirements.txt:36` | `lnic-contracts` v0.4.0 | — |
| **new** `tests/test_status_vocabulary_is_the_contract.py` | §5.4 | — |

Fourteen test files reference the old columns or statuses today
(`test_a_chosen_type_decides_the_status`, `test_costs`, `test_dashboard`,
`test_review_hold_and_questions`, `test_extraction_dispositions`,
`test_repeated_bodies_are_found`, `test_disposition_paths_are_real`,
`test_builder_steps`, `test_the_queue_window_and_scope_verbs`,
`test_article_detail`, `test_the_extraction_queue_can_be_worked`,
`test_review_queue`, `test_enrichment_grid`, `test_review_hold_and_questions`).
Each is edited, not replaced: the fixture rows move their status onto the
enrichment row and their attempts onto the attempts row; assertions
follow. `make check` on Postgres (`docker-compose.test.yml`, :5434) is the
gate; `make crawler-schema` against production through the proxy is the
proof the unmanaged models match after step 8.

---

## 8. Order of operations

Each step is one pull request in one repository, merged before the next
opens. Steps 1–5 change nothing in production.

| # | Repository | Work | Proof | Back out |
| --- | --- | --- | --- | --- |
| 1 | `lnic-contracts` | v0.4.0: §5.1–5.3, tests, tag | `make check`; tag exists | untag |
| 2 | crawler | pin v0.4.0; the two contract tests (§5.4); `src/utils/census_places.py` and the gazetteer import (§3.5) | `make check`; deploy of processor/crawler unaffected | revert |
| 3 | `lnic-classify` | repository created (§2.2), rulesets (§2.3), GCP identity (§2.8); everything in §2, §3, §4.3–4.4, §7.1–7.4 as the first PR | CI green: lint, typecheck, test (floor ≥ 80%), integration, conforms; `build.yml` dispatch pushes an image | delete the repository |
| 4 | — | restore the production instance to a clone (`gcloud sql instances clone`); run steps 6–8 against it end to end; record the §4.5 counts and the run's timings in the step-6 PR | one full CronJob run on the clone: rows written, `articles` untouched | delete the clone |
| 5 | datadesk | pin v0.4.0; §7.6 in full; `make check`; **not deployed** until step 8 — held as an open PR with CI green (the one open PR datadesk carries) | `make check` on :5434 | close |
| 6 | production | `apply.sh create_enrichment_role.sql`; Secret Manager + `enrichment-db-credentials` (§4.6) | the three verifications in §4.6 | `DROP ROLE` after `REASSIGN OWNED BY enrichment_rw TO mizzou_user` |
| 7 | production | `alembic stamp 0001`; `alembic upgrade head` (0002 with backfill) as `enrichment_rw` through the proxy, `statement_timeout` raised for the backfill | §4.5 counts match the pre-measurement; `SELECT count(*) FROM articles WHERE status IN ('enriched','enrichment_skipped')` = 0 | `alembic downgrade 0001` (runs `RESTORE_SQL`) |
| 8 | production, same hour | `bq update` (§4.7); merge and deploy datadesk (step 5's PR); `kubectl apply` the new CronJob manifest; unsuspend (`kubectl patch cronjob mizzou-enrichment -p '{"spec":{"suspend":false}}'`) | next 07:00 UTC BigQuery run: row count equals the new predicate's count; datadesk dashboard counts equal `article_enrichment.status` counts; first CronJob run writes rows and `articles.updated_at` max is unchanged | re-suspend; `bq update` back; datadesk revert deploy; step 7's downgrade |
| 9 | crawler | migration dropping `articles.enriched_at`, `articles.enrichment_attempts`; `test_review_hold` and the manifest tests (§7.5); §6.4 removals **except** the Cloud Build trigger and image | `make check`; `make crawler-schema` in datadesk green | revert; the downgrade re-adds the columns (nullable, empty) |
| 10 | crawler + GCP | delete `build-enrichment-manual`; delete the crawler-built `enrichment` image tags older than the new repository's first | `validate-gcp-triggers` green | none needed |

Steps 6–8 happen in one working session after step 4 has been run on the
clone. Step 9 waits a week of scheduled runs.

---

## 9. Schedule

| Day | Step | Deliverable |
| --- | --- | --- |
| 1 | 1 | `lnic-contracts` v0.4.0 tagged |
| 1–2 | 2 | crawler PR: pin, two contract tests, `census_places` |
| 2–4 | 3 | `lnic-classify`: history, `db.py`, `cli.py`, repository changes, alembic chain, Dockerfile, workflows, Makefile, hook, all tests green, image built; GCP identity |
| 5 | 4 | clone rehearsal; counts and timings recorded |
| 5–6 | 5 | datadesk PR: models, dispositions, queue, dashboard, corpus, templates, conftest, fourteen test files, grant |
| 7 | 6–8 | production cut-over |
| 8 | — | first scheduled runs observed; BigQuery row count checked at 07:00 UTC |
| 9 | 9 | crawler drop migration and removals |
| +7 days | 10 | trigger and old images deleted |

Nine working days plus a week of observation before step 9, matching the
8–9 in SPLITTING_ENRICHMENT §10 with the datadesk work counted honestly:
§10 there called it "two queries"; §7.6 here shows it is ten modules and
fourteen test files, absorbed by the day previously reserved for
"running both paths", which the suspended CronJob makes unnecessary.

---

## 10. Not in this work

- `datasets.metadata.enrichment_profile` keys (`metadata_presets`,
  `steady_state_since`, `version`, `scope`) as a declared shape in
  `lnic-contracts`. Read by enrichment, edited by hand today; a contract
  when datadesk's dataset page writes it.
- Datadesk's `tests/conftest.py` adopting `crawler_schema.ddl()`.
- Automated contract-bump pull requests across the three consumers.
- An index for the `review_decided` lateral scan, until measured.
- `mizzou_user`'s remaining privileges on the five tables: it stays able
  to read and write them; the crawler test in §7.5 is the guard, not a
  REVOKE. A REVOKE follows once the migration job and every manual
  runbook use `enrichment_rw`.
