# Splitting enrichment into its own repository

What it would cost, what it would risk, and what has to be true first.
Measured against the tree on 2026-09-05.

The question is a repository split, not a service split: discovery,
collection and extraction stay in this repository; enrichment moves to
a second one, developed semi-separately and run as an independent
service against the same database.

---

## 1. The short answer

**Effort: 8–9 working days.** The code that moves is 1,951 lines that
already import nothing from the rest of the tree, already own their own
tables, and already run as their own image and CronJob. What costs is
the second delivery pipeline and moving three columns.

**Risk: low once one column stops being shared.** Enrichment writes
`articles.status`, `articles.enriched_at` and
`articles.enrichment_attempts`. Those three columns are the whole
coupling. Moved into `article_enrichment`, enrichment never writes a
table it does not own, and the drift that a split would otherwise
introduce has nowhere to happen.

**It is not blocked on the NLP stack.** Enrichment uses no torch, spaCy
or scikit-learn. It builds on `mizzou-base` today because that is the
only base there is; in its own repository it builds on `python:3.11-slim`
and §3.2 of BUILD_AND_CI_ARCHITECTURE stops being its problem.

The one precondition is the status vocabulary becoming a contract (§6),
and that is owed with or without the split: datadesk already reads and
writes `articles.status` with no contract behind it.

---

## 2. The rule the suite is built on

`lnic-contracts` holds definitions. Each repository holds its own
implementation. The test that keeps the boundary honest:

> A contracts release may require a consumer to **accept a new shape**.
> It must never require a consumer to **change behaviour**.

| Belongs in `lnic-contracts` | Stays in the owning repository |
| --- | --- |
| table shapes (`crawler-schema`) | the ORM that maps them |
| status vocabularies | the code that transitions them |
| the export row schema | the query that produces it |
| `python-checks.yml`, the coverage floor, the org ruleset | the tests and the `Makefile` |

Shared *code* in the contracts package — an ORM, a config loader, a
telemetry client — turns three repositories back into one deployable
with three checkouts: every behaviour change becomes a coordinated
release, and the package built to remove the bottleneck becomes it.
Kubernetes' `k8s.io/api` is the reference for the good version: types
only, imported by every component, no behaviour.

The second rule follows from the first. **A repository owns the tables
it writes.** It reads every other table through the declared shape and
never writes one. Datadesk already works this way against this
database; enrichment nearly does (§4).

### Why not one repository

This repository already is one: discovery, extraction and enrichment in
one 69,000-line tree, which is the tree an outside contributor cannot
approach. A monorepo isolates a contributor only after path-filtered CI,
per-package test targets and CODEOWNERS are built on top of a workspace
tool; at the suite's size that tooling is a fourth project. A separate
repository gets the same isolation from GitHub for nothing: a
contributor forks one repository, the org ruleset and the shared CI
apply, and the crawler is never in their checkout.

---

## 3. What moves

| Moves | Lines |
| --- | ---: |
| `src/enrichment/` | 1,951 |
| `src/cli/commands/enrichment.py` | 235 |
| `vendor/backfield/` (prompts and reference data) | 852 KB |
| `Dockerfile.enrichment`, `k8s/enrichment-cronjob.yaml`, `gcp/cloudbuild/cloudbuild-enrichment.yaml` | — |
| `tests/enrichment/`, `tests/cli/commands/test_enrichment_command.py`, `tests/integration/test_enrichment.py` | — |
| `alembic/versions/` — the seven migrations that create or alter enrichment's tables | — |

**What stays.** `src/ml/` (the classifier), `src/pipeline/entity_extraction.py`,
`src/services/classification_service.py` and the gazetteer commands
are older, ORM-bound, and part of the extraction pipeline's labelling
step, not of enrichment. They were counted into the earlier 5,000-line
estimate, and they are where the shared-floor cost came from. They do
not move.

---

## 4. What enrichment touches today

Measured, not assumed.

| Dependency | Finding |
| --- | --- |
| `src.models`, `src.config`, `src.telemetry`, `src.utils` | **not imported** by anything under `src/enrichment/` |
| Database access | raw SQL over a SQLAlchemy `Connection`; the CLI wrapper borrows `DatabaseManager` once, for the connection (`src/cli/commands/enrichment.py:136`) |
| torch, spaCy, scikit-learn, newspaper | none |
| Tables it writes and owns | `article_enrichment`, `article_geoids`, `article_people`, `article_places`, `article_organizations` |
| Columns it writes on a table it does not own | `articles.enrichment_attempts` (`repository.py:342`); `articles.status`, `articles.enriched_at` (`repository.py:691`) |
| Rows it reads | `articles` joined to `candidate_links`, `dataset_sources`, `datasets`, `sources` — all through the shape `lnic-contracts` already declares |
| Base image | `mizzou-base` (10 GB, carries the NLP stack it does not use) |

The runtime boundary is already a service boundary. The repository
boundary is three columns and one import away.

---

## 5. The database is one database, and each table has one writer

| Side | Writes |
| --- | --- |
| crawler | `candidate_links`, `sources`, `articles` |
| enrichment | its five tables, and — until the split — three columns of `articles` |
| datadesk | `articles.status` on review (rewinds to `paused`, `cleaned`), its own tables |

**The three columns move.** `status`, `enriched_at` and
`enrichment_attempts` become columns of `article_enrichment`, which
already holds one row per article enrichment has looked at. After the
move enrichment selects from `articles` and writes only its own tables.
`articles.status` stops at `labeled` for the crawler's purposes.

Two readers change with it:

- **The BigQuery scheduled query** (outside the repository) whose inner
  filter is `status IN ('enriched', 'enrichment_skipped')` joins
  `article_enrichment` for the same filter. One config change.
- **Datadesk** reads `enriched` / `enrichment_skipped` counts for the
  dashboard and costs pages; the queries join `article_enrichment`. Its
  review rewinds already write only crawler statuses and do not change.

**Migrations have one owner per table.** The seven enrichment
migrations move to the new repository as the start of its own alembic
chain with its own version table. `alembic/` here keeps `articles`, and
a column enrichment wants on `articles` is a pull request against this
repository — which, after the move, it has no reason to want.

A local end-to-end run is two checkouts pointed at one Postgres. Each
repository's compose file already takes a DSN.

---

## 6. The status vocabulary is already a cross-repository fact

`articles.status` is the pipeline's state machine, and three
repositories touch it today with nothing but convention holding the
words together:

| Repository | Reads | Writes |
| --- | --- | --- |
| crawler | everything | `extracted`, `cleaned`, `labeled`, `paused`, `wire`, `obituary`, `opinion`, `weather`, `paywall`, `out_of_scope` … |
| enrichment | `labeled` | `enriched`, `enrichment_skipped` |
| datadesk | `enriched`, `enrichment_skipped`, `labeled`, `cleaned`, `paused` | `paused`, `cleaned` (review rewinds) |

A status renamed on one side is invisible until an article lands in a
state the other does not service — out of the pipeline, out of the
export, with nothing raising it. This is the exact failure
`lnic-contracts` was created for, where a key renamed in
`articles.metadata.review` stranded held articles with no import error
to catch it.

The vocabulary moves into `lnic-contracts` as a declared enumeration.
Each repository gains one test: every status it writes is in the
contract, and every status it reads is one it handles. This is owed
today; the split only makes the third writer a third repository.

---

## 7. What has to be true first

| Precondition | State |
| --- | --- |
| Status vocabulary in `lnic-contracts`, asserted by crawler and datadesk | not done — the one real gate |
| Shared CI (`ci-v1`) so the new repository inherits the pattern | **done 2026-09-05** |
| Org ruleset so the new repository inherits the merge rules | **done 2026-09-05** |

Two items that the earlier assessment listed as blockers are not:

- **NLP out of `base`** (§3.2). Enrichment leaves `base` by leaving the
  repository. The crawler's own image size is §3.2's problem and is
  unchanged by the split either way.
- **Automated contract bump PRs.** Worth doing — three consumers bumped
  by hand is worse than two — but the split does not depend on it. A
  status vocabulary changes rarely; a table shape changes when a column
  is added, which the current hand bump already handles.

---

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| The scheduled query or a datadesk page still filters `articles.status` for enrichment states after the columns move | grep for the two words across all three repositories before the migration; the contract test in §6 catches a read of a status no longer written |
| Migration head conflicts against one database | one owner per table; separate version tables; the enrichment chain starts from its own base revision |
| A second deploy pipeline to keep current | a copy of a pattern proven three times; `image-tag` and `python-checks.yml` are shared |
| Reprocessing: something rewinds `article_enrichment.status` and enrichment must notice | unchanged — reprocessing is already keyed on the status alone (`repository.py:45`) |
| Version lockstep across three consumers, done by hand | tolerable at the rate contracts changes; automate when it hurts |

---

## 9. What it buys

- **Enrichment stops paying for the NLP stack.** Its image goes from
  10 GB to a few hundred MB, and rebuilds in seconds.
- **The two release on their own cadence.** A change to the geocoding
  ladder does not rebuild the crawler; a change to the fetch path does
  not rebuild enrichment.
- **A contributor can hold the whole repository in their head.** Two
  thousand lines with one entrypoint, one table family and one external
  API, instead of 69,000.
- **The boundary gets tested.** Today the seam is a CLI import; after
  the split it is a declared vocabulary with a test on both sides.
- **No repository writes another's table.** The rule datadesk already
  keeps becomes the rule everywhere.

---

## 10. Effort, itemised

| Work | Estimate |
| --- | --- |
| Move `src/enrichment/`, the CLI verb, vendored backfield and tests; open the connection from a DSN instead of `DatabaseManager` | 1 day |
| Migration: three columns into `article_enrichment`; backfill; drop from `articles`; the scheduled query and datadesk's two queries join | 2 days |
| Status vocabulary into `lnic-contracts`, with the assertion in each of the three repositories | 1 day |
| New repository: `python-checks.yml`, per-repo ruleset, `Dockerfile` on `python:3.11-slim`, Cloud Build trigger, deploy workflow | 2 days |
| Enrichment's alembic chain and version table, proven against a restored copy | 1 day |
| k8s: CronJob and `versions.env` move; the crawler's image chain drops `enrichment` | 0.5 day |
| Documentation, and running both paths for a week before retiring the old one | 1–1.5 days |

**Total: 8–9 working days.** The earlier estimate of 15–16 assumed the
ORM, config and telemetry would move into `lnic-contracts`; that was
both the wrong pattern (§2) and, measured, unnecessary (§4).
