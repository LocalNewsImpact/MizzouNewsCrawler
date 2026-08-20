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
discover → extract → clean → wire check → CIN label → [ENRICH] → Datastream → BigQuery
                                              ↓
                                    status = 'labeled'
```

The stage runs on articles that already satisfy the export gate and have not yet
been enriched:

```sql
status = 'labeled' AND wire_check_status = 'complete' AND enriched_at IS NULL
```

That gate is the existing one — `src/cli/commands/extraction.py` documents
BigQuery as exporting `status='labeled' AND wire_check_status='complete'`.

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

Enrichment adds no new qualification rule. If an article is fit to export, it is
fit to enrich.

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
| 1. `geographic_scope` | every article | 1 | Decides whether a point location is meaningful at all |
| 2. `place_extract` | point-scope articles only (46%) | 1 | Mentions, with parsed components |
| 3. Resolve the point | point-scope articles | 0 | Single city, else the publication's city — see below |
| 4. `geocode_agent` | unresolved POI-level only (~8%) | many | Backfield's agentic geocoder |
| 5. Remaining metadata presets | every article | 5 | subject, topic, format, timeframe, user need |
| 6. `person_extract`, `organization_extract` | every article | 2 | People with quotes; organizations |

**Step 1 before step 2 is the main saving.** Scope costs one call and excludes
54% of articles from place extraction entirely.

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
| Backfill 99,418 | **$666–745** one-time |
| Ongoing, busy month (12,000–17,500) | **$80–131** |
| Ongoing, slow month (1,000–5,300) | **$7–40** |

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
| Backfill 99,418 | ~3.2 days | ~15 hours |
| Busy month, incremental (~580/day) | ~27 minutes/day | — |

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

## 7. Data written

New tables in the crawler database, all keyed on `article_id`. Datastream
replicates them to BigQuery automatically — no export code, no schema
registration.

| Table | Grain |
|---|---|
| `article_enrichment` | One row per article: scope, subject, topic, format, timeframe, user need, resolved point, model and prompt versions, cost, `enriched_at` |
| `article_places` | One row per extracted location, with components, resolution method, and coordinates when resolved |
| `article_people` | One row per person mention, with quotes |
| `article_organizations` | One row per organization mention |

Every row records the model id, the backfield commit, and the prompt preset
version, so a reprocessing decision can be scoped to exactly what changed.

`enriched_at` on `articles` is the idempotency key. Re-running the job never
re-bills an article that has already succeeded.

## 8. Failure handling

- One article failing must not fail a batch. Errors are recorded per article with
  the exception type and the step that failed; the article stays unenriched and
  is retried on the next run.
- A batch is committed per article, not per run, so a job killed mid-way loses
  nothing already paid for.
- Cost is recorded per article. A daily spend ceiling stops the job rather than
  discovering the overrun on an invoice.
- Enrichment failure never blocks export. An article with `enriched_at IS NULL`
  still replicates to BigQuery with its existing fields.

## 9. Open decisions

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

## 10. Suggested sequence

1. Confirm the resolved points on the 100-article sample are actually correct.
   The rule is validated; the output is not.
2. Measure prompt caching and preset consolidation on 100 articles.
3. Build the adapter and the four tables; run 1,000 articles end to end.
4. Backfill, rate-limited, with the spend ceiling armed.
5. Enable the `CronJob` for incremental articles.

Steps 1 and 2 cost a few cents each and should gate the rest.
