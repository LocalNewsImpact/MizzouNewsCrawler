# A curated dataset needs to declare which checks do not apply to it

The pipeline's filters assume the corpus arrives unvetted. Discovery finds a
URL, and every downstream check exists to decide whether that URL is a local
news article worth enriching: wire detection, duplicate handling, the length
gate, `not_article` and `obituary` classification.

A curated dataset inverts that assumption. The WSU Washington State corpus is a
list of stories a researcher selected by hand — 3,558 URLs in the Murrow fellow
tracker, 474 of them already classified. Selection *is* the filter, and it has
already run, with better judgement than any heuristic. Applying the pipeline's
filters on top does not add a second opinion; it subtracts records the study
was defined to contain.

## What this cost on the WSU import

Two pipeline defaults had to be defeated by hand in
`scripts/import_wsu_notebook_labels.py`. Neither was visible from the schema.

**`wire_check_status` is `NOT NULL DEFAULT 'pending'`.** Omitting the column
does not mean "no wire check". It means the MediaCloud check is queued, and 33
of the imported headline groups are the same story on two or more publishers —
identical cross-publisher text is precisely the signal that check keys on. One
row had already been attempted and come back `api_error:422` seventeen minutes
after the import. Worse, `pending` is also the one value that *blocks*
enrichment, which selects on `wire_check_status IN ('complete', 'local')`, so
the default would have stranded all 474 rows short of the geo-classification
the import exists to reach.

**The syndicated copies are duplicates by content and units of analysis by
design.** The Snohomish trio runs one story across three domains the same day;
the Columbian and TDN share Columbia River coverage. Collapsing them would
destroy the per-outlet publication record the study measures. Nothing currently
marks duplicates from `text_hash`, so this was safe by accident rather than by
declaration — a future dedup pass keyed on content would silently break the
corpus.

The import therefore asserts `wire_check_status = 'local'` with

    wire_check_metadata = {"authority": "wsu-curated-url-set",
                           "mediacloud_lookup": false}

so the claim is auditable. Without that metadata, a curated assertion is
indistinguishable from a check that ran and returned a verdict.

## Why per-import overrides are the wrong shape

Both fixes live in one import script. That is the problem, not the solution:

- The next curated dataset repeats the reasoning from scratch, and whoever
  writes it has to rediscover that `pending` blocks enrichment.
- An override written into an import is invisible to the pipeline. A
  re-extraction, a cleaning pass or a new dedup job has no way to know these
  rows are exempt, so it re-applies the check the import worked around.
- The exemption has no scope. `wire_check_status='local'` on a row says nothing
  about whether the length gate or `not_article` classification should apply.

## The shape it wants

The exemption belongs on the dataset, where the curation claim actually lives,
and it must be readable by every stage rather than applied once at write time:

    datasets.metadata -> {"curated": true,
                          "bypass": ["wire_check", "content_dedup",
                                     "length_gate"]}

Each bypassed check then has one job: consult the dataset before it runs, and
record in the row that it was skipped and on whose authority. That keeps three
properties the current approach lacks — the reason is stated once, every stage
sees it, and a row always says why a check did not run.

Two constraints on any implementation:

- A bypass must never be the absence of a value. `wire_check_status` being
  NULL-able would have made this import a silent success and a silent
  enrichment failure. An exempt row carries a positive marker.
- Bypassing a check is not the same as asserting its happy answer. `local`
  happens to be both here because the curation claim and the check's verdict
  coincide. Where they would not, the stage needs a distinct skipped state
  rather than a fabricated result.
