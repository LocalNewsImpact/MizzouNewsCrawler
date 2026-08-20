# Backfield enrichment before BigQuery export

Proposal for a final pipeline stage that extracts places, people, organizations
and article metadata using [backfield](https://github.com/localangle/backfield),
writing to the crawler's own database so the results replicate to BigQuery
through the existing Datastream CDC.

Every figure below was measured on 20 August 2026 — against the production
database, and by running backfield's nodes on 100 real articles. Nothing here is
a vendor claim or an estimate where a measurement was possible.

---

## 1. Where it fits

```
discover → extract → clean → wire check → CIN label → ENRICH → Datastream → BigQuery
                                              ↓                    ↓
                                     status='labeled'      status='enriched'
                                     (candidate)           (exportable)
```

**The export criterion changes.** Today BigQuery takes
`status='labeled' AND wire_check_status='complete'`. It will instead take
`status='enriched'`, applied only after this stage completes successfully.

Enrichment stops being an optional trailer on the pipeline and becomes the last
required step. `labeled` becomes a candidate state, not an exportable one.

The stage selects its work as:

```sql
status = 'labeled' AND wire_check_status = 'complete'
```

and on success sets `status = 'enriched'`.

`enriched` means **every step configured for that article's dataset has
completed** — not that every possible step ran. See §7.

Three consequences worth being explicit about:

- **Junk cannot export.** An article rejected by the content gate in §3 never
  becomes `enriched`, so it never reaches BigQuery, whatever CIN label it was
  given. The cookie-text defect closes by construction rather than by adding a
  check earlier in the pipeline.
- **Enrichment failure withholds export.** An article that errors stays at
  `labeled` and does not appear in BigQuery until it succeeds. This is the
  intended behaviour, and it makes the enrichment backlog an export backlog —
  see §9.
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

### The backfill is March only

**Scope of the initial backfill is roughly 15,000 articles from March 2026**, not
the 99,418 historical total. March has 17,441 qualifying articles, so the target
is a subset of one month.

The remaining ~82,000 historical articles are deliberately out of scope. They can
be added later without rework: `enriched_at` is the idempotency key, so widening
the window is a query change, and nothing already enriched is re-billed.

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

**This is a labelling defect, not a nuisance.** There is no story in that text,
so there is nothing for a CIN label to describe. The classifier produced one
anyway, at 0.43 confidence, and that low confidence stopped nothing: the article
was promoted to `status='labeled'` and is exportable today. Two gaps meet here —
no check that the text is a story, and no confidence floor on the promotion.

Both belong **before CIN labelling**, not before enrichment. If junk never gets
labelled it never reaches `status='labeled'`, never exports, and never costs an
enrichment call. Placing the gate in this stage would catch it one step too late:
the wrong label would already exist and would already have replicated.

Two layers, cheapest first:

**0a. A deterministic heuristic, free.** Density of cookie, consent, privacy
policy, vendor list and advertising-partner terms. Five or more occurrences
identified exactly the one junk article in the sample and nothing else. This runs
in Python with no API call and should be tuned against known-bad articles before
it is trusted to reject anything.

**0b. A truncated LLM gate for what the heuristic misses.** Cookie and paywall
text is identifiable from the opening few hundred characters, so this call sends
**the first ~800 characters, not the article** — roughly 250 input and 30 output
tokens, about $0.0001. It answers one question: is this the text of a news story?

Rejected articles are flagged and skip every subsequent step.

**Be clear about what this is worth.** The frequency measured was 1 in 100, and
the sample was drawn from articles at or above median length — junk of this kind
is long, so the true corpus rate is probably lower. The cost saving is real but
small: the gate costs about $1.50 per 15,000 articles and saves a comparable
amount. The reasons to do it are the other two:

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
| **Backfill, ~15,000 from March** | **$100–113** one-time |
| Ongoing, busy month (12,000–17,500) | **$80–131** |
| Ongoing, slow month (1,000–5,300) | **$7–40** |
| For reference: all 99,418 historical | $666–745, not planned |

At this size the backfill costs about the same as one busy month of ongoing
enrichment. The recurring figure, not the backfill, is the number that matters
for the decision.

Two levers not yet applied, each worth measuring before the backfill:

- **Prompt caching.** The six production prompts total ~9,000 tokens and are identical
  across every article; roughly 74% of each call's input is this stable prefix.
  DeepSeek bills cache reads at $0.13/M against $0.25/M. Putting the article last
  in the message should cut input cost materially.
- **Preset consolidation.** Six presets send the article six times. Combining
  them into fewer calls would send it once, at some risk to per-category quality.
  Worth an A/B on 100 articles before adopting.

## 5. Time

Measured throughput at 10 concurrent workers:

```
7 metadata presets   100 articles in 28s per preset
place_extract        100 articles in 122s
```

A full 9–10 call pipeline is roughly 3 seconds per article at that concurrency.

| | At 10 workers | At 50 workers |
|---|---|---|
| **Backfill, ~15,000 from March** | **~12 hours** | **~2.5 hours** |
| Busy month, incremental (~580/day) | ~27 minutes/day | — |
| For reference: all 99,418 | ~3.2 days | ~15 hours |

A March-only backfill is a single overnight run at modest concurrency. It does not
need the higher concurrency tier, and it does not need to survive a multi-day
window — which removes most of the operational risk from the first real run.

The job is I/O-bound on the API, not CPU-bound, so one or two existing spot nodes
are sufficient. Concurrency is limited by OpenRouter rate limits, not by us.

## 6. Running it on GCP

| | |
|---|---|
| Compute | Kubernetes `CronJob` on the existing `mizzou-cluster`, spot pool |
| Database | The crawler's existing Cloud SQL — new tables, no new instance |
| Image | Crawler base plus backfield's packages, pinned to a backfield commit |
| Secrets | OpenRouter key, and a geocoder key if step 4 is enabled |
| Redis, Celery, backfield APIs | Not used |

Incremental infrastructure cost is a few dollars per month of spot compute plus
storage. There is no new managed service.

Backfield is pre-1.0 and its own documentation says self-hosting is unsupported.
Pin an exact commit, treat upgrades as deliberate work, and keep the node calls
behind a thin adapter so a breaking change touches one module.

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
| **None** | No backfield call is made; the article is marked `enriched` immediately and exports |

A `none` profile still produces an `article_enrichment` row, recording that the
profile was empty. An article must never be stranded at `labeled` because its
dataset asked for nothing.

### Absent and disabled are not the same

This is the part that will bite downstream if it is not carried into the data. A
missing place list can mean three different things:

| | Meaning |
|---|---|
| Step disabled for the dataset | Not attempted; absence carries no information |
| Step ran, found nothing | A real, negative finding |
| Step failed | Unknown; the article should not be `enriched` at all |

So every enrichment row records the profile version and the steps actually
applied, and BigQuery consumers filter on those rather than on `NULL`. Without
it, "no people were found" and "we did not look for people" are the same query
result, and any analysis over a mixed-profile corpus is wrong in a way nobody
will notice.

### The content gate is switchable, and that has a cost

`content_gate` is listed separately because it is the one step whose absence
changes what reaches BigQuery rather than how much is known about it. A dataset
running `none` exports its cookie-text articles, as happens today. That may be
the right call for a dataset being ingested for volume rather than analysis, but
it should be a decision recorded in the profile, not a side effect of turning
enrichment off.

Recommended default for a new dataset: `content_gate` on, everything else off.
Cheap, and it stops the known defect without committing to any spend.

## 8. Data written

New tables in the crawler database, all keyed on `article_id`. Datastream
replicates them to BigQuery automatically — no export code, no schema
registration.

| Table | Grain |
|---|---|
| `article_enrichment` | One row per article: scope, subject, topic, format, timeframe, user need, resolved point, **profile version and steps applied**, model and prompt versions, cost, `enriched_at` |
| `article_places` | One row per extracted location, with components, resolution method, and coordinates when resolved |
| `article_people` | One row per person mention, with quotes |
| `article_organizations` | One row per organization mention |

Every row records the model id, the backfield commit, and the prompt preset
version, so a reprocessing decision can be scoped to exactly what changed.

`status='enriched'` is both the export criterion and the idempotency key.
Re-running the job never re-bills an article that has already succeeded, because
enriched articles are no longer candidates. `enriched_at` records when, and the
recorded model and prompt versions scope any future reprocessing.

## 9. Failure handling

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
- **A bypass is required.** If enrichment is broken or too expensive to run,
  there must be a supported way to promote `labeled` articles to `enriched`
  without enrichment, so a vendor problem cannot indefinitely withhold the
  corpus.

## 10. Open decisions

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

The disagreements are mostly ours: "Civic Life" absorbed a movie review, a
holiday store-hours listing and a real-estate promo. The control run matters more
than the agreement rate — a model that ratifies whatever it is shown would be
useless as a check, and this one does not.

Used this way it is an audit instrument for our taxonomy, not a replacement
classifier. Cost is negligible: one call per sampled article, $0.00078.

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

## 11. Suggested sequence

1. Tune the boilerplate heuristic and the content gate against known-bad
   articles, and measure the rejection rate on a fresh sample drawn without the
   length bias in this one.
2. Confirm the resolved points on the 100-article sample are actually correct.
   The rule is validated; the output is not.
3. Measure prompt caching and preset consolidation on 100 articles.
4. Build the adapter and the four tables; run 1,000 articles end to end.
5. Backfill March, rate-limited, with the spend ceiling armed — one overnight run,
   ~$100.
6. Enable the `CronJob` for incremental articles.
7. Decide later whether to widen the window beyond March. Nothing in the design
   forecloses it.

Steps 1 to 3 cost a few cents each and should gate the rest.
