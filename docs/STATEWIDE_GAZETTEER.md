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

1. **Geocode every feature.** `geocode-gazetteer --all`. 83,325 lookups at
   the observed rate is roughly four hours, about two with higher
   concurrency. The Census geocoder is free; concurrency stays modest.
2. **Build the statewide index** — one row per feature per state, with its
   place, and a name→places count so §3.1 is a lookup rather than a scan.
3. **Re-measure the short-name guards** (§3.3) against the wider pool
   before anything is rematched.
4. **Rematch** the 2.97M `article_entities` rows.
5. **Point the gate at it** — `repository.institution_places` reads the
   statewide index, and `EVIDENCE_LABELS` keeps §3.2.
6. **Re-run `enrich reground`.** It only deletes, so restore from the
   snapshot tables first and let the improved gate re-judge the corpus.

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

## 6. Related

- `src/enrichment/grounding.py` — the gate, and why each exclusion exists.
- `src/enrichment/gazetteer_places.py` — the lat/lon to Census place lookup.
- `src/enrichment/reground.py` — re-judging what was already written.
- [BACKFIELD_ENRICHMENT.md](BACKFIELD_ENRICHMENT.md) — the enrichment stage.
