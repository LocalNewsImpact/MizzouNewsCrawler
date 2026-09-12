# The pipeline as states: what selects what, and how to rewind

Written because three rules were built on inference and two of them were
wrong. `extracted` was assumed to be an article status that cleaning
picks up; the paused articles were split by how much text they held when
the reason was recorded in a column all along. Neither error would have
survived a look at this page, which did not exist.

Every claim below names the code or the query it came from.

## Two vocabularies, and they are not the same

`candidate_links.status` and `articles.status` share several words and
mean different things by them. `extracted` is a link status *and* an
article status; `paused` is both and means something different on each.

| | values actually present (2026-09-12) |
|---|---|
| `candidate_links.status` | extracted 105,198 · wire 89,676 · not_article 24,846 · sampled_out 16,453 · paused 5,575 · article 4,760 · obituary 4,631 · opinion 3,891 · weather 2,745 · paywall 2,043 · 404 1,555 · discovered 675 · skipped 45 · proxy_blocked 37 · filtered 7 |
| `articles.status` | labeled 85,245 · wire 47,054 · enriched 15,198 · obituary 4,278 · out_of_scope 3,830 · paywall 2,166 · weather 2,071 · opinion 1,981 · enrichment_skipped 1,250 · not_article 1,245 · cleaned 444 · paused 178 |

`articles.status = 'extracted'` is absent from that list and is still a
real status: it is transient, and housekeeping moves every one that has
no text to `paused`. A status can be load-bearing and have a count of
zero.

## The forward path

    LINK      discovered ──verify──> article ──extract──> extracted
                                         │
    ARTICLE                              └──> (created) ──> cleaned
                                                              │
                                               analyze ───────┘
                                                  │
                                                  v
                                               labeled
                                                  │
                                               enrich
                                                  │
                                    ┌─────────────┴─────────────┐
                                    v                           v
                                enriched            enrichment_skipped

| stage | selects | sets | source |
|---|---|---|---|
| verification | `candidate_links.status='discovered'` | `article`, or a withheld kind | `services/url_verification_service.py:143` |
| extraction | `candidate_links.status='article'` | link `extracted`; article created | `cli/commands/extraction.py:616` |
| cleaning | inside extraction | article `cleaned` | `cli/commands/extraction.py:2824` |
| classification | article status in `('cleaned','local')` | `labeled` | `cli/commands/analysis.py:_resolve_statuses`, `models/database.py:1078` |
| enrichment | `articles.status='labeled'` | `enriched` / `enrichment_skipped` | `enrichment/repository.py:42` |

Classification's default is literally `["cleaned", "local"]`. An article
in any other status is not classified, whatever else is true of it.

## What is published

Three BigQuery syncs select `status IN ('enriched','enrichment_skipped')`
— articles, labels, entities. The geoids sync now carries the same
filter; before 2026-09-12 it was `SELECT * FROM article_geoids` with no
filter, so a retracted story's counties would have outlived the story.

**Retraction is therefore a status change and never a delete.** Moving an
article out of those two statuses removes it from every sync at the next
run.

## The exceptions, and where they park

| status | what it means | recorded where |
|---|---|---|
| article `paused` | extraction ran and produced no text: `status='extracted' AND text IS NULL`. Cannot proceed to cleaning. | `cli/commands/housekeeping.py:225`, reason in `articles.metadata->>'pause_reason'` |
| link `paused` | candidate expired — older than `--candidate-expiration-days` and never became an article | `cli/commands/housekeeping.py:260` |
| link `sampled_out` | deliberately not fetched | — |
| link `404`, `proxy_blocked` | the fetch failed in a way worth telling apart | — |
| article `wire`/`obituary`/`opinion`/`weather` | a kind no enrichment stage selects. The status IS the instruction not to enrich; there is no second flag. | `lnic_contracts.discovery_verdict.status_for` |

**Read `pause_reason`, do not infer it.** The 178 paused articles split
77 / 101 by that column: 77 carry `null_text` and have neither text nor
capture; 101 carry no reason at all and have both. The second group is
exactly the 101 articles with an extraction-queue decision (49 reject,
36 accept, 16 reextract) — they were parked by review, not by a pipeline
failure. Splitting them by how much text they held, as an earlier draft
did, produced 93/49/36 and was wrong about all three.

## Rewinds

To send a record back to a stage, set the status that stage selects. The
gate is the only thing that matters; nothing reads a flag beside it.

| to re-run | set | on |
|---|---|---|
| verification | `discovered` | the link |
| extraction (a real re-fetch) | `article` | the **link** — extraction reads the link, not the article |
| classification | `cleaned` | the article |
| enrichment | `labeled` | the article |
| nothing, ever again | `not_article` | the article |

Two traps in that table, both of which have already been fallen into:

**A re-extraction is set on the link.** Extraction selects
`candidate_links.status='article'`; setting the article to anything at
all does not schedule a fetch.

**There is no "clean me again" article status.** Cleaning happens inside
extraction, and classification selects `cleaned`, which is cleaning's
*output*. An article whose cleaning failed goes back through extraction
— via its link — or nowhere.

## What this does not cover

`local` appears beside `cleaned` in classification's default and in
`WIRE_CHECK_QUEUE_STATUSES`, and no article currently holds it. It is
either historical or set somewhere not found. Anything routing on it
should establish that first rather than assume, which is the mistake
this document exists to stop.
