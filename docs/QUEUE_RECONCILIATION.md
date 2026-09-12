# Reconciling the review queues with the pipeline

A review decision changes one column at the moment it is made. Nothing
afterwards checks that the rest of the record agrees with it, so a
disposition and the state it implies drift apart — quietly, because
every individual write succeeded.

Measured on 2026-09-12, after 810 discovery decisions and 3,602
extraction decisions:

| what a reviewer said | what is actually true |
|---|---|
| "not a story" — 207 URLs | **100 have articles**; 58 reached enrichment; **16 have geoids and are in BigQuery** |
| "re-extract this" — 16 articles | all 16 still `paused`; nothing re-extracted them |
| "reject" — 600 articles | 19 `enriched`, 17 `labeled` and queued to enrich, 7 `cleaned` |
| "it is wire" — 136 URLs | 74 links became `wire`, 45 stayed `discovered` |
| "it is opinion" / "column" | 4 opinion and 20 column pieces reached `enriched` |

None of this is a failed write. Each decision did what it was written to
do; no process asks afterwards whether the record still makes sense.

## What drives what

Three gates, and reconciliation is the business of moving records across
them deliberately rather than by accident.

| gate | selects on |
|---|---|
| verification / fetch | `candidate_links.status = 'discovered'` |
| enrichment | `articles.status = 'labeled'` |
| BigQuery: articles, labels, entities | `articles.status IN ('enriched','enrichment_skipped')` |
| BigQuery: geoids | **nothing — `SELECT * FROM article_geoids`** |

That last row is the one asymmetry, and it is load-bearing. Because the
other three syncs filter on status, moving an article to `not_article`
or `wire` removes it from BigQuery on its own. Its geography does not
follow, so the story disappears from the articles table while its
counties go on being counted.

Today nothing leaks: all 50,548 geoid rows belong to articles that are
`enriched` or `enrichment_skipped`, because geography is only ever
written during enrichment. The leak begins the moment reconciliation
starts changing statuses, which is the whole point of this document.

**So the first change is to the scheduled query, not to any row.** Give
the geoids sync the same `WHERE status IN ('enriched','enrichment_skipped')`
the other three already have. Then "remove this story from BigQuery" is
a status change and nothing else: no deletes in Postgres, reversible,
and impossible to forget for an individual article.

## The rules

Each is stated as: the disposition, the state it requires, and what to
do when they disagree.

### Discovery: "not a story"

The URL should never have been fetched. Anything downstream of it is an
artefact of a mistake.

- `candidate_links.status` → `not_article`
- `articles.status` → `not_article`, which removes it from every
  BigQuery sync once the geoids query is filtered
- enrichment rows, CIN labels and entities are **kept**. They cost
  nothing, they cannot reach an analysis that filters on status, and
  deleting them destroys the record of what the pipeline believed.

Applies to 100 articles today, 16 of them currently published.

### Discovery: "it is a story", with a kind

`lnic_contracts.discovery_verdict.link_status_for` already maps the kind
to a link status, and it is the contract both sides read. Reconciliation
enforces that mapping rather than restating it:

- a plain story, `news`, or `column` → `discovered`, to be fetched
- `wire`, `obituary`, `opinion`, `weather` → the withheld status for
  that kind, which no enrichment stage selects

Where an article already exists in a state the kind forbids — the 20
columns and 4 opinion pieces that reached `enriched` — the article's
status moves to match the kind. Its enrichment data stays, by the same
argument as above.

### Extraction: "reject"

The article is not usable. Same treatment as "not a story": status to
`not_article`, data kept, removed from BigQuery by the status filter.

The 17 currently `labeled` are the urgent ones — they are queued to be
enriched, so every day this does not run is a day they may cost money to
enrich something a person already rejected.

### Extraction: "re-extract"

**These were extracted. Extraction produced nothing.** All 16 have
`extracted_at` set and zero text and zero capture. They need a real
fetch, not a status nudge.

The wider `paused` population splits in two, and the split decides what
to do rather than being a detail:

| paused = 178 | |
|---|---|
| no capture at all | **93** — re-fetch |
| capture but no text | **49** — re-clean; fetching again wastes a request against a publisher |
| capture and text | 36 — the content is fine; parked for some other reason, and not this process's business |

### Extraction: "restore" and "accept"

Both say the record is usable. 471 restored articles are `enriched`,
which is the system working. The 36 accepted and 49 rejected articles
sitting in `paused` are the disagreement: an accepted article should not
be parked.

### Geography

No reconciliation. The contribution is applied by
`enrich apply-manual` on the daily housekeeping run, and a contribution
that has already been applied is a no-op.

## What it must not do

**It must not delete enrichment, CIN labels or entities.** The status
filter is what keeps them out of published figures; deleting them
destroys evidence of what the pipeline concluded and makes the
"reviewer disagreed with the model" set unrecoverable — which is the
training data.

**It must not re-fetch an article that already has a capture.** 49 of
the paused articles have a body that failed cleaning. Fetching those
again spends a request against a publisher to obtain something already
held.

**It must not act on a decision it cannot explain.** A disposition whose
required state is not in the table above is reported and skipped, never
guessed at.

**It must not run silently.** Every run reports what it changed, per
rule, and a run that changes an unusual number of rows is the signal
that a rule is wrong.

## Where it runs

`mizzou-housekeeping`, daily at 02:00 UTC, beside `enrich apply-manual`
— before the 07:00 BigQuery sync, so a story removed in the morning is
gone from BigQuery the same day.

`--dry-run` reports every change without making it. It is a tool for
checking a rule that has just been edited, not a required first step.

## Two halves, and only one of them is unusual

Most of what this does is the ordinary pipeline. 93 articles go back for
a fetch, 49 for a clean, the wrongly-parked are unparked, and 516 links
sit at `discovered` waiting for verification — every one of those
records then moves the way every record moves. There is nothing to
preview about it.

The other half is not processing. It is retraction:

| rule | articles leaving BigQuery | of those, carrying geography |
|---|---:|---:|
| discovery: "not a story" | 20 | 16 |
| extraction: "reject" | 139 | 18 |
| **total** | **159** | **34** |

159 articles currently published as local news stop being published, 34
of them carrying county geography that has been feeding coverage
figures. That is the number worth knowing before the first run, and it
is written here rather than left for a dry run to discover.

**The geoids filter has to land first.** Without it those 34 articles
disappear from the BigQuery articles table while their counties go on
being counted — a state worse than either leaving them published or
retracting them properly. It is a change to a GCP scheduled query, so it
arrives outside any pull request or deploy, and nothing in this
repository will tell you whether it has happened.
