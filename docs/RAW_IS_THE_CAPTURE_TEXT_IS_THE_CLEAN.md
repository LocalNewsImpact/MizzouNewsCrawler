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

## Deployment order matters

Three deployments are live — `mizzou-api`, `mizzou-processor`, `work-queue` —
and each breaks the moment the column is renamed, until it runs code that knows
the new name. The crawler, enrichment and pipeline CronJobs are **suspended**,
which makes this the right window: nothing is mid-extraction.

The migration and the image must land together:

1. Merge the code change. Its readers accept both names during the transition.
2. Build and roll out the images.
3. Apply the migration.
4. Restart the three deployments.

A reader that accepts both names for one release is what removes the ordering
risk. `getattr(article, "raw", None) or getattr(article, "content", None)` on
the ORM side, and `COALESCE(raw, content)` is *not* available in SQL because the
old column ceases to exist — so the SQL readers must be switched in the same
release as the migration, and that is the constraint that makes step 1 a
compatibility release rather than a pure rename.

## Open decisions

**1. Does `text_length` change what it measures?** After the rename its
expression reads `length(COALESCE(raw, text, text_excerpt, ''))` — a column
named `text_length` measuring `raw`. Correcting it to prefer `text` is the same
semantic fix as the rename, but it recomputes the value for 165,609 rows and
every threshold, gate and audit built on it, including the enrichment length
gate. Renaming without touching it leaves the name visibly lying; changing it
is a data change that needs its own verification.

**2. Does enrichment switch to `text` in this PR?** It should — one cleaned
field, every downstream consumer. But `repository.py` chose `content`
deliberately:

> The gate reads `a.content`, deliberately -- the paywall thresholds were
> measured against that column, and reading a different one would silently
> re-measure all of them.

The cleaned body is shorter and has the wall text stripped, so pointing the gate
at `text` re-calibrates it. That needs the thresholds re-measured against
`text`, not just the column swapped, or the gate starts passing and failing
records for reasons nobody chose.
