# Backfield enrichment before BigQuery export

Proposal for a final pipeline stage that extracts places, people, organizations
and article metadata using [backfield](https://github.com/localangle/backfield),
writing to the crawler's own database. Results reach BigQuery through per-table
scheduled queries, alongside the four that exist today.

Every figure below was measured on 20 August 2026 — against the production
database, and by running backfield's nodes on 100 real articles. Nothing here is
a vendor claim or an estimate where a measurement was possible.

---

## 1. Where it fits

```
discover → extract → clean → wire check → CIN label → ENRICH → scheduled sync → BigQuery
                                              ↓                    ↓
                                     status='labeled'      status='enriched'
                                     (candidate)           (exportable)
```

**The export criterion changes.** The deployed mechanism (verified 2026-08-20)
is a BigQuery scheduled query, "Sync Articles from Cloud SQL", running daily at
07:00 UTC as a full refresh with the filter `status = 'labeled'` — the
`wire_check_status` condition appearing in code comments is not in the deployed
query. The filter becomes:

```sql
status IN ('enriched', 'enrichment_skipped')
```

Enrichment stops being an optional trailer on the pipeline and becomes the last
required step. `labeled` becomes a candidate state, not an exportable one.

The stage selects its work as:

```sql
status = 'labeled' AND wire_check_status = 'complete'
```

### Status vocabulary

`enriched` means backfield ran; it does not mean eligible for export. Conflating
the two leaves the corpus unable to distinguish enriched articles from skipped
ones once dataset profiles differ.

| Status | Set when | Exports | Terminal |
|---|---|---|---|
| `labeled` | Candidate, or enrichment failed and will retry | No | No |
| `enriched` | Backfield ran every step the dataset's profile asked for | **Yes** | Yes |
| `enrichment_skipped` | No backfield call was made — see `skip_reason` | **Yes** | Yes |
| `not_article`, `paywall` | Content gate rejected the text | No | Yes |
| `out_of_scope` | Scope is in the dataset's `export_exclude_scopes` | No | Yes — reprocessable on a profile bump |

A dataset running *some* enrichments still yields `enriched`; the steps actually
applied are recorded on the row (§7). Only a complete absence of backfield work
yields `enrichment_skipped`, with the reason recorded:

| `skip_reason` | Meaning |
|---|---|
| `profile_none` | The dataset asked for no enrichment |
| `dataset_disabled` | Enrichment is off for this dataset entirely |
| `operator_bypass` | Released by hand during an outage — see §10 |
| `failed_max_attempts` | Enrichment failed repeatedly; released so it still exports |

Two of these are policy and two are incidents. The distinction must survive in
the data: a period of `operator_bypass` articles is a gap that has to be
identifiable later without reference to deploy logs.

Consequences:

- **Junk cannot export.** An article rejected by the content gate in §3 takes a
  terminal `not_article` or `paywall` status, which is in neither exportable
  state, whatever CIN label it was given.
- **The sync is a full refresh**, so a status change takes effect at the next
  07:00 run — including removal. This is why reprocessing must never reset
  status (§8), and why the criterion is widened before the first enrichment run
  (implementation spec, Phase 2). The cookie-text defect closes by construction rather than by adding a
  check earlier in the pipeline.
- **Enrichment failure withholds export.** An article that errors stays at
  `labeled` and does not appear in BigQuery until it succeeds. This is the
  intended behaviour, and it makes the enrichment backlog an export backlog —
  see §10.
- **The existing gate stays as the entry condition.** Nothing that fails wire
  checking or labelling becomes a candidate in the first place.

**Scope is the `Mizzou-Missouri-State` dataset.** The other datasets in the
database (VT Community News, WSU Washington State) are out of scope for this
proposal; including them would add roughly 3,700 articles.

| | Count |
|---|---|
| Mizzou articles, all statuses | 159,932 |
| At `status='labeled'` | 100,257 |
| **Qualifying for export** | **99,418** |

Qualifying articles per month, by publish date:

| Month | Qualifying |
|---|---|
| 2026-01 | 12,120 |
| 2026-02 | 13,283 |
| 2026-03 | 17,441 |
| 2026-04 | 5,185 |
| 2026-05 | 1,042 |
| 2026-06 | 2,754 |
| 2026-07 | 5,308 |

The spread is crawler throughput, not seasonality — extraction has been stopped
for parts of this period. Plan against the busy months: **12,000–17,500**.

### Two input modes

**Steady state is the primary mode.** Every article collected from here on passes
through this stage before export. The recurring figures in §4 and §5 are the ones
that govern the decision; the backfill is a one-off.

**Backfill takes an explicit article list.** The set is supplied as article ids,
not derived from a date range. March 2026 is the working scale — 17,441 articles
qualify, and the list is expected to be roughly 15,000 — but selection is not a
`publish_date` predicate and should not be implemented as one.

| Mode | Selection |
|---|---|
| Steady state | The candidate query, on a schedule |
| Backfill | A supplied list of article ids |

A supplied list is a selection, not an override. Listed articles pass through the
same content gate and the same dataset profile as any other: an article on the
list that is cookie text is still rejected, and one whose dataset profile is
`none` is still skipped. The list decides *which* articles are considered, not
*what happens to them*.

Ids on the list that are not candidates — already enriched, never labelled, wire
— are reported and skipped rather than silently dropped, so a list of 15,000 that
processes 12,000 says why.

The remaining historical articles are out of scope for now and require no rework
to add later: candidacy is the version comparison in §8, and nothing already
processed is re-billed.

Enrichment adds no new *entry* rule — everything that qualifies today becomes a
candidate. What it adds is an exit rule: an article exports when it has been
enriched, or not at all.

## 2. Why backfield runs as a library, not a platform

Backfield ships nine Compose services and states that production self-hosting
from its checkout is unsupported. None of that is required here. Its extraction
nodes are ordinary functions:

```python
run_article_metadata(params, inputs) -> dict
run_place_extract(params, inputs)    -> dict
run_person_extract(params, inputs)   -> dict
run_organization_extract(params, inputs) -> dict
```

`default_context()` reads three environment variables and opens no database. The
model is a plain parameter, so `openrouter/deepseek/deepseek-v3.2` is passed per
call. `db_output` is a separate node we do not call — results are written to our
own tables.

Consequences: **no backfield Postgres, no PostGIS, no pgvector, no Redis, no
Celery, no APIs, no UIs.** One container image, one job.

### The extension that would have forced a self-managed database

Backfield's schema requires `postgis`, `vector`, `pg_trgm` and `h3`. Checked
against `mizzou-db-prod`:

```
postgis   3.6.0   available
vector    0.8.5   available
pg_trgm   1.6     available
h3        —       not available on Cloud SQL
```

This does not affect us, because h3 is only used by SQL in backfield's public
geo-cell browsing endpoints, which we do not run. Writing h3 cells happens in
Python into plain text columns. Recorded here because it does block adopting
backfield's own schema on Cloud SQL, should that ever be proposed.

## 3. Order of operations, and why

The stage is ordered so that the cheapest call can prevent the most expensive
one. Measured on the 100-article sample.

| Step | Runs on | Calls | Purpose |
|---|---|---|---|
| 0a. Boilerplate heuristic | every article | 0 | Free; rejects text that is plainly not a story |
| 0b. Content gate | survivors | 1 (truncated) | Rejects what the heuristic misses |
| 1. `geographic_scope` | real stories only | 1 | Decides whether a point location is meaningful at all |
| 2. `place_extract` | point-scope articles only (46%) | 1 | Mentions, with parsed components |
| 3. Resolve the point | point-scope articles | 0 | Single city, else the publication's city — see below |
| 4. `geocode_agent` | unresolved POI-level only (~8%) | many | Backfield's agentic geocoder |
| 5. Remaining metadata presets | every article | 5 | subject, topic, format, timeframe, user need |
| 6. `person_extract`, `organization_extract` | every article | 2 | People with quotes; organizations |

**Step 1 before step 2 is the main saving.** Scope costs one call and excludes
54% of articles from place extraction entirely.

### Step 0: reject text that is not a story

Articles that are entirely cookie notices, consent tables or paywall furniture
still reach `status='labeled'` despite the boilerplate work already done. One
appeared in the 100-article sample:

```
KQTV — "Taylor Crouse", 27,372 characters of cookie descriptions

  our label       Civic information      confidence 0.429
  our alternate   Economic Development   confidence 0.228
  status          labeled  -> exportable to BigQuery
  locations extracted by backfield: 0
  cost to process: $0.018, or 2.6x a typical article

  backfield's rationale, unprompted:
  "The provided text is not a news article; it is a list of website
   cookie descriptions and technical settings."
```

This is a labelling defect. The text contains no story, so no CIN label
describes it. The classifier produced one at 0.429 confidence and the article was
promoted to `status='labeled'`. Two gaps produce this: no check that the text is
a story, and no confidence floor on the promotion.

Two layers, cheapest first:

**0a. A deterministic heuristic, free.** Density of cookie, consent, privacy
policy, vendor list and advertising-partner terms. Five or more occurrences
identified exactly the one junk article in the sample and nothing else. Tuned in
Phase 0 on an unbiased 300-article sample: **no article scored ≥5** (290 scored
zero), and the gray zone proves the threshold — *"Oreo bringing zero-sugar
cookies to US"* and a donor-consent bill each score 4 on literal term matches. A
lower threshold rejects real news; 5 stands. Corpus junk rate is **under 0.3%**,
confirming the length-biased 1-in-100 overstated it.

**0b. A truncated LLM gate for what the heuristic misses.** The call sends **two
800-character windows — the head and the middle of the document** — not the whole
article (~550 input tokens, ~$0.0002). Head-only sampling was tested first and
rejected: cleaning residue concentrates at the top, and a head-only gate
misclassified a known-good article whose stored text opens with a cookie banner.

The verdict is **"is a story present in either window?"**, stated in the prompt
explicitly: furniture around a story does not change the verdict. Measured on an
adversarial 11-article set (8 heuristic gray-zone, the known-bad cookie article,
2 clean controls): 10 of 11 correct, including *"Oreo bringing zero-sugar
cookies"* passed and the cookie-text article rejected. The one miss is the known
limitation: a vox-pop piece that is mostly furniture with a fragment of quotes
read as paywall.

Rejected articles are flagged and skip every subsequent step.

Measured frequency was 1 in 100, on a sample drawn from articles at or above
median length. Junk of this kind is long, so the corpus rate is likely lower. The
gate costs roughly $1.50 per 15,000 articles and saves a comparable amount; the
cost case is neutral. The two operative reasons:

- **Label correctness.** A CIN label on text containing no story is wrong, and it
  is currently indistinguishable in BigQuery from a label on a real article. It
  contaminates coverage statistics and any analysis built on them.
- **Regression detection.** The rejection rate is a monitor on the boilerplate
  stripping. A sudden rise means cleaning has broken upstream, and that is worth
  knowing on the day it happens rather than in a quarterly review.

This overlaps existing statuses — `not_article` (1,051) and `paywall` (2,161)
already exist — so the gate should feed the same vocabulary rather than invent a
parallel one.

### Where the gate belongs, given the new export criterion

Inside this stage. Because export requires `enriched`, an article the gate
rejects never exports regardless of the label it carries, so the defect is closed
without touching the labelling step.

One related change remains worth considering separately: **a confidence floor on
CIN labelling**. The cookie article was labelled `Civic information` at 0.429 and
promoted to `labeled` with nothing objecting. That wrong label will no longer
reach BigQuery, but it is still wrong, still stored, and still visible to anyone
reading the database directly.

```
city_municipality        40      regional      17      statewide     12
neighborhood_community    6      national      10      international  2
                                 other         13
```

A story spanning three counties is `regional`. It should not receive a pin, and
under this order it never enters the geocoding path.

### Step 3 resolves most points for nothing

`place_extract` returns every mention — a mean of **6.5 locations per article**,
648 across the sample. Only 27 articles mention exactly one city, so extraction
alone does not identify where a story happened.

Two rules, applied in order, need no API and no model:

1. If the article mentions exactly one city, use it.
2. Otherwise use the **publication's city** from `sources.city`, when it appears
   among the mentions.

Measured on the 46 point-scope articles:

```
publication city among the extracted mentions   34
publication city not among them                 11
no publication city on record                    1

resolved to a single point                      38 of 46
still ambiguous                                  8 of 46
```

**38% of articles get a defensible point with no geocoding service and no extra
model call.** City-level points then resolve to coordinates from a GNIS or Census
gazetteer file held locally — exact, free, no rate limit. The same GNIS file is
already loaded for the LNIC source directory.

### Step 4 is the expensive one, which is why it is last and narrow

Backfield's geocoder runs **four LLM models per location** — evaluation,
geographic reasoning, geographic estimation, and a router — plus a geocoder API.
It supports Pelias (Geocode Earth) and Geocodio; Nominatim is wired only for
natural features such as rivers and parks, so it cannot stand in.

Under this design it runs on roughly 8% of articles, for POI- and street-level
locations the free rules could not resolve. At that volume a Geocodio key at
$0.50/1,000 costs single-digit dollars per month. Without the scope gate it would
run on roughly 646,000 locations for the backfill.

## 4. Cost

Measured per call, reading token counts off the responses on articles at or above
the corpus median length:

```
mean per metadata call    2,693 input, 113 output tokens
cost per call             $0.00078   (DeepSeek V3.1 rates: $0.25/M in, $0.95/M out)
```

| | Per article |
|---|---|
| Content gate, truncated input | $0.0001 |
| `geographic_scope` | $0.0008 |
| Metadata, 5 remaining presets | $0.0039 |
| `place_extract` on 46% of articles | $0.0004 |
| `person_extract` + `organization_extract` | $0.0016 |
| Geocoding on ~8% | <$0.0002 |
| **Total** | **≈$0.0067–0.0075** |

`information_needs` is **not** in this total. Our CIN classifier remains
authoritative and backfield's runs only in development — see §9.

| | |
|---|---|
| **Backfill, a ~15,000-article list** | **$100–113** one-time |
| Ongoing, busy month (12,000–17,500) | **$80–131** |
| Ongoing, slow month (1,000–5,300) | **$7–40** |
| For reference: all 99,418 historical | $666–745, not planned |

The backfill costs about the same as one busy month. Since every article
collected from here on passes through this stage, the recurring figure is the one
that governs the decision.

Both levers were measured in Phase 0 (2026-08-21):

- **Prompt caching: active with no code change.** The presets already place
  `{text}` last, and DeepSeek caches the ~1,900-token prefix automatically
  through OpenRouter. Measured: warm calls report `cached_tokens=1856–1920` and
  cost **$0.0002–0.0004 against the $0.00078 cold baseline**; hit rate ~80%
  within a burst (a call routed to a cold replica misses). Effective per-article
  cost is therefore below the table above, which stands as the no-cache bound.
- **Preset consolidation: dropped.** One combined call against six separate
  calls on the same 100 articles agreed only **71–84% per dimension**
  (subject 75%, topic 78%, format 84%, temporal 76%, user_need 71%, scope 72%).
  That is a different classifier, not a cost optimisation. Per the phase rule it
  is dropped and not revisited. For reference, the combined call cost
  $0.0006/article.

## 5. Time

Measured throughput at 10 concurrent workers:

```
7 metadata presets   100 articles in 28s per preset
place_extract        100 articles in 122s
```

A full 9–10 call pipeline is roughly 3 seconds per article at that concurrency.

| | At 10 workers | At 50 workers |
|---|---|---|
| **Backfill, a ~15,000-article list** | **~12 hours** | **~2.5 hours** |
| Busy month, incremental (~580/day) | ~27 minutes/day | — |
| For reference: all 99,418 | ~3.2 days | ~15 hours |

A March-only backfill is a single overnight run at modest concurrency. It does not
need the higher concurrency tier, and it does not need to survive a multi-day
window — which removes most of the operational risk from the first real run.

The job is I/O-bound on the API, not CPU-bound, so one or two existing spot nodes
are sufficient. Concurrency is limited by OpenRouter rate limits, not by us.

## 6. Containerisation and resource footprint

| | |
|---|---|
| Compute | Kubernetes `CronJob` on the existing `mizzou-cluster`, spot pool |
| Database | The crawler's existing Cloud SQL — new tables, no new instance |
| Secrets | OpenRouter key; a geocoder key only if step 4 is enabled |
| Redis, Celery, backfield APIs | Not used |

### Base image alignment

Backfield requires Python 3.11. `Dockerfile.base` is
`python:3.11-slim-bookworm`. They align, and the enrichment image builds from the
crawler base.

**Not from `Dockerfile.processor`.** The processor derives from the ML base and
carries spacy, transformers, scikit-learn and their model weights. Enrichment
performs no local inference — it makes HTTP calls to OpenRouter — so none of that
is reachable code. Building from the processor image would multiply the image for
no benefit.

Measured: importing the four extraction nodes pulls in `backfield_db`,
`backfield_entities`, `sqlalchemy` and `litellm`, and does **not** pull in
`torch` or `transformers`.

### What is shared and what is added

Already present in the crawler base and reused unchanged:

`sqlalchemy`, `requests`, `pydantic`, `structlog`, `psycopg2-binary`,
`cloud-sql-python-connector` — plus the crawler's own session handling, config
loading, telemetry and the `articles` model.

Added by backfield, measured from site-packages:

| Package | Size | Needed for |
|---|---|---|
| `litellm` | 84 MB | Every model call |
| `pycountry` | 22 MB | Place normalisation |
| `openai` | 10 MB | litellm provider shim |
| `anthropic` | 9 MB | litellm provider shim |
| `shapely` | 6 MB | Geometry |
| `h3`, `langgraph` | 3 MB each | Cell index; agent graph |
| `geopy`, `usaddress`, `overpy`, `us`, `duckduckgo-search`, `boto3` | 1–2 MB each | Geocoding paths |

Roughly **150 MB added** over the crawler base.

`boto3` and `duckduckgo-search` are declared dependencies of `backfield-agate`
but are reachable only from the S3 input/output nodes and web-search fallback,
which this design does not call. They are installed because they are hard
dependencies, not because they are used.

### Minimising the footprint

1. **Build from `Dockerfile.base`, not `Dockerfile.processor`.** This is the
   single largest saving and requires no other change.
2. **Multi-stage build**, copying only the finished `site-packages` into the
   runtime stage, as `Dockerfile.base` already does.
3. **Do not install `requirements-processor.txt`.** Enrichment needs no ML stack.
4. **Pin backfield to a commit**, installed as packages rather than a checkout.
5. **Import lazily where possible.** `litellm` is 84 MB and dominates both image
   size and import time.

### Runtime resources

Measured: importing the four nodes reaches **306 MB RSS** before any article is
processed, essentially all of it `litellm` and its provider shims.

| | |
|---|---|
| Memory request | 512 Mi |
| Memory limit | 1 Gi |
| CPU request | 250 m |

The work is I/O-bound on the OpenRouter API. Concurrency is achieved with threads
inside one pod rather than more pods, so a single small pod at concurrency 10–50
is the whole deployment. Scaling out costs memory per replica for no throughput
gain, since the limit is the API, not the CPU.

Spot nodes are appropriate: the job is interruptible and idempotent, and a killed
run loses only the articles in flight.

### Version pinning

Backfield is pre-1.0 and its documentation states that self-hosting is
unsupported. Pin an exact commit, treat upgrades as deliberate work, and keep the
node calls behind a thin adapter module so a breaking change touches one file.
The adapter is also the seam the tests in §11 exercise.

## 7. Per-dataset enrichment profiles

Datasets differ in what they are for. A dataset must be able to run all of the
enrichments, some of them, or none — and reach BigQuery either way. Enrichment is
a required *step*, not a required *result*.

The profile is held on the dataset, defaulted, and versioned:

```jsonc
// datasets.metadata -> "enrichment_profile"
{
  "version": 1,
  "content_gate": true,          // independently switchable, on by default
  "scope": true,
  "places": true,
  "geocode": false,              // needs a geocoder key
  "people": true,
  "organizations": true,
  "metadata_presets": ["subject", "topic", "format",
                       "temporal_orientation", "user_need"]
}
```

| Profile | Behaviour |
|---|---|
| **All** | Every step in §3 runs |
| **Some** | Only the named steps run; the rest are skipped, not failed |
| **None** | No backfield call is made; the article is marked `enrichment_skipped` with `skip_reason='profile_none'` and exports |

A `none` profile still produces an `article_enrichment` row, recording that the
profile was empty. An article must never be stranded at `labeled` because its
dataset asked for nothing.

A partial profile yields `enriched`; only the absence of any backfield call
yields `enrichment_skipped`. The criterion is whether backfield was called, so
`enriched` carries the same meaning across datasets.

### Absent and disabled are not the same

A missing place list has three possible meanings:

| | Meaning |
|---|---|
| Step disabled for the dataset | Not attempted; absence carries no information |
| Step ran, found nothing | A real, negative finding |
| Step failed | Unknown; the article should not be `enriched` at all |

Every enrichment row therefore records the profile version and the steps
actually applied, and BigQuery consumers filter on those rather than on `NULL`.
Without this, "no people were found" and "people were not extracted" are the same
query result, and any analysis spanning datasets with different profiles is
incorrect.

### The content gate is switchable

`content_gate` is separately switchable because it changes what reaches BigQuery
rather than what is known about it.

### Scope-based export exclusion, per dataset

`export_exclude_scopes` names scope categories whose articles take the terminal
status `out_of_scope` and do not export. Decided immediately after the scope
classification, so every remaining step is skipped — on the 100-article sample,
excluding `international` and `national` removes 12% of articles from both the
export and the remaining enrichment spend.

```jsonc
"export_exclude_scopes": ["international"]        // or ["international","national"]
```

Rules:

- Requires `scope`: exclusion is decided by the classification.
- The two point scopes are not excludable — local coverage is the product.
- `elsewhere_to_local` is excludable but means "external events with direct
  local impact"; excluding it drops localized national stories.
- Default is empty. A dataset that says nothing excludes nothing.
- The enrichment row still records the scope and its rationale, so the
  exclusion is auditable per article.
- Reversible: `out_of_scope` articles are reprocessing candidates on a profile
  version bump, status untouched until they are re-enriched under the new flag. A dataset running `none` exports cookie-text
articles, as happens today. That may be correct for a dataset ingested for volume
rather than analysis, but it is recorded in the profile rather than implied by
disabling enrichment.

Recommended default for a new dataset: `content_gate` on, everything else off.
Cheap, and it stops the known defect without committing to any spend.

## 8. Reprocessing: turning enrichment on later

A dataset set to `none` today must be enrichable in a month by changing the
profile, and the same must hold for articles that were bypassed during an outage
or that failed. This is a first-class requirement, not a migration script.

### Candidacy is a version comparison, not a status change

Re-queuing by setting articles back to `labeled` would stop them matching the
export filter, and the next daily full refresh would drop those rows from
BigQuery for the duration of reprocessing.

The profile therefore carries a version, each enrichment row records the version
it was produced under, and candidacy is a comparison:

```sql
-- never processed
status = 'labeled'
-- or processed under an older profile than the dataset now asks for
OR (status IN ('enriched', 'enrichment_skipped')
    AND e.profile_version < d.profile_version)
```

Status is unchanged throughout. An article remains exportable while queued,
during reprocessing, and afterwards.

### Only the delta is paid for

The enrichment row records the steps actually applied. When a profile gains a
step, the job runs **only the steps missing from that article**, not the profile
from scratch. Turning on `people` for 15,000 already-enriched articles costs one
call each, not ten.

`operator_bypass` articles are the exception: nothing ran, so everything runs.

### Cost of a change is knowable before it is made

Because steps applied are recorded per article, the delta for a proposed profile
change is a query, not a guess:

```sql
-- how many articles would a newly enabled step cost?
SELECT count(*) FROM article_enrichment e
JOIN articles a ON a.id = e.article_id
WHERE NOT ('people' = ANY(e.steps_applied))
```

A profile change should report its estimated cost and article count before it is
applied, for the same reason the job carries a spend ceiling.

## 9. Schema

New tables in the crawler database, all keyed on `article_id`. Each is synced
to BigQuery by its own scheduled query, following the four that exist — the
sync is per-table and explicit, not automatic.

All samples below are real output from
`openrouter/deepseek/deepseek-v3.2` on one article: *"Meet Diane Grimes,
candidate for Warren County Ambulance District Board of Directors"*.

### `articles` — two added columns

```sql
ALTER TABLE articles
  ADD COLUMN enriched_at        timestamp,
  ADD COLUMN enrichment_attempts smallint NOT NULL DEFAULT 0;
```

`status` gains `enriched` and `enrichment_skipped`. `enrichment_attempts` bounds
retries before `failed_max_attempts` (§10).

### `article_enrichment` — one row per article

```sql
CREATE TABLE article_enrichment (
  article_id            text PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,

  -- provenance and reprocessing control
  profile_version       integer NOT NULL,
  steps_applied         text[]  NOT NULL,
  skip_reason           text,              -- profile_none | dataset_disabled |
                                           -- operator_bypass | failed_max_attempts
  backfield_commit      text    NOT NULL,
  model                 text    NOT NULL,
  prompt_versions       jsonb   NOT NULL,
  cost_usd              numeric(10,6),
  enriched_at           timestamptz NOT NULL DEFAULT now(),

  -- content gate
  is_news_content       boolean,
  content_gate_reason   text,

  -- one column per metadata preset, each with its confidence
  scope                 text,  scope_confidence      real,
  subject               text,  subject_confidence    real,
  topic                 text,  topic_confidence      real,
  format                text,  format_confidence     real,
  timeframe             text,  timeframe_confidence  real,
  user_need             text,  user_need_confidence  real,
  rationales            jsonb,             -- preset -> rationale text

  -- resolved location, when scope is point-level
  point_place           text,
  point_method          text,              -- single_city | publication_city | geocoded
  point_lat             double precision,
  point_lon             double precision,
  point_gnis            text
);
CREATE INDEX ON article_enrichment USING gin (steps_applied);
CREATE INDEX ON article_enrichment (profile_version);
```

Sample values:

| Column | Value |
|---|---|
| `scope` | `city_municipality` |
| `subject` | `election` (0.95) |
| `topic` | `local_government_politics` (0.95) |
| `format` | `profile` (0.95) |
| `timeframe` | `future` (0.90) |
| `user_need` | `show_me_the_community` (0.85) |
| `steps_applied` | `{content_gate,scope,places,people,organizations,subject,topic,format,timeframe,user_need}` |
| `point_method` | `publication_city` |

### `article_places` — one row per extracted location

```sql
CREATE TABLE article_places (
  id            bigserial PRIMARY KEY,
  article_id    text NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  full_name     text,
  place_type    text,          -- city | place | street_road | county | state | ...
  city          text,
  county        text,
  state         text,
  address       text,
  description   text,          -- why the place is in the story
  mention_text  text,          -- the sentence it came from
  is_point      boolean,       -- did this become the article's resolved point
  lat           double precision,
  lon           double precision,
  geocoder      text
);
CREATE INDEX ON article_places (article_id);
CREATE INDEX ON article_places (city, state);
```

Sample row:

```json
{
  "full_name": "Warrenton, MO",
  "place_type": "city",
  "city": "Warrenton",
  "state": "MO",
  "description": "City where the Warren County Ambulance District is based.",
  "mention_text": "Warren County Ambulance District Board of Directors",
  "is_point": true
}
```

A mean of **6.5 rows per article** (648 across the 100-article sample). Most
articles produce several; 11 of 100 produced none.

### `article_people` — one row per person

```sql
CREATE TABLE article_people (
  id            bigserial PRIMARY KEY,
  article_id    text NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  name          text NOT NULL,
  sort_key      text,
  title         text,
  affiliation   text,
  person_type   text,          -- elected_official | resident | expert | ...
  role_in_story text,
  nature        text,          -- subject | source | mentioned
  public_figure boolean,
  mention_count integer,
  quotes        jsonb          -- quoted passages attributed to this person
);
CREATE INDEX ON article_people (article_id);
CREATE INDEX ON article_people (sort_key);
```

Sample row:

```json
{
  "name": "Diane Grimes",
  "sort_key": "grimes",
  "title": "Finance administrator/business owner",
  "person_type": "elected_official",
  "role_in_story": "Candidate for Warren County Ambulance District Board of Directors",
  "nature": "subject",
  "public_figure": false
}
```

### `article_organizations` — one row per organization

```sql
CREATE TABLE article_organizations (
  id            bigserial PRIMARY KEY,
  article_id    text NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  name          text NOT NULL,
  org_type      text,          -- public_services | business | nonprofit | ...
  boundary      text,
  role_in_story text,
  nature        text,
  mention_count integer
);
CREATE INDEX ON article_organizations (article_id);
```

Sample row:

```json
{
  "name": "Warren County Ambulance District",
  "org_type": "public_services",
  "role_in_story": "Governing body for ambulance services in the county",
  "nature": "subject"
}
```

### Notes on the shape

- `sort_key` and `name` are the join keys a future canonicalization step would
  use. Storing them now costs nothing and avoids reprocessing later.
- `quotes` is `jsonb` rather than a table because quotes are only ever read with
  their person.
- Confidence is stored for every classification. Nothing downstream currently
  filters on it, but the cookie-text defect (§3) is the argument for keeping it.
- No embeddings. `pgvector` is available on Cloud SQL if that changes.

| Table | Grain |
|---|---|
| `article_enrichment` | One row per article: scope, subject, topic, format, timeframe, user need, resolved point, **`profile_version`, `steps_applied` (array, indexed), `skip_reason`**, model and prompt versions, cost, `enriched_at` |
| `article_places` | One row per extracted location, with components, resolution method, and coordinates when resolved |
| `article_people` | One row per person mention, with quotes |
| `article_organizations` | One row per organization mention |

Every row records the model id, the backfield commit, and the prompt preset
version, so a reprocessing decision can be scoped to exactly what changed.

Idempotency comes from the candidate query: only `labeled` articles are picked
up, so anything already `enriched` or `enrichment_skipped` is never re-billed. `enriched_at` records when, and the
recorded model and prompt versions scope any future reprocessing.

## 10. Failure handling

Because export now depends on this stage, its failure modes are export failure
modes.

- One article failing must not fail a batch. Errors are recorded per article with
  the exception type and the step that failed; the article stays at `labeled` and
  is retried on the next run.
- A batch is committed per article, not per run, so a job killed mid-way loses
  nothing already paid for.
- Cost is recorded per article. A daily spend ceiling stops the job rather than
  discovering the overrun on an invoice.
- **Failure and rejection must be distinguishable.** An article rejected as not
  being a story is terminal and should take the existing `not_article` or
  `paywall` status. An article that failed a call is transient and stays at
  `labeled` for retry. Collapsing the two either loses junk into the retry queue
  forever or silently discards real stories.
- **The backlog is now visible or it is invisible.** Articles stuck at `labeled`
  are articles missing from BigQuery. This needs an alert on the age of the
  oldest unenriched candidate, not a dashboard nobody opens. An OpenRouter outage,
  a rate-limit change or an expired key now stops the export feed, which was not
  true before.
- **A permanently failing article must not be withheld forever.** After a bounded
  number of attempts it takes `enrichment_skipped` with
  `skip_reason='failed_max_attempts'`, so it exports and remains a candidate for
  reprocessing under §8. Without this, one article backfield cannot parse is one
  article BigQuery never sees, and nobody finds out.
- **A bypass is required.** If enrichment is broken or too expensive to run,
  there must be a supported way to release `labeled` articles without enriching
  them. That path sets `enrichment_skipped` with
  `skip_reason='operator_bypass'`, never `enriched`, so an outage is later
  distinguishable from a policy decision and from real enrichment.

## 11. Testing

The adapter module is the seam. Backfield's nodes are third-party code and are
not retested here; what is tested is our use of them, our decisions, and our
writes.

### Unit tests — no database, no network

Model calls are stubbed with recorded fixtures captured from real runs.

| Area | Assertions |
|---|---|
| Profile resolution | All / some / none produce the right step list; unknown keys rejected; missing profile falls back to the default |
| Status transitions | Full profile → `enriched`; empty profile → `enrichment_skipped` + `profile_none`; gate rejection → `not_article`; call failure → stays `labeled` and increments attempts; attempts exhausted → `enrichment_skipped` + `failed_max_attempts` |
| Point resolution | One city → that city; several cities + publication city among them → publication city; several cities without it → unresolved; zero cities → unresolved |
| Scope gating | `regional`, `statewide`, `national`, `international`, `other` never reach place extraction |
| Content gate | Cookie-text fixture rejected; a normal article passes; the gate reads only the truncated prefix |
| Reprocessing candidacy | Older `profile_version` selects; equal does not; `steps_applied` yields only the missing steps |
| Response parsing | Malformed JSON, absent `category`, confidence out of range, and unexpected category values all fail the article rather than writing a bad row |
| Cost accounting | Recorded cost matches token counts; the ceiling halts the run |

Point resolution and status transitions carry the most consequence and no
external dependency, so they should be table-driven with the real cases from the
100-article sample as fixtures.

### Integration tests — real Postgres, stubbed models

Run against the existing test Postgres, in the pattern already used by the
crawler suite.

| Area | Assertions |
|---|---|
| Writes | All four tables populate; `article_places` yields multiple rows for one article; cascade delete removes children |
| Idempotency | A second run selects nothing and writes nothing |
| Export criterion | Only `enriched` and `enrichment_skipped` match; `labeled` and `not_article` do not |
| **Reprocessing does not withdraw rows** | An article exportable before a profile bump is exportable at every point during and after reprocessing. This is the failure mode in §8 and the one test that must never be skipped. |
| Explicit id list | Non-candidate ids are reported and skipped; the run total accounts for every id supplied |
| Partial failure | One article failing leaves the others committed |
| Migration | The migration applies to a copy of the production schema and rolls back |

### Contract tests — real API, run on demand

Not in CI on every branch; on demand and before a backfield version bump.

- Each node returns the fields the adapter reads, against a live model call.
- A backfield upgrade is validated by re-running the 100-article sample and
  diffing categories, not merely by the suite passing.

The second is the one that catches a prompt change upstream. Editing a preset's
few-shot examples changed 2 of 4 classifications in testing (§11), so backfield
changing its own prompts can move labels without any error surfacing.

### Fixtures worth committing

The 100-article sample already produced the awkward cases: a 27,372-character
cookie-text article, an article yielding 41 locations, 11 yielding none, and the
8 point-scope articles that stayed ambiguous. These are the fixtures, and they
are real rather than invented.

## 12. Open decisions

**Backfield's CIN does not replace ours. Decided.** Our classifier stays
authoritative. The `information_needs` preset is excluded from the production
path, which is why the step table lists five remaining presets rather than six
and why the cost figures above do not include it.

It stays available for development and testing behind a flag, run on samples
rather than the corpus. What the 100-article test established, and why it is
worth keeping for that purpose:

| | |
|---|---|
| Exact agreement with our primary label | 51% |
| Allowing our alternate or their 1–3 set | 65% |
| Upheld a deliberately wrong label (control) | 5 of 100 |
| Same verdict regardless of the label shown | 92 of 100 |

Most disagreements are errors in our labels: "Civic Life" was applied to a movie
review, a holiday store-hours listing and a real-estate promotion. The control
run establishes that the model does not ratify the label it is shown, which is
the property required of an audit.

Used this way it is an audit instrument for our taxonomy rather than a
replacement classifier. Cost is one call per sampled article, $0.00078.

**Rationale phrasing.** Rationales open with "The article is/describes/profiles"
in almost every case. Three options, measured:

| Approach | Effect | Cost |
|---|---|---|
| `BACKFIELD_PROJECT_SYSTEM_PROMPT` | Shortens rationales; **does not** remove the opening — the preset's few-shot examples anchor it | None |
| Fork the preset with rewritten examples | Removed the opening in 2 of 4, **and changed 2 of 4 classifications** | Maintaining a copy of the prompt; requires re-validation |
| Strip the preamble after the fact | Deterministic, cannot affect labels | A regex to maintain |

Forking is not a cosmetic change: it moves labels. Post-processing is the only
option that alters presentation without altering classification.

**"Civic Life" versus "Civic information".** Both exist in our taxonomy, both map
to the same concept, and six of the 37 disagreements are churn between them. This
should be resolved regardless of what happens with backfield.

**Whether to keep our existing entity extraction.** `article_entities` is already
populated for 133,100 articles by `src/pipeline/entity_extraction.py`. Backfield
would produce a second, richer answer. Running both indefinitely means two
answers to the same question.

**Entity canonicalization.** In library mode, "Mayor Smith" in 40 stories is 40
mention rows, not one person. Backfield's Stylebook resolves this but is
DB-resident — `substrate_*` and `stylebook_*_canonical` tables, alias lookup and
a review queue — and adopting it means running backfield's schema, which is where
the h3 finding in §2 starts to matter. Deferrable, expensive to retrofit.

**The 11 point-scope articles where the publication's city was not mentioned.**
Some are legitimate — a Branson paper covering Springfield. Rule 2 would place
them wrongly. Worth reading before the backfill.

## 13. Suggested sequence

1. Tune the boilerplate heuristic and the content gate against known-bad
   articles, and measure the rejection rate on a fresh sample drawn without the
   length bias in this one.
2. Confirm the resolved points on the 100-article sample are actually correct.
   The rule is validated; the output is not.
3. Measure prompt caching and preset consolidation on 100 articles.
4. Build the adapter and the four tables; run 1,000 articles end to end.
5. Enable the `CronJob` for new collection. This is the steady state and the
   reason for the work.
6. Run the supplied backfill list, rate-limited, with the spend ceiling armed —
   one overnight run, ~$100.
7. Decide later whether to process the remaining history. Nothing forecloses it.

Steps 1 to 3 cost a few cents each and should gate the rest.
