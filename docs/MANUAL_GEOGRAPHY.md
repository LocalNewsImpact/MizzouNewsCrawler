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

## Used identically, marked plainly

Every consumer — the story map, the BigQuery export, any query against
`article_geoids` — sees a human contribution in exactly the same shape as
an extracted one, on the same ladder, resolved by the same crosswalk. No
consumer needs to know, and none has to be changed.

`source` is what keeps it honest. The column already distinguishes
`point`, `mention`, `scope_state` and `county_rollup`; `human` joins
them. An analysis that wants to exclude human contributions can, an
analysis that wants to count them can, and one that does neither is not
silently mixing two things it thinks are one.

**Resolution is the pipeline's, not the reviewer's.** A person types
"Linn, MO"; `lnic_contracts.geography` turns it into `2943238` and its
county. A reviewer never types a FIPS, and a human entry cannot land on a
rung the pipeline could not have reached.

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
