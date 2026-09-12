# Geography a person puts in

Some articles will never get their geography from the pipeline. A story
behind a paywall arrives as a headline and a subscription prompt, and no
amount of re-running the model reads what was not fetched. The pipeline
is right to stop; the story still happened in a place, and that place
still belongs on a map of where an outlet reports.

So a person contributes it, and the contribution is used exactly as the
pipeline's own is — while staying visibly a person's.

## Which articles

The population is smaller than "articles with no geography", and the
difference matters: a queue padded with articles nobody can help buries
the ones they can.

Measured on the Missouri dataset, excluding wire, obituaries, weather
and opinion:

| why there is no geography | articles | reviewable |
|---|---:|---|
| never enriched | 85,496 | no — a pipeline backlog |
| enriched, no geography, no reason recorded | 3,636 | no — a defect to find |
| no codeable geography | 1,155 | **no — the pipeline answered** |
| paywall stub | 969 | yes |
| `not_scoped` | 175 | yes |
| `regional_uses_place_set`, empty set | 146 | yes |
| publication city not in the gazetteer | 5 | yes |

**`no_codeable_geography` is excluded.** The pipeline read the story and
found no place in it, which is a verdict rather than a gap — a column, a
devotional, a national wire piece with nothing local in it. Asking a
person to second-guess 1,155 correct answers to find the 1,300 real gaps
is how a queue stops being worked.

Spot-checking that verdict is a reasonable thing to want and a different
question. It belongs in its own queue, asked its own way.

**The 85,496 are not a review problem.** Crons are suspended and only
March has been backfilled. They want enrichment, not a person.

## Scoped, or nobody finishes it

343 articles for March across Audrain, Boone and Osage — 273 of them
Boone, across ten newsrooms. Nobody works a 343-item queue. "Osage,
March" is 23 and finishable in a sitting.

Four filters, and they are the four the visual builder's spec already
uses, so the console keeps one vocabulary rather than growing a second:

| filter | column |
|---|---|
| dataset | `articles.dataset_id` |
| date | `articles.publish_date` |
| county | `candidate_links.source_county` |
| newsroom | `candidate_links.source_id` |

## Where it is stored, and why not in `article_geoids`

`persist_outcome` deletes and rewrites an article's geoid set on every
enrichment run:

    DELETE FROM article_geoids WHERE article_id = :id

A human row written there is destroyed the next time anything
re-enriches that article — including a run that produces worse geography
than the person did. The work would vanish silently and the person would
have no way to know.

So the contribution lives in its own table, and the geoid set is
**rebuilt from it** rather than holding the only copy:

    article_places_manual
      article_id      the story
      full_name       what was written, as written
      city, county, state
      geoid           resolved through lnic_contracts.geography
      geoid_level     state | county | place | tract | block
      is_point        the central location, or a mention
      added_by        who
      added_at        when
      note            why, where a reviewer wants to say

`build_story_geoids` reads it alongside the extracted places and emits
those rows into `article_geoids` with `source = 'human'`.

## Two consumers, two paths — and neither was free

The first cut of this claimed that writing to `article_geoids` was
enough because every consumer reads it. **That was wrong**, and it is
recorded here because it is the kind of wrong that looks finished: the
row was written, the audit entry was made, and nothing drew it.

**The story map does not read `article_geoids`.** `run_story_map` draws
its dots from `article_enrichment.point_lat` / `point_lon` and shades
its counties from `article_enrichment.geoids`. The datadesk console
therefore reads `article_places_manual` directly and merges it into both
layers — a human centre becomes a dot with coordinates from the Census
internal point for its geoid, and every manual row shades its county.

**BigQuery does read `article_geoids`**, and nothing else. The scheduled
query "Sync Article Geoids from Cloud SQL" is `SELECT * FROM
article_geoids`, daily at 07:00 UTC, with no filter of its own.

**The merge in `persist_outcome` cannot reach these articles.** It is
the only other caller of `manual_geoids()`, and the only route to it is
`select_by_ids`, which rejects anything whose `status != 'labeled'`. Of
the 1,266 March articles the review queue offers, **zero** are `labeled`
— 850 `enrichment_skipped`, 157 `not_article`, 150 `enriched`, 65
`cleaned`, 44 other — because the queue exists precisely for articles
enrichment has already finished with.

So there is a third path, `enrich apply-manual`:

    enrich apply-manual [--dataset SLUG] [--since YYYY-MM-DD] [--dry-run]

It inserts the contribution into `article_geoids` with `source =
'human'`, additively and idempotently — `ON CONFLICT DO NOTHING`, never
the DELETE-and-rewrite `persist_outcome` does, because it runs outside
enrichment and must not touch what enrichment wrote. **It must run
before 07:00 UTC** for a contribution to appear in that day's BigQuery
sync.

## Used identically, marked plainly

Every consumer sees a human contribution in exactly the same shape as an
extracted one, on the same ladder, resolved by the same crosswalk.

`source` is what keeps it honest. The column already distinguishes
`point`, `mention`, `scope_state` and `county_rollup`; `human` joins
them. An analysis that wants to exclude human contributions can, an
analysis that wants to count them can, and one that does neither is not
silently mixing two things it thinks are one.

**Resolution is the pipeline's, not the reviewer's.** A person types
"Linn, MO"; `lnic_contracts.geography` turns it into `2943238` and its
county. A reviewer never types a FIPS, and a human entry cannot land on a
rung the pipeline could not have reached.

## What a reviewer may type, and what is offered back

A typed place name is worth nothing until it resolves, and a name that
resolves to the wrong place is worse than one that does not resolve at
all. So the queue does not take free text and hope.

**Suggestions come from the table the writer resolves against.** If the
console offered names from its own copy of the gazetteer while the
crawler resolved against another, a reviewer could pick a suggestion that
then failed, with no way to understand why. Both read
`lnic_contracts.geography`, so what is offered is what will resolve, by
construction rather than by both being careful.

**Same state first, never only.** Suggestions rank the publisher's own
state at the top and still offer everywhere else below.

Ranking catches the error the pipeline actually made. A story about the
sewer trustees of Freeburg -- a village in Osage County, Missouri -- was
extracted as `Freeburg, IL`. Illinois genuinely has a Freeburg, the
lookup succeeded, and the story shaded a county three hundred miles away.
Nothing downstream could catch it, because the answer was internally
valid. A reviewer typing `Freeburg` while working a Missouri outlet is
offered Missouri's first, and cannot make that mistake by accident.

Filtering would be wrong, and this corpus proves it: Whiteman Air Force
Base, Nashville, Wichita State, the University of Pittsburgh and Seattle
are all places Missouri outlets genuinely covered in one month. A
Missouri-only list would make real coverage unenterable, which is how a
queue teaches people to work around it.

**Typos are offered corrections, not rejections.** `suggest_places` and
`suggest_counties` return close names for a value that did not match --
the same `difflib` pass the county normalization already uses.

**A reviewer never types a FIPS.** They write a name; the contract
resolves it. A human entry cannot land on a rung the pipeline could not
have reached, and the stored row keeps what was typed beside the code it
resolved to, so a wrong resolution can be told from a wrong entry.

## Precedence

Enrichment outranks nothing and is outranked by nothing — they coexist.

- A human contribution for an article the pipeline could not read is the
  only geography that article has.
- Where both exist, both are recorded. The pipeline's is `point` or
  `mention`; the person's is `human`. Nothing is overwritten, because
  neither is evidence the other is wrong.
- A later enrichment run rebuilds the set and the human rows come back,
  because they are read from `article_places_manual` rather than
  surviving in place.

Deciding that one should win over the other is a real question and not
one this needs to answer to be useful. Recording both, distinguishably,
leaves it open.

## The queue

`ReviewDecision` with `subject_type = 'article'` — the same table and the
same machinery the discovery and extraction queues use, so this inherits
the audit trail, the one-decision-per-question constraint, and the
existing way of showing somebody what they already decided.

Two verbs:

- **Set where this is** — the central location. One per article.
- **Also mentions** — a place the story names that is not its centre.

The reviewer sees the headline, whatever text was captured, the URL, and
the reason there is no geography — a paywall stub reads differently from
a story nobody scoped, and knowing which is what tells a person whether
to open the link.

## What this is not

**Not a correction queue.** Nothing here edits what the pipeline
extracted. A wrong extraction is a different problem with a different
fix, and mixing "add what is missing" with "fix what is wrong" makes both
harder to reason about.

**Not a labelling task.** This is not training data for a geography
model; it is geography for stories that have none. If it later becomes
training data, `source = 'human'` is what makes that possible to do
deliberately.
