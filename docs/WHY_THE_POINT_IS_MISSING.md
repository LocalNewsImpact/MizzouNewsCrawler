# Why the point is missing

Measured 2026-09-16/17 over the Missouri corpus. The short version: the
pipeline finds the places and never chooses one.

## The number

150 articles were selected on three conditions — enrichment classified the
scope as `city_municipality` or `neighborhood_community`, so the pipeline
itself judged the story local; the gazetteer recognised a named feature in
the text; and **no point was selected**.

| | |
|---|---|
| articles | 150 |
| production named at least one place in `article_places` | **143 (95%)** |
| production selected a central point | **0** |
| a model asked one direct question, with a verbatim quote required | **101** |
| of those 101, the place was ALREADY among production's claims | **92 (91%)** |

Production had the answer for 92 of them, in its own table, and did not
promote it.

## What was tested along the way, and what it cost

Two days went into the evidence layer on the assumption that the gate was
starved of it. It was not.

**Re-extracting the corpus against the statewide gazetteer.** 19,926
articles, 0 errors, entity matches 124,868 -> 160,328. Retroactive effect
on refused geography, measured over all 5,128 refused claims: **zero**.
Every claim that would now be admitted passes with `institution_places`
empty.

**Re-enriching under the same profile with richer evidence.** 279 articles,
all already profile v3, so entity evidence was the only changed input. 15
gained a point, of which 3 matched an institution city and 2 carried
`point_support='institution'`. 34 of 167 institution-supported points MOVED,
32 of them from a city to the county containing it -- coarser, not better.
So roughly 3 changes from the evidence and ~45 from the model's own
non-determinism. Rolled back.

**Handing the model a candidate list drawn from the gazetteer.** 150
articles, candidates plus a required verbatim quote: **31** verified
placements, 63 minutes. The same 150 with the quote and NO candidates:
**101**, 13 minutes. The candidate list did not help; it suppressed 70
placements and pulled others to the wrong place — a Jackson County story to
the town of Jackson, 300 miles away, because a transit stop carried the
name.

**Why the candidates were that bad.** `gazetteer_name_places` is an index of
every OSM feature name, and 61% of it is categories where the name is a
label rather than an identity. `Basketball` is a court, `Locker Rooms` is a
locker room, `Honor Roll` is a plaque. It also holds place names, so
`Jefferson City -> Jefferson City` is 15.5% of candidates and is the article
naming the place rather than evidence about it. And the index is place-level,
so a county-level story had no county to choose.

Two defects behind that were real and are fixed (#600): the generic-token
guard was missing its sports and facility vocabulary, and a name borne by
many features of which one was geocoded counted as unambiguous —
`bethel church` has 52 bearers in Missouri and resolved every Missouri story
naming one to Wildwood.

## Where the failure actually is

Not extraction. Not the gazetteer. Not spaCy. The claims exist; the step that
turns claims into a point produces nothing on stories the pipeline has
already classified as local.

The one change that moved the number was asking for the place directly and
requiring a sentence copied from the article to justify it. 0 -> 101, at a
third the runtime of the candidate design, and the quote is checkable by
string comparison rather than trust: 101 of 107 verified, and of the 6 that
did not, most were corrupted bodies or normalisation near-misses rather than
invention.

## What the evidence layer is still for

Confirmation, which is the role §4e of `STATEWIDE_GAZETTEER.md` established
and this does not disturb. The gate asks whether a place the model proposed
is defensible; two independent signals agreeing is evidence. What does not
work is the gazetteer proposing, and what does not work is the gazetteer
constraining.

## Also found, and not yet fixed

**561 enriched articles carry ROT47 ciphertext** — 2.7% of the corpus. Their
entities, geography and every derived field come from corrupted text.
`University Hospital` reached the corpus as `U2>Ajniversity Hospital`, so the
gazetteer never matched it even though it holds `university hospital ->
Columbia` correctly. The detector found 11 of the 561 because it looked for
the markers its own decoder consumes; that is fixed separately, but the 561
already-enriched articles are not re-processed by fixing it.
