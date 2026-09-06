# Splitting analysis and enrichment into their own repository

What it would cost, what it would risk, and what has to be true first.
Measured against the tree on 2026-09-05.

The question is a repository split, not a service split: discovery,
collection and extraction stay in this repository; CIN classification,
entity extraction and enrichment move to a second one, developed
semi-separately and run as independent services against the same
database.

---

## 1. The short answer

**Effort: two to three weeks of focused work, most of it not the move.**
The code that moves is small — about 5,000 of 69,000 lines. What costs
is the shared floor underneath it and the second delivery pipeline it
needs.

**Risk: moderate, and concentrated in one place.** Both repositories
would write `articles.status`, and a status vocabulary that drifts
strands rows in a state neither side services. Everything else is
plumbing with known shapes.

**It is not blocked on the split being hard.** It is blocked on two
things this repository has not finished: the NLP stack still sits in
`base` where both sides pay for it, and a contract release still has to
be bumped by hand in each consumer.

---

## 2. What actually moves

| Moves | Lines |
| --- | ---: |
| `src/enrichment/` | 1,951 |
| `src/ml/` (the classifier) | 315 |
| `src/pipeline/entity_extraction.py` | — |
| `src/services/classification_service.py` | — |
| `src/utils/gazetteer_names.py`, geocode cache | — |
| `vendor/backfield/` | 852 KB, vendored |
| `src/cli/commands/{enrichment,entity_extraction,gazetteer,analysis}.py` | — |
| 47 test files of 388 | — |

Roughly 5,000 lines of source and an eighth of the test suite. For
comparison, `src/crawler/` alone is 17,437 lines and `src/utils/`
21,357.

**The runtime boundary already exists.** `Dockerfile.enrichment` builds
its own image, `k8s/enrichment-cronjob.yaml` runs it as its own CronJob,
and its entrypoint is one CLI verb (`enrich run --dataset …`). Nothing
in the crawler's request path calls into enrichment; the coupling is a
CLI import, not a function call in a hot loop.

---

## 3. What is shared, and what that costs

The move is small. The floor underneath it is not.

| Shared today | Lines | What the second repository needs |
| --- | ---: | --- |
| `src/models/` — the ORM, one definition of every table | 4,550 | a package, or a duplicate that drifts |
| `src/config.py` | 225 | the same |
| `src/telemetry/`, `src/utils/telemetry.py` | ~2,400 | the same |
| `src/utils/` odds — confidence, logging, metrics, process tracking | ~1,500 | the same |
| `alembic/` — 63 migrations, one head | — | see §4 |

Three ways to handle it, and only one is honest:

1. **Duplicate.** Cheapest today, and the drift is guaranteed: two ORM
   definitions of `articles` diverge the first time a column is added.
2. **Talk over an API.** Correct in the long run, wrong now: enrichment
   reads whole article bodies in batches, and an HTTP hop per article
   changes the cost profile of a job that already runs for hours.
3. **Grow `lnic-contracts` to carry the shared floor.** The package
   already exists for exactly this reason, already holds a shape both
   sides read, and already ships to three consumers. This is the answer,
   and it is most of the work.

---

## 4. The database is one database

Both sides write the same rows.

| Side | Writes |
| --- | --- |
| crawler | `candidate_links`, `sources`, `articles` (through extraction) |
| enrichment | `article_enrichment`, `article_geoids`, `article_people`, `article_places`, `article_organizations`, and **`articles.status`** |

A repository boundary does not make a service boundary. The two will go
on sharing a database, which is the same constraint the sources
migration works under: they cannot join across databases, so the split
must not assume they can.

**Migrations need an owner.** 63 migrations, one head. The enrichment
tables were created by six of them. After a split, either the crawler
keeps `alembic/` and the second repository asks it for schema changes —
slow, and the wrong repository reviews them — or the second repository
runs its own chain with its own version table against the same database,
which works and needs a rule about who may touch `articles`.

Recommended: the second repository owns the tables only it writes, with
its own alembic version table. `articles` stays here, and a column
enrichment needs is a pull request against this repository.

---

## 5. What has to be true first

| Blocked on | Why | State |
| --- | --- | --- |
| NLP out of `base` (§3.2 of BUILD_AND_CI_ARCHITECTURE) | after the split the crawler should not carry spacy/torch, which is only true if the base image stops carrying them | not done |
| The contract release opens the bump PR in each consumer | two consumers already have to be bumped by hand in lockstep; a third makes it worse | not done |
| Shared CI (`ci-v1`) | a new repository gets the pattern for free | **done 2026-09-05** |
| The status vocabulary is a contract, not a convention | see §6 | not done |

---

## 6. The risk that matters

**Two repositories writing one status column.**

`articles.status` is the pipeline's state machine. Extraction writes
`extracted`, `cleaned`, `paused`; enrichment writes `enriched`,
`enrichment_skipped`, and reads `labeled`. The values are agreed by
nothing but the fact that both sides are in one tree and one test suite.

Split them, and a status renamed on one side is invisible until an
article lands in a state the other does not service — out of the
pipeline, out of the export, with nothing raising it. This is not
hypothetical: it is the exact failure `lnic-contracts` was created for,
where a key renamed in `articles.metadata.review` stranded held articles
with no import error to catch it.

Mitigation, and it is the price of the split: the statuses move into
`lnic-contracts` as a declared vocabulary both sides import, with a test
in each repository asserting that every status it writes is in the
contract and every status it reads is handled.

### The rest, in order of how much they would hurt

| Risk | Mitigation |
| --- | --- |
| Version lockstep across three repositories, done by hand | automate the bump PR before the split, not after |
| Migration head conflicts against one database | one owner per table; separate version tables |
| A local end-to-end run needs two checkouts and one database | a compose file in each that points at the same Postgres, and a documented order |
| The gazetteer and geocode cache are read by both sides | they belong with enrichment; the crawler's use is a report, which can move or read the table |
| Coverage floor per repository | the floor is one number in `lnic-contracts` already; a new repository inherits it |
| Two deploy pipelines to keep current | the second is a copy of a pattern now proven three times; the `image-tag` action and `python-checks.yml` are shared |

---

## 7. What it buys

- **The NLP stack stops being everybody's cost.** `ml-base` is 10 GB and
  the processor image 9.99 GB; extraction does not need any of it.
- **The two can be released on their own cadence.** A change to the
  geocoding ladder does not rebuild the crawler; a change to the fetch
  path does not rebuild the classifier.
- **A second team can work without merge collisions** in a 69,000-line
  tree where the two halves already do not call each other.
- **The boundary gets tested.** Today the seam between extraction and
  enrichment is an import; after the split it is a contract with a test
  on both sides, which is the thing that catches a rename before it
  strands rows.

---

## 8. Effort, itemised

| Work | Estimate |
| --- | --- |
| Move the code and its tests; fix imports | 2 days |
| Shared floor into `lnic-contracts` (models, config, telemetry) and pinned in both | 4–5 days |
| Statuses into the contract, with the assertions in both repositories | 2 days |
| Alembic ownership: split the chain, prove it against a restored copy | 2 days |
| New repository's CI, image chain, Cloud Build triggers, deploy workflow | 2 days |
| k8s: move the CronJob, the Argo template reference, versions.env | 1 day |
| Documentation, and a week of running both before retiring the old path | 2 days |

**Total: 15–16 working days**, of which the actual move is two.

The estimate assumes the two blockers in §5 are cleared first. Attempted
before them, the same work costs closer to four weeks and lands a
crawler image that still carries torch.
