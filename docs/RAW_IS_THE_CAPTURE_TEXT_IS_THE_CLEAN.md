# `raw` is the capture, `text` is the clean

`articles.content` holds the **raw capture**. `articles.text` holds the
**cleaned body**. Nothing about either name says so, and the model's own
comments say the opposite:

    content = Column(Text)                      # Core content
    # Keep older 'text' fields for compatibility
    text = Column(Text)

So the column that is merely an input reads as the authoritative one, and the
column every analysis stage is supposed to use reads as a deprecated leftover.
That is not a documentation problem. It has already produced three defects.

## What the names have cost

**Enrichment reads the raw capture.** `src/enrichment/repository.py` selects
`a.content` in eight places and gates on `coalesce(a.content, '') <> ''`. The
LLM therefore sees navigation menus, cookie banners and paywall notices that
cleaning exists to remove. CIN, by contrast, reads `text` first — so one
article is classified on the cleaned body and enriched on the raw one.

**`text_length` measures the wrong column.** The generated expression is

    length(COALESCE(content, text, (text_excerpt)::text, ''::text))

A column named `text_length` that prefers `content` means every audit filtering
on `text_length` while reading `text` is measuring one column and reading
another. 530 rows have an empty `text` with `content` populated, so they report
a non-zero length and are invisible to exactly that kind of query.

**The same file disagrees with itself.** Two places in the enrichment
repository read `COALESCE(a.content, a.text, '')` rather than `a.content`, so
the fallback order is inconsistent within one module.

## Why this was survivable until now

`content` and `text` were byte-identical for **159,709 of 165,609** articles
(96.4%). The write path used to put the same cleaned string in both, throwing
the raw copy away. Reading either column was the same act, so no reader was
wrong yet.

The split began in March 2026, when the insert was fixed to keep both:

| month | articles | `content` != `text` |
| --- | --- | --- |
| Jan 2026 | 8,738 | 0 (0%) |
| Feb 2026 | 19,996 | 0 (0%) |
| Mar 2026 | 31,101 | 3,526 (11.3%) |
| Apr 2026 | 9,047 | 1,163 (12.9%) |
| May 2026 | 1,708 | 476 (27.9%) |
| Sep 2026 | 1,134 | 163 (14.4%) |

Every reader that named the wrong column became wrong on that date and stays
wrong for everything extracted since. In the export it is currently 136 rows
carrying ~154 extra characters each; it grows with every extraction.

## The rename

    articles.content  ->  articles.raw

`text` keeps its name, because it is already the field the pipeline is meant to
converge on and renaming it would touch far more than this.

Two schema objects reference the column and both follow the rename
automatically, because PostgreSQL stores their definitions parsed rather than as
text:

- the `text_length` generated expression
- `ix_articles_rot47_ciphertext`, a partial index whose predicate is
  `content LIKE '%k^Am%'` — and which becomes *more* correct, since ROT47
  ciphertext is a property of the capture

No view depends on `articles`. The BigQuery export does not publish the body.
`web/frontend/src/WireReview.jsx` reads `a.news || a.body || a.content` from an
API response, a fallback chain rather than a column read.

## Scope

27 files carry a reference. The mechanical part is a rename; the judgement is
in two places, called out below as open decisions.

## What was decided, and measured

**`text_length` now measures the cleaned body.** The generated expression
becomes `length(coalesce(text, raw, text_excerpt, ''))`, with `raw` as the
fallback for rows extracted before the columns diverged. A generated column
cannot be altered, so the migration drops and re-adds it (one table rewrite,
~1.4 GB, under the migration's 30-minute statement timeout). Measured against
production before the change, 165,609 rows:

| | rows |
| --- | --- |
| value changes | 5,473 |
| shrinks (cleaning had removed chrome) | 835 |
| grows (`text` longer than the capture) | 4,638 |
| becomes 0 (`text` = '' with a capture present) | 527 |
| becomes non-zero | 0 |
| crosses 400 downward / upward | 501 / 77 |
| crosses 200 downward / upward | 524 / 132 |

The 527 that become 0 are 289 `not_article`, 177 `paywall`, 29 `paused`, 23
`opinion`, 4 `obituary`, 2 `enriched`, 1 `weather`, 1 `enrichment_skipped`:
rows whose body is the wall or the furniture, where "cleaning ran and left
nothing" is the right answer. `''` counts as a measured zero because
`coalesce()` skips NULL, not the empty string.

**Enrichment is renamed, not re-pointed.** It reads `a.raw` — the same
column, under its real name — because its paywall thresholds were measured
against that column and moving it to `text` re-measures them. That is its own
change. `tests/enrichment/test_an_empty_body_is_not_a_verdict.py` pins the
choice by name so nobody re-measures it by accident.

**The cleaning pass stops writing the capture.** `cleaning.py`'s
`ARTICLE_UPDATE_SQL` wrote cleaned prose back into `content`, which is how the
two columns converged on 159,709 rows. It now writes `text` only. The ROT47
repair keeps its rewrite of `raw`: decoding ciphertext is a property of the
capture, and it says so by name.

**`ArticleInput.content` stays.** The enrichment input dataclass keeps its
field name; it is filled from `r.raw` in `_rows_to_articles` and is internal
to the enrichment package.

**The datadesk console edits and displays `raw`, and that is an open
decision.** Its model comment said `content` "is the current field and the one
review edits will target", and its inline editor called it a cleaned-text
column. So a reviewer correcting "Stored text" has been writing the raw
capture — the column CIN never reads. The rename makes that visible
(`/review/articles/<id>/edit/raw/`) without changing it; moving the editor
and the detail view to `text` is a behaviour change for its own PR.

## What moves outside the crawler

- **BigQuery.** The `articles` transfer is `SELECT * FROM articles ...` with
  `WRITE_TRUNCATE`, daily at 07:00 UTC. The first run after the migration
  renames the column in `mizzou_analytics.articles` and shifts `text_length`.
  The Sheets export functions read `a.text` and are unaffected. Ad-hoc
  queries naming `content` (24 jobs in the last 90 days, last 2026-07-22)
  will need `raw`.
- **datadesk.** Separate PR on that repo. It must merge AFTER this migration
  has run, because merging is its deploy and the model would 500 on every
  article query until the column exists. The live column-level grants follow
  the rename by attribute number and need no re-apply;
  `create_crawler_write_role.sql` is updated so a fresh bootstrap matches.
  Two visible, intended consequences: the Blocked page's "No body at all"
  count (`text_length = 0`) rises by the 527 above, and the queue's
  `text_length__gte=2000` doubt score now measures the cleaned body.
- **`bk_articles_20260919`**, the snapshot taken for the shared-body
  retraction, keeps its `content` column. It is a snapshot, not a live table.

## Deployment

There is no compatibility release: the SQL readers name `raw` and nothing
else, because a renamed column cannot be read under two names in SQL. The
schema and the code cut over together, and the deploy pipeline decides the
order:

- `run-migrations` in `build-and-deploy-services.yml` runs as soon as the
  migrator image builds, deliberately not waiting for the service builds.
- Each service image deploys itself (`kubectl set image`) as the last step of
  its own Cloud Build, at the end of the base → ml-base → processor → api →
  crawler chain.

So the schema moves first, and a pod still running old code fails on
`column "content" does not exist` until its rollout lands — minutes. Every
crawler, enrichment and pipeline CronJob is suspended, so `mizzou-processor`
and `work-queue` are idle; `mizzou-api`'s article-body endpoints
(`backend/app/main.py`, `telemetry/operations.py`) answer 500 for that window
and nothing writes.

1. Merge. `run-migrations` applies `b1c2d3e4f5a7`; the rollouts follow.
2. Verify: `SELECT raw FROM articles LIMIT 1`, `text_length` spot checks
   against the table above, `ix_articles_rot47_ciphertext` predicate reads
   `raw`.
3. Merge the datadesk PR.
4. The 07:00 UTC BigQuery transfer picks up the new column.

Rollback is `alembic downgrade z6f7a8b9c0d1`, which restores the name and the
old expression; `tests/alembic/test_raw_is_the_capture_postgres.py` proves the
round trip on a table with rows in it.
