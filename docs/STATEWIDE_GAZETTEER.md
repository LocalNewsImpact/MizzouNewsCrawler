# A statewide gazetteer for verifying induced geography

The enrichment model infers a story's location from institutions the story
names. "A senior at Mexico High School" locates a story in Mexico;
"Southeast Missouri State gymnastics" locates one in Cape Girardeau. That
induction is wanted — it reasons from evidence in the article — and it is
not the fabrication `src/enrichment/grounding.py` exists to stop.

The gate verifies it by asking the gazetteer where each named institution
is. This document states why the gazetteer cannot answer that question in
its current shape, what to build instead, and the rules a match has to
obey so the new shape does not introduce failures of its own.

Every figure here was measured against production on 2026-09-15.

---

## 1. Why the per-publisher gazetteer cannot verify anything

The gazetteer is built per source, within a radius:

| | |
|---|---|
| rows | 558,540 |
| distinct OSM features | 83,325 |
| copies of each feature | 6.7 |
| distinct sources | 247 |
| maximum `distance_miles` | 22.2 |

**The radius makes the evidence circular.** Every row is within 22 miles of
one publisher, so *any* match resolves to somewhere near that publisher. A
story naming an Aldi matches the Aldi in the publisher's own town — not
because the story is about that town, but because that is the only Aldi in
the table for that source. Using it as evidence launders the
publisher-market bias the gate exists to stop.

This is not hypothetical. Of 37,566 articles carrying institution evidence,
1,262 rested entirely on a `PERSON`-labelled match, and the matches
included `Cracker Barrel` → St. Joseph and `T.J. Maxx` → St. Joseph. Both
are chains. Both resolved to the publisher's city by construction.

**The radius also costs recall.** A story about a town 30 miles from its
publisher gets no institution evidence at all, however distinctively it
names a school or a courthouse there.

**And 85% of the table is duplication** — the same feature stored once per
nearby source, which is why the table is half a million rows for 83,325
real places.

**The scope is enforced at match time, not only at build time.** That is
the line the redesign turns on:

```python
# src/pipeline/entity_extraction.py
def get_gazetteer_rows(session, source_id, dataset_id):
    filters = []
    if source_id:
        filters.append(Gazetteer.source_id == source_id)
    if dataset_id:
        filters.append(Gazetteer.dataset_id == dataset_id)
    if not filters:
        return []
```

An article's entities are matched only against its own publisher's slice,
so "Mizzou Arena → Columbia" is invisible to any article whose publisher is
more than 22 miles from it. This is also why the rematch in §4 is not
optional: every one of the existing 73,330 matches was made under the
narrow scope.

Entities themselves are extracted inline during article extraction
(`_run_article_entity_extraction`, spaCy `en_core_web_sm` plus an
`EntityRuler`), stamping `articles.entities_extracted_at`, so they exist
before enrichment reads them.

## 2. What to build

One row per OSM feature per state, geocoded to a Census place.

```
dedupe            558,540 rows  ->  83,325 features (osm_type + osm_id)
geocode           lat/lon -> place_geoid, place_name, county_geoid
                  (src/enrichment/gazetteer_places.py, already built)
match             entities against the state's features, not the source's
verify            grounding.grounded() reads the result
```

Deduplicated, of 62,478 distinct names:

| | |
|---|---|
| resolve to exactly one place | 24,249 |
| ambiguous — 2 or more places | 1,255 |
| no place known (not yet geocoded) | 36,974 |

## 3. Matching rules

These are the rules. Each exists because of a specific, measured failure.

### 3.1 A name that resolves to more than one place is not evidence

The core rule, and it replaces every chain heuristic. Statewide, a chain
name resolves to dozens of places and therefore locates nothing:

| name | places |
|---|---|
| walmart supercenter | 149 |
| pizza hut | 140 |
| safeway | 82 |
| u s bank | 77 |
| aldi | 72 |
| the church of jesus christ of latter-day saints | 68 |

A name is usable **only** when the state's features place it in exactly one
Census place. `Westminster College` qualifies. `Aldi` disqualifies itself,
with no list of chain brands to maintain and no judgement call.

This also retires the label restriction in §3.2 as a *chain* defence: the
extractor files `Cracker Barrel` as `PERSON`, and under this rule it fails
on ambiguity rather than on its label.

### 3.2 Only labels that can carry a place

`ORG`, `FAC`, `GPE`, `LOC`. Not `PERSON`, `NORP` or `EVENT`.

Ambiguity does not catch everything a person's name does: `Ali` matched an
`ALDI`, and a surname matching a POI named after that family resolves to
one place and would otherwise pass. Keep both rules; they fail different
things.

### 3.3 Word-bounded matching, and a minimum name length

On 2026-08-28, 48.3% of entity matches were on names of two characters or
fewer, and 67,770 junk matches were purged (PR #484). A statewide candidate
pool is larger than a per-source one, so the same defect costs more here
than it did then.

- Match on word boundaries. `Union` must not match inside `Unionville`.
- Require a minimum length and reject single tokens that are also common
  words. The guards from #484 apply unchanged and must be re-measured
  against the wider pool before the rematch is accepted.

### 3.4 State is part of the key

MO, VT and WA are separate datasets. Springfield exists in all three, and
so do Columbia, Washington and Fulton. Match an article's entities only
against the features of the article's own state, taken from the
publication's state rather than inferred.

### 3.5 An unmatched entity is not a refusal

A name the gazetteer does not know produces no evidence and no verdict. It
must not be recorded as a failed match or counted against the article:
`Houck Fieldhouse` is a real SEMO building the gazetteer lacks — it has
`Houck Stadium` — and `Southeast Missouri State` was never extracted as an
entity at all. Gaps upstream are gaps, not negative evidence.

### 3.6 Evidence supports a place; it never supplies a point on its own

Grounding decides whether a place the model claimed may be recorded. It
does not mint geography. An institution match with no corresponding model
claim adds nothing to the record.

## 4. Order of work

1. **Load the states.** §10 — from the GCS extracts, on demand, keyed by
   `(state, osm_type, osm_id)`.
2. **Geocode every feature.** `geocode-gazetteer --all`. 83,325 lookups is
   roughly four hours at the observed rate, about two with higher
   concurrency. The Census geocoder is free; concurrency stays modest.
3. **Build the name→places count** so §3.1 is a lookup rather than a scan.
4. **Fix normalisation** (§8.2) and **re-measure the name guard** (§8.4)
   against the wider pool. Both before anything is rematched.
5. **Switch the matcher to exact-only** (§8.1) and scope it by state (§9).
6. **Rematch** the 2.97M `article_entities` rows.
7. **Point the gate at the gazetteer category, not spaCy's label** (§8.3).
8. **Re-run `enrich reground`.** It only deletes, so restore from the
   snapshot tables first and let the improved gate re-judge the corpus.

Steps 4 and 5 are the ones that can silently make things worse, and both
are measurable before they ship: a rematch on a sample, compared against
the current matches, says what changed and in which direction.

## 4a. Better sources than OSM for institutions

Verified 2026-09-15 against the live services; Missouri counts are actual,
not estimates.

| source | MO rows | carries | access |
|---|---|---|---|
| NCES CCD public schools | 2,483 | lat/lon **and `county_code`** | Education Data API, no key |
| NCES CCD districts | 567 | address | same API |
| IPEDS institutions | 151 | `city`, `county_name` | same API |
| CMS Hospital General Information | 120 | name, address, city, zip | data.cms.gov API |
| **total** | **3,321** | | |

Against 27,729 OSM features for Missouri, of which schools (3,357) and
healthcare (1,321) are the categories these supersede.

**The value is not volume.** CCD is complete by definition for public
schools, and it carries `county_code`, so the county rung needs no
geocoding and the place rung is one lookup with the code in
`gazetteer_places.py`. IPEDS carries `county_name` and would supply
Southeast Missouri State University. District names matter on their own:
local news names districts constantly and OSM does not model them.

Use these as an authoritative layer OVER OSM rather than a replacement.
OSM keeps the categories they do not cover -- businesses, religious,
landmarks, sports venues -- which is most of the table.

**Do not plan on HIFLD.** The HIFLD Open portal was decommissioned on
2025-08-25. The Data Rescue Project mirrored its layers to DataLumos and
SeerAI hosts a Parquet copy on source.coop, but those are static 2025
snapshots rather than a maintained source. Fire stations, police, EMS and
courthouses have no live federal replacement; hospitals do, through CMS.

**NCES private schools (PSS) are not in the Education Data API** -- it
serves CCD, IPEDS and CRDC. PSS needs a direct bulk download from NCES.

**Overture Maps was considered and rejected** for this purpose. Its places
theme is denser than OSM, but at an estimated 300,000-500,000 rows for
Missouri it is a fifty-fold increase for breadth this gate does not need:
the failures measured here are institutions, not businesses, and a denser
business layer mostly adds ambiguous chain names that §3.1 discards.

## 4b. What the change actually does, measured before shipping

Step 4 of §4 says the rematch is measurable on a sample before it ships.
Run 2026-09-16 over the first 12 scoped sources, 219,272 stored entity
rows:

| | |
|---|---|
| matched today (per-source gazetteer, fuzzy at 0.85) | 2,658 |
| matched by the new rules (statewide, exact, scoped) | **5,313** |
| old matches the new rules CLEAR | 685 |

**Recall roughly doubles while the errors go.** Dropping the similarity
threshold costs nothing because `normalize_name` recovers what it was
papering over, and the statewide scope finds what a 22-mile slice could
not — "Mizzou Arena" is now visible to every publisher in Missouri, not
only those within 22 miles of it.

The 685 cleared are the ones that must not survive: "St. Louis City"
filed under St. Louis County, the Kansas City Police Department under
North Kansas City's.

Guard check against the wider pool, same run: 0 of 106,652 loaded
features fail `is_matchable_gazetteer_name` (the guard runs at load), and
6,554 of 83,286 (state, name) keys sit on more than one feature — led by
`chevron` (368 features), `shell` (355), `phillips 66` (258) and
`safeway` (251). Those are what §3.1 discards, and they are chains, which
is the rule working.

## 5. What this does not fix

The ceiling on verifying induction is set upstream, not by the gazetteer:

| label | matched | total | rate |
|---|---|---|---|
| FAC | 11,387 | 95,082 | 12.0% |
| ORG | 39,721 | 1,058,005 | 3.8% |
| GPE | 15,591 | 573,544 | 2.7% |
| LOC | 828 | 54,204 | 1.5% |

An institution the extractor never emits cannot be matched however good the
gazetteer is. The SEMO gymnastics article produced 21 entities — `Ohio
State`, `Central Michigan`, `NCAA Regionals`, `Houck Fieldhouse` — and not
`Southeast Missouri State`. Statewide matching does not reach that; entity
extraction does.

That is a per-article miss, NOT a coverage gap. Extraction runs on
essentially everything: of 20,521 enriched articles, 20,509 carry at least
one entity and only 12 carry none. One of those 12 is a KOMU gymnastics
story whose induced place — Columbia, from "Mizzou" — the gazetteer could
have confirmed outright, since it holds 57 Mizzou features including Mizzou
Arena in Columbia. The limit is therefore the MATCH rate within articles
that do have entities, which is what §2 and §3 address, and not extraction
coverage. The 12 empty articles want a re-run of `entity-extraction`, which
is a different job from this one.

## 7. What is there now, reviewed

| file | role |
|---|---|
| `scripts/populate_gazetteer.py` (1,985 lines) | geocodes a publisher, queries Overpass within 20 miles, writes rows stamped `dataset_id` / `source_id` / `host_id` |
| `scripts/build_osm_poi_extract.py` | builds a STATEWIDE CSV from a Geofabrik `.osm.pbf` using the same 61 tag filters |
| `OSM_POI_CSV` | makes the builder serve from a local CSV instead of Overpass |
| `src/pipeline/entity_extraction.py` | spaCy `en_core_web_sm` + an `EntityRuler`; `get_gazetteer_rows` scopes candidates; `_score_match` decides |
| `src/utils/gazetteer_names.py` | the matchability guard: length ≥ 3 and at least one letter |
| `src/cli/commands/gazetteer.py` | `populate-gazetteer` |
| `src/cli/commands/gazetteer_geocode.py` | `geocode-gazetteer` |

Read by: `repository.institution_places` (the grounding gate),
`utils/byline_cleaner.py` (organisation names, to filter bylines), and
`reporting/county_report.py` + `cli/commands/pipeline_status.py` (over
`article_entities`). `pipeline/publisher_geo_filter.py` and
`pipeline/enhanced_wire_filtering.py` build their own in-memory publisher
gazetteers from source location data — a different thing, not this table.

**The statewide extracts already exist.** `gs://mizzou-osm-extracts/poi/`
holds missouri (32,925 POIs), washington (50,481), kansas (18,325) and
vermont (6,763), built 2026-08-28. Statewide Missouri is only 19% more
features than the current per-publisher build's 27,729, because 247
publishers' 20-mile radii already cover most of the populated state. **The
gain is not more data. It is scope, ambiguity detection, and 6.7× less
storage.**

## 8. Matching: exact only, normalised first, and blind to spaCy's labels

### 8.1 Drop fuzzy matching

`_score_match` accepts `fuzz.ratio >= 0.85`. Exact hits are 72.0% of the
73,330 matches; the fuzzy band is 26.3% and holds two different things:

| entity | matched to | score | count | |
|---|---|---|---|---|
| `St. Louis City` | St. Louis **County** | 0.857 | 206 | different jurisdiction |
| `the Kansas City Police Department` | **North** Kansas City PD | 0.941 | 286 | different municipality |
| `Cardinals` | `Cardinal` | 0.941 | 802 | team → unrelated POI |
| `Marshall` | `Marshalls` | 0.941 | 257 | → a retail chain |
| `Kansas City` | `Q Kansas City` | 0.917 | 218 | city → a business |
| `Kansas City's` | `Kansas City` | 0.917 | 463 | *a possessive* |
| `Jefferson City's` | `Jefferson City` | 0.933 | 177 | *a possessive* |

The first five are wrong. The last two are normalisation failures that
should never have reached a scorer. Statewide the pool grows from a few
hundred candidates to tens of thousands, so every one of these gets more
likely, not less.

Exact matching also makes the `len(gazetteer_rows) < 50000` fallback guard
dead code — which is just as well, because **Washington statewide is 50,481
POIs**, over that line, so the guard would silently give Washington
exact-only matching while Missouri got fuzzy. A per-state behaviour split
nothing would have reported.

### 8.2 Normalise before matching, not after failing to match

`Kansas City's` → `Kansas City` and `Jefferson City's` → `Jefferson City`
are 640 matches that only needed a possessive stripped. Normalisation must
handle, on both sides:

- trailing possessive, straight and curly: `'s`, `’s`
- a leading article: `the`
- punctuation and case, as now

Those become exact matches and stop depending on a scorer at all.

### 8.3 Ignore spaCy's labels

The statistical model has no ground truth; it guesses a label from token
shape and context, and at `en_core_web_sm` it guesses badly. Across 2.9M
rows the most frequent `ORG` values include `Trump` (6,715), `House`
(4,375), `State` (3,279), `Columbia` (3,047 — a place), `story` (2,999) and
`REWRITTEN` (1,726 — wire boilerplate). `GPE` includes `Mo.` (19,206) and
`ST` (5,060).

So `EVIDENCE_LABELS` in `repository.py` is weak protection: it filters on
exactly the field that is unreliable. **Use the gazetteer's own `category`
instead**, which is deterministic — `GAZETTEER_CATEGORY_MAPPINGS` in
`entity_extraction.py` already maps eleven OSM categories to a type.

This is safe because the `EntityRuler` compiles every gazetteer name into an
exact token pattern and injects it into the pipeline. A known institution is
matched exactly, by name, with no statistical judgement involved. **The
evidence path does not need the NER model at all**; the model exists to
discover unknown entities, which is a different job and can stay as it is.

### 8.4 Strengthen the name guard

`is_matchable_gazetteer_name` requires length ≥ 3 and one letter. Against a
per-publisher slice that sufficed. Against a state it does not: it admits
`Union`, `Liberty`, `Salem`, `City Hall`, `Post Office`, `Dollar General`.

§3.1's one-place rule carries most of this — a name in many places is
discarded — but a name that is generic AND happens to occur once in the
state would pass. Reject names that are a single common word, and re-measure
the guard against the statewide pool before anything is rematched (§4 step
3).

## 9. Scope: the publisher's state, plus a border within reach

A dataset is a coverage list, not a location list. `resolve_source_state`
and `tests/test_gazetteer_state_resolution.py` already record why: the
Mizzou dataset legitimately holds KMBZ (Mission, KS) and Dos Mundos
(Overland Park, KS), because the Kansas City metro spans the line — which is
why `kansas.csv` is in the bucket. And 896 of 901 Vermont sources arrive
with no state at all, so guessing one is forbidden.

The scope for a source is therefore:

1. the source's own state, from `resolve_source_state` — never guessed; a
   source with no state resolvable is skipped with a reason, as now;
2. plus any state whose border falls within that source's coverage radius.

Computed once per source and STORED, so the scope is explicit and
auditable rather than recomputed per article. A Washington publisher then
reads Washington, and never the Missouri gazetteer or eighteen others.

### 9.1 What the scope is computed from, and what it cannot reach

A source's own 20-mile OSM build already answered "what is within reach";
joined to the state-keyed features, the answer carries a state. Measured
2026-09-16 over 246 sources with a build: 198 reach exactly one state, 48
reach two.

**The threshold is 10%, and the distribution chose it.** Secondary states
divide cleanly — 23 at 20% or more (Dos Mundos is 45% Kansas, Fox4KC
40%), 7 more at 10-20%, then a single state in the 5-10% band and 17
below 5%, several at one POI. `auroraadvertiser.net` touches Kansas by a
single POI; admitting that hands a Missouri weekly the whole
17,997-feature Kansas gazetteer.

`datasets.metadata.default_state` fills a gap where a source has no state
of its own — that is `resolve_source_state`'s existing contract. Only
Mizzou declared one; WSU-Washington-State now does too, because those 38
sources are all in Washington.

**VT-Community-News must NOT.** Its 901 sources are student and community
papers from around the country — `thedepauw.com`, `oudaily.com`,
`loyolamaroon.com`, `umassdtorch.com` — and of them 7 carry a city, 5 a
state and 3 a ZIP. The dataset is named for the initiative studying them,
not for where they sit. Setting a default of VT on 2026-09-16 scoped 896
national outlets to the Vermont gazetteer; it was reverted the same
session.

So those 901 sources have no resolvable state and are scoped to NOTHING,
which is the safe reading of an empty scope and matches what they get
today: the per-source builder skipped them for the same reason. Giving
them entity matching needs locations, not a cleverer default.

## 10. Loading a state on demand

The extract for a state is downloaded and installed when a source in that
state is first seen, not ahead of time.

1. Look for the state in the statewide gazetteer. If present, done.
2. Otherwise fetch `gs://mizzou-osm-extracts/poi/<state>.csv` and load it.
3. If the bucket does not have it, build it from the Geofabrik PBF with
   `build_osm_poi_extract.py` and upload — a one-time cost per state.
4. Geocode the new rows to Census places (`geocode-gazetteer`), which is
   what §2 needs and what the one-place rule in §3.1 counts over.

Loads are idempotent and keyed by `(state, osm_type, osm_id)`.

## 11. What this did to the tests

31 test files referenced the gazetteer. What actually happened, as
opposed to what was predicted here before the work:

| file | outcome |
|---|---|
| `test_gazetteer_state_resolution.py` | untouched — §9 depends on exactly this behaviour, and a guess made against it on 2026-09-16 was reverted the same day |
| `test_gazetteer_name_guard.py` | untouched; extended by `test_gazetteer_name_normalisation.py` |
| `pipeline/test_entity_extraction.py` | two scoring tests rewritten. `test_score_match_returns_best_fuzzy_match` became `test_score_match_refuses_a_near_miss`, and a second was added for the real case: "st louis city" must not match "st louis county". `test_attach_gazetteer_matches_handles_direct_and_fuzzy` became `..._takes_the_exact_name_only`. |
| `test_a_county_must_be_a_county.py` | untouched |
| `test_gazetteer_integration.py` | untouched — it exercises the per-source path, which survives |

**`get_gazetteer_rows` was NOT replaced.** The prediction here was that a
test asserting it filters on `source_id` is asserting the defect. In the
event the per-source path survives as a fallback for a source with no
recorded scope, so those tests still describe live behaviour and stand.
What was removed is the thing that made the path dangerous: `_score_match`
no longer has a similarity threshold, so even the legacy path cannot
produce a 0.85 match. Leaving a threshold live on a second path is a
hazard whether or not that path currently runs.

New files: `test_gazetteer_name_normalisation.py`,
`pipeline/test_a_gazetteer_the_whole_state_shares.py`,
`pipeline/test_a_source_reaches_only_its_own_states.py`,
`pipeline/test_matching_is_exact_and_scoped.py`,
`pipeline/test_the_ruler_is_compiled_once.py`,
`pipeline/test_rematching_what_was_already_matched.py`,
`enrichment/test_the_gate_asks_the_name_index.py`,
`enrichment/test_a_poi_knows_its_place.py`.

## 12. Related

- `src/enrichment/grounding.py` — the gate, and why each exclusion exists.
- `src/enrichment/gazetteer_places.py` — the lat/lon to Census place lookup.
- `src/enrichment/reground.py` — re-judging what was already written.
- [BACKFIELD_ENRICHMENT.md](BACKFIELD_ENRICHMENT.md) — the enrichment stage.
