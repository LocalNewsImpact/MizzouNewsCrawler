# Geographic grounding

Assigning a news article one central location, and a set of secondary
mentions, from two independent signals.

## 1. Architecture

A language model reads the article and proposes geography. A curated
gazetteer confirms or refuses each proposal. The gazetteer never
proposes.

The asymmetry is the design. A model's output carries no internal
indication of which claims are supported; on this corpus 17.2% of
recorded places were unsupported by the article. A gazetteer cannot read,
so it cannot distinguish a place a story is about from a place it merely
names — and when allowed to nominate a location unaided, 68.3% of its
proposals named a place absent from the article entirely.

Confirmation requires two signals to coincide. A noisy signal agreeing
with an independent one is evidence; the same signal alone is not.

```text
article ──> LLM ──────> proposed central place + mentions ──┐
        │                                                    ├──> gate ──> stored geography
        └──> spaCy ──> entity spans ──> gazetteer ──> places ─┘
```

## 2. Gazetteer

### 2.1 Sources

Five contributors, distinguished by a source column and unique on
`(state, source, source_id)`. Missouri:

| source | features | distinct names | geocoded |
|---|---|---|---|
| OSM ways | 18,487 | 14,600 | 16,000 |
| OSM nodes | 13,787 | 10,330 | 6,940 |
| NCES CCD | 5,695 | 5,193 | 5,695 |
| NCES PSS | 512 | 461 | 512 |
| generated stems | 114 | 114 | 114 |
| curated | 1 | 1 | 1 |

**OpenStreetMap POI extract.** Built offline from a Geofabrik state PBF,
filtered to named features whose tags fall in a category vocabulary, and
written as CSV. Broad and uneven: it supplies every category below, and
its quality varies with contributor attention. Coordinates come with the
feature; place and county are assigned afterwards by the Census geocoder.

**NCES Common Core of Data.** The federal public-school census, annual.
Supplies school name, street address, city, state, ZIP, latitude,
longitude and county FIPS per school. Authoritative and complete for
public K-12 — 2,473 Missouri schools — which is the gap OSM leaves.

**NCES Private School Universe Survey.** The private-school equivalent,
via the NCES school-locations service: name, city, state, coordinates and
county FIPS. 501 Missouri schools. Vintage lags CCD, so schools opened
recently are absent.

**Census place gazetteer.** Not a feature source. A static tab-delimited
file per state giving GEOID, name and interior point for every
incorporated place — 1,082 in Missouri. It converts a school's city
string into the place geoid the index answers with, and it is the
reference list against which a generated stem is tested for being a place
name (§3.3). Matching normalises saint forms: `St Louis`, `Saint Louis`
and `St.Louis` all resolve to the Census `St. Louis`, without which 474
of 2,974 schools fail to resolve.

**Census geocoder.** The `geographies/coordinates` endpoint, used to
assign place and county to a feature that arrives with coordinates but no
administrative geography — principally the OSM extract. Independent
cities are county equivalents: St. Louis city is `29510`.

**Generated and curated entries** are described in §3.3 and §3.4.

### 2.2 Categories

Every feature carries a category derived from its source: OSM tags map
through a category vocabulary, and survey records are `schools` by
construction. Missouri:

| category | features |
|---|---|
| schools | 11,163 |
| businesses | 6,756 |
| religious | 6,186 |
| landmarks | 4,003 |
| entertainment | 2,029 |
| government | 1,858 |
| transportation | 1,846 |
| sports | 1,418 |
| economic | 1,387 |
| healthcare | 1,252 |
| emergency | 698 |

The category is not decoration. Variant generation applies only to
`schools`, `religious`, `government`, `healthcare` and `emergency` —
categories in which a name denotes an institution whose location
identifies a story. Stemming a business or a transit stop yields a
surname or a town name. `businesses`, `landmarks`, `entertainment`,
`transportation`, `economic` and `sports` remain matchable but are not
stemmed.

### 2.3 Name index

Matching queries an index of `(state, name_norm) → place_geoid`, built by
counting the distinct Census places bearing each name.

**A name borne by more than one place resolves to nothing.** `First
Baptist Church` occurs in 55 Missouri places; it carries
`place_count = 55`, no geoid, and answers no query. This is the primary
control against confident error.

**An ungeocoded feature counts against its name.** `bethel church` has 52
Missouri features, 51 without a place and one resolving to Wildwood.
Counting only geocoded features makes the name appear unambiguous, and
every story naming a Bethel Church resolves to Wildwood. Ungeocoded
features add one to the count: their location is unknown, but their
existence is sufficient to deny the name a single answer.

## 3. Name handling

The string in the article and the string in the reference data are rarely
identical.

### 3.1 Normalisation is side-dependent

| side | function | affixes |
|---|---|---|
| gazetteer | `normalize_name` | **kept** |
| article | `lookup_keys` | **stripped** |

An affix belongs to a place's name and not to a sentence's grammar.
Stripping the possessive on the gazetteer side collapses `Love's` to
`love`, `Casey's` to `casey` and `Applebee's` to `applebee` — 335
Missouri names onto common words, after which the matcher fires on "love"
in prose. The leading article behaves identically: `The Hill` → `hill`.

On the article side the affix is noise: "the Kansas City Police
Department", "Kansas City's mayor".

### 3.2 Descriptions are not names

OSM's `name` tag frequently carries a description. The extract contains
features named `Basketball`, `Locker Rooms`, `The Track`, `Honor Roll`
and `High School football field`. Each compiles to a matcher pattern, so
the word matches in prose and proposes a city.

**A name whose every token denotes a kind of place is rejected.** `Fire
Station` is rejected; `Boone County Fire Protection District` is kept,
because `boone` is not generic. One distinctive token suffices. The
vocabulary is a curated list of ~167 facility, sport and fixture terms.

Two further rules: names shorter than three characters are rejected (a
feature named `A` produced 22,251 matches), as are names containing no
alphabetic character.

### 3.3 Variant generation

A registry name is not the printed form. Each institution contributes the
official name plus derived variants:

| official | derived |
|---|---|
| `MURIEL W. BATTLE HIGH SCHOOL` | `Battle High School` |
| `DAVID H. HICKMAN HIGH` | `Hickman High School` |
| `WARRIOR RIDGE ELEM.` | `Warrior Ridge Elementary` |
| `Southeast Missouri State University` | `Southeast Missouri` |
| `Southern Boone High School` | `Southern Boone` |

Rules: expand abbreviations, drop an honoured person's given names, drop
an honorific, complete `High` to `High School`, and remove the type word
to yield the **stem**.

A stem is rejected when it:

- **is a place name.** Schools are commonly named for their own town.
  `Poplar Bluff High School` stems to the town it is in; `St Peters
  Elementary`, a school in Joplin, stems to a city near St. Louis.
  Compared against the Census place list: 184 rejected, 107 kept.
- **is a single token.** `Battle High School` yields nothing. `Battle` is
  labelled PERSON 51 times in this corpus.
- **is wholly generic.** `Main Street Elementary`, `North Elementary`.
  Matched as a whole string, not as a prefix, so `Central Methodist` and
  `North Callaway` survive.

Variant generation applies only where the source guarantees structure — a
registry name always carries a type word and a distinctive token. Applied
to arbitrary OSM names it degrades: stripping honorifics, personal names
and legal suffixes across 20,651 names yields 150 variants used by
articles, of which the most frequent are `smith` (556 mentions),
`campbell` (540) and `truman` (144), derived from `Smith Co.` and
`Dr. X Campbell`. Constraining it to variants retaining a type word and
two tokens leaves 36 variants and 126 mentions, roughly half of them
collisions. It is therefore not applied generally.

### 3.4 Curated entries

Rules do not reach local shorthand. Missouri articles write `Tolton` 297
times and `Tolton Catholic High School` six; OSM holds `Father Tolton
Catholic High School`. Honorific stripping reaches the six. Reaching the
297 requires indexing a bare surname, which no automatic rule performs.

A curated entry records the name, the place, the author and a note. Three
are refused: a wholly generic name; a place the gazetteer has not
geocoded, since an entry may reference a known place but not create one;
and an entry without an author. Adding one re-counts that name alone
rather than rebuilding the state index.

## 4. Entity extraction

spaCy, with the gazetteer compiled into an `EntityRuler` ahead of the
statistical model.

**Patterns are strings.** `EntityRuler` routes a string to the
`PhraseMatcher` — a vocabulary trie, cost proportional to document length
— and a token-dict list to the `Matcher`, which is linear in pattern
count. Over 32,274 features and 20 articles: 0.3 ms against 892 ms per
article. The difference is invisible at the ~2,000 patterns of a
per-publisher gazetteer.

Single-token names retain a token pattern: `IS_LOWER: False` prevents a
feature named `Mobile` matching the word "mobile", and that condition is
not expressible as a string.

**`overwrite_ents=True`.** Otherwise a span already claimed by the
statistical model is retained: `Mizzou Arena` resolves as `Arena`/PERSON.
The same model labels `Columbia` as ORG 3,047 times and `REWRITTEN` as
ORG 1,726.

**Scope.** A source matches against its own state plus any border state
contributing at least 10% of its reachable POIs.

## 5. Model output

Per article, structured, each field carrying a confidence and a written
rationale:

- scope — hyperlocal, city, regional, statewide, national
- one central place, with a resolved geoid
- secondary mentions
- people and organisations, with role, affiliation and mention count
- classification — subject, topic, format, timeframe, user need

The central place arrives geocoded, so the gate evaluates a decision
rather than resolving a name.

## 6. Grounding rule

One function, called at both write sites, so the point claim and the
mention set cannot diverge on what qualifies.

A place is defensible when either holds:

1. **The article names it** — in body or headline, outside furniture, and
   outside a dateline that identifies only the newsroom.
2. **The article names an institution located in it.**

Clause 2 carries the system. Over 215 points designated on articles the
model classified as local:

| evidence available | accepted |
|---|---|
| article text alone | 1 |
| + OSM institutions | 32 |
| + federal school surveys | 49 |
| + generated short forms | 74 |

One article in 215 names its own city. Local reporting identifies a
school, a church or a fire district rather than a municipality, so the
completeness of institution data determines the system's recall.

**Datelines are treated asymmetrically.** A dateline matching the
publisher's city is furniture and is excluded; a dateline naming any
other place is evidence.

An earlier form of clause 1 required the place name alone. It removed 70
of 803 points whose article named an institution in the removed city.

## 7. Signal quality

### Gazetteer side

| control | effect |
|---|---|
| ambiguity rule | a name in >1 place resolves to nothing |
| description guard | rejected at build; dropped from the index on rebuild for states loaded under an older vocabulary |
| place names excluded as institutions | `Jefferson City → Jefferson City` is the article naming the place, not evidence about it — 15.5% of candidates in one sample |
| stem validation | rejected against the Census place list |

### Article side

**Corrupted text.** TownNews serves paywalled bodies ROT47-encoded. A
partial decode consumes the paragraph markers it matched while leaving
ciphertext outside them, so a detector keyed on those markers identifies
11 of 561 affected articles. The detector matches the residue instead —
the ROT47 encodings of surviving HTML, computed from the markup rather
than transcribed. `&amp;` encodes to `U2>Aj`, the reason `University
Hospital` appears in the corpus as `U2>Ajniversity Hospital`. Recall
98.8%; markers shorter than four characters are excluded because `&#`
encodes to `UR`, which occurs inside MISSOURI.

**Span boundaries.** A longer span subsuming an institution name matches
nothing. `Southeast Missouri State gymnastics` is one span; the index
holds `Southeast Missouri State University`. Unresolved.

**Entity labels are not used as a filter.** spaCy labels `George
Washington` PERSON and `Ameren Missouri` PERSON. The label is inferred;
the gazetteer category is curated.

### Excluded signals

| signal | reason |
|---|---|
| publisher's own city | places every story in the newsroom's town |
| proximity to the publisher | 87% of refused points fall within 20 miles; it does not discriminate |
| the model's knowledge of institutions | against NCES ground truth on 120 schools: 43% correct, 18% confidently wrong, 39% declined; failure mode is reading the school's name as the town (`Grandview High → Grandview`, actually Hillsboro) |

## 8. Operations on stored geography

Evidence improves after articles are enriched. Re-enrichment is not the
mechanism: given an unchanged prompt and profile, a second pass moved 34
of 167 points and demoted 32 from a city to its containing county —
variance exceeding the effect under measurement.

| command | direction | model calls |
|---|---|---|
| `enrich reground` | removes stored geography the text does not support | none |
| `enrich restore-points` | writes a point for a stored claim the gate now accepts | none |

Both are deterministic. `point_method` distinguishes a restored row from
a model-placed one; `point_support` records which clause admitted it.

Current totals: 89 points recovered — 71 on improved gazetteer data, 18
further after re-extraction exposed the new names as entity spans.

## 9. Limits

- **Span boundaries** (§7) — the principal residual cause of an unplaced
  local story.
- **Local shorthand** — `Cape Central`, `Tolton`; no registry holds these
  and no rule derives them safely. Curation only.
- **Higher education** — IPEDS is the CCD equivalent for colleges and is
  not loaded.
- **Unplaced remainder** — approximately 7% of articles classified local
  end without a central place, split about evenly between the model
  proposing none and the gate refusing what it proposed.
