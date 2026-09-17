# Geographic grounding

Assigning a news article one central location and a set of secondary
mentions, by joining a curated gazetteer to a language model's output.

This document is written to be reimplemented. Each rule is given with the
failure it prevents, because the rules are not interchangeable and
several of the obvious alternatives are worse.

---

## 1. The problem both signals fail at

### 1.1 What a language model gets wrong

A model reads an article and returns places. Its errors are not random
and not flagged:

- **Fabrication.** It records a place the article never mentions. On this
  corpus, 17.2% of recorded places were unsupported by the article text.
- **Publisher bleed.** It resolves a story to the newsroom's own city
  because the dateline says so, regardless of where the events are.
- **Mention inflation.** Every place named anywhere — a comparison, a
  wire credit, a reporter's previous posting — is returned as though the
  story concerned it.

Nothing in the output separates these from correct answers. Confidence
scores do not: a fabricated place arrives with the same confidence as a
named one.

### 1.2 What a gazetteer gets wrong

A gazetteer knows that Smith-Cotton High School is in Sedalia. It cannot
read, so it cannot distinguish a story *about* the school from one that
merely names it, and it has no way to rank the places an article touches.

Allowed to nominate a location unaided, it fails in three characteristic
ways:

- **Junk names.** OpenStreetMap features genuinely named `Basketball`,
  `George Washington`, `FEMA`. A Greene County sheriff story resolves to
  St. Louis through a park bench.
- **Institutions that are elsewhere.** A Sedalia basketball story names
  the visiting school and resolves to Blue Springs.
- **Name collisions.** A Kennett church matches a same-named church at
  the other end of the state.

Measured directly: 68.3% of gazetteer-only proposals named a place absent
from the article entirely.

### 1.3 Why confirmation works when proposal does not

Confirming requires **two independent signals to coincide**: the model
names a place, *and* the article names an institution located there. Each
signal is noisy, but their errors are uncorrelated — a model fabricating
"Sedalia" has no reason to fabricate it on an article that happens to
name a Sedalia school.

The same signal alone is noise with a place attached. This is the
governing constraint:

> **The model proposes. The gazetteer confirms or refuses. The gazetteer
> never proposes.**

Everything below follows from keeping those roles separate.

```text
article ──> LLM ─────────> proposed central place + mentions ──┐
        │                                                       ├──> gate ──> stored
        └──> spaCy ──> spans ──> gazetteer index ──> places ────┘
```

---

## 2. Gazetteer

### 2.1 Sources

Assembled per US state, installed on demand when a dataset introduces an
unseen state. Five feature contributors, unique on
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
filtered to named features whose tags fall in a category vocabulary.
Broad, uneven, and the only source for most categories. Coordinates
arrive with the feature; place and county are assigned afterwards.

**NCES Common Core of Data.** The federal public-school census. Name,
address, city, state, ZIP, coordinates and county FIPS per school.
Authoritative and complete for public K-12.

**NCES Private School Universe Survey.** The private equivalent, via the
NCES school-locations service. Vintage lags CCD, so recently opened
schools are absent.

**Census place gazetteer.** Not a feature source. A static per-state file
of GEOID, name and interior point for every incorporated place — 1,082 in
Missouri. Two jobs: converting a school's city string into a place geoid,
and serving as the reference list against which a generated stem is
tested for being a place name (§4.4).

**Census geocoder.** `geographies/coordinates`, assigning place and
county to features that arrive with coordinates only. Independent cities
are county equivalents; St. Louis city is `29510`.

All sources are static files in object storage. A state install issues no
network request, so builds are reproducible and inputs cannot shift
underneath a corpus.

### 2.2 Why OSM alone is insufficient

OSM school coverage is contributor-dependent. The Missouri extract holds
3,759 names under `schools` and omits Battle High School, Smith-Cotton,
Warrior Ridge, Hickman and Rock Bridge.

This is not a cosmetic gap. §5 shows that the institution clause carries
almost the entire gate, so a missing school is a refused story. Adding
the federal surveys moved accepted points from 32 to 49 on a fixed sample
of 215; adding derived short forms moved it to 74.

**Higher education has no equivalent source loaded.** IPEDS is the CCD
analogue for colleges and remains unintegrated; universities arrive
through OSM with the same coverage risk.

### 2.3 Categories

Every feature carries a category: OSM tags map through a vocabulary,
survey records are `schools` by construction.

| category | features | stemmed |
|---|---|---|
| schools | 11,163 | yes |
| businesses | 6,756 | no |
| religious | 6,186 | yes |
| landmarks | 4,003 | no |
| entertainment | 2,029 | no |
| government | 1,858 | yes |
| transportation | 1,846 | no |
| sports | 1,418 | no |
| economic | 1,387 | no |
| healthcare | 1,252 | yes |
| emergency | 698 | yes |

The split is load-bearing. A name in `schools` or `healthcare` denotes an
institution whose location identifies a story. A name in `businesses` or
`transportation` does not, and stemming one yields a surname or a town —
`Smith Co.` → `smith`, a transit stop named `Jefferson City` →
`Jefferson City`.

### 2.4 The name index

Matching queries `(state, name_norm) → place_geoid`, built by counting
the distinct Census places bearing each name.

**Rule 1 — a name in more than one place resolves to nothing.** `First
Baptist Church` occurs in 55 Missouri places. It is present with
`place_count = 55`, no geoid, and answers no query.

This is the primary control against confident error, and it is why the
index is built by counting rather than by taking a first match. A
first-match index would answer every `First Baptist Church` with whichever
one was loaded first, and would be wrong 54 times in 55 without any
signal that it was guessing.

**Rule 2 — an ungeocoded feature counts against its name.** `bethel
church` has 52 Missouri features: 51 without an assigned place and one
resolving to Wildwood. Counting only geocoded features makes the name
look unambiguous, and every Missouri story naming a Bethel Church
resolves to Wildwood.

An ungeocoded feature's location is unknown, but its *existence* is
known, and that is sufficient to deny the name a single answer. It adds
one to the count rather than its own number — the system knows there are
others, not where they are.

---

## 3. Entity extraction and its cleanup

The gazetteer reaches the gate through spaCy. What arrives needs
filtering at three levels.

### 3.1 The matcher

The gazetteer is compiled into an `EntityRuler` placed ahead of the
statistical model.

**Patterns must be strings.** `EntityRuler` routes a string to the
`PhraseMatcher` — a vocabulary trie, cost proportional to document length
— and a token-dict list to the `Matcher`, which is linear in pattern
count. Over 32,274 features and 20 articles: **0.3 ms against 892 ms per
article.** At the ~2,000 patterns of a per-publisher gazetteer the
difference is invisible; at statewide scale it is the difference between
a 90-minute corpus pass and a 3-day one.

Single-token names keep a token pattern, because `IS_LOWER: False`
prevents a feature named `Mobile` matching the word "mobile" and that
condition is not expressible as a string.

**`overwrite_ents=True`.** Otherwise a span the statistical model has
already claimed stays claimed, and the curated name loses to the guess:
`Mizzou Arena` resolves as `Arena`/PERSON. The same model labels
`Columbia` ORG 3,047 times and `REWRITTEN` ORG 1,726 times. Between a
curated gazetteer entry and `en_core_web_sm`, the gazetteer wins.

**Scope.** A source matches against its own state plus any border state
contributing ≥10% of its reachable POIs. Without the threshold, a single
spillover POI opens an entire neighbouring state's index to a publisher
that never covers it.

### 3.2 The gazetteer is the controlled vocabulary

spaCy emits a great deal that is not a place: `Story`, `Please`,
`Featured Local Savings`, `NCAA`, mangled spans, boilerplate. None of it
is filtered by inspection. It is filtered by **joining `entity_norm`
against the name index** — a span that does not match a curated name
contributes nothing.

This inverts the usual arrangement. spaCy is not asked to decide what is
a place; it is asked to produce candidate strings, and the gazetteer
decides. The consequence is that **extraction recall matters and
extraction precision does not.** Junk spans are free; missed spans are
not.

### 3.3 Entity labels are not trusted

Filtering candidates by spaCy's label is the obvious next step and does
not work. The label is inferred, not curated:

- `George Washington` → PERSON (it is a park feature)
- `Ameren Missouri` → PERSON (it is a utility)
- `Jefferson City` → GPE (it is a transit stop resolving to the town)

Restricting to ORG and FAC removes `George Washington` and also removes
`Ameren Missouri`. Measured across a judged corpus, every rule built on
labels or categories cost more correct answers than noise it removed.
**The gazetteer category is curated data; the spaCy label is a guess.**
Where they disagree, neither is authoritative, so neither is used as a
filter — the ambiguity rule (§2.4) and the name guard (§4.2) do the work
instead.

---

## 4. Names

This is where most of the accuracy lives. The string in the article and
the string in the reference data are rarely identical, and the naive
fixes are actively harmful.

### 4.1 Normalisation is side-dependent

Two functions, deliberately different:

| side | affixes |
|---|---|
| gazetteer | **kept** |
| article | **stripped** |

An affix belongs to a place's name and not to a sentence's grammar.

Stripping the possessive on the **gazetteer** side collapses `Love's` to
`love`, `Casey's` to `casey`, `Applebee's` to `applebee` — 335 Missouri
names onto common English words, after which the matcher fires on "love"
in ordinary prose. The leading article is the same trap one word earlier:
`The Hill` → `hill`, `The Ridge` → `ridge`, both then matching a
boil-water advisory.

On the **article** side the same affix is noise: a story writes "the
Kansas City Police Department" and "Kansas City's mayor", and neither
affix is part of the name.

A single symmetric normaliser cannot satisfy both. This is the first
thing to get right in a reimplementation.

### 4.2 A description is not a name

OSM's `name` tag is where mappers put descriptions. Real Missouri
features: `Basketball`, `Locker Rooms`, `The Track`, `Honor Roll`,
`High School football field`, `Restrooms`, `Public Storage`.

Each compiles to a matcher pattern, so the word matches in prose and
proposes a city. `basketball` → Springfield on an article about
sports-betting advice; `honor roll` → North Kansas City on an elementary
school honour roll.

**A name whose every token denotes a kind of place is rejected.** `Fire
Station` goes; `Boone County Fire Protection District` stays, because
`boone` is not generic. One distinctive token suffices — the rule is
deliberately conservative, since rejecting a real name costs recall
permanently while admitting a weak one costs only a gate refusal.

The vocabulary is ~167 facility, sport, room and fixture terms. Two
further rules sit underneath: names shorter than three characters are
rejected (a feature named `A` produced 22,251 matches, 48.3% of all
matches before the guard existed), as are names with no alphabetic
character (`1327`, `99+`).

**The guard runs at index build and again on rebuild**, so a state loaded
under an older vocabulary is corrected rather than staying wrong. The
underlying features are retained — entity match history references them —
and only the index row is dropped.

### 4.3 Variants: the printed form

A registry name is not what a newspaper prints. This is the single
largest recall lever in the system.

| official | printed |
|---|---|
| `MURIEL W. BATTLE HIGH SCHOOL` | Battle High School |
| `DAVID H. HICKMAN HIGH` | Hickman High School |
| `ROCK BRIDGE SR. HIGH` | Rock Bridge High School |
| `WARRIOR RIDGE ELEM.` | Warrior Ridge Elementary |
| `Father Tolton Catholic High School` | Tolton Catholic High School |
| `Southeast Missouri State University` | Southeast Missouri |
| `Southern Boone High School` | Southern Boone |

Loading the official string alone matches none of the right-hand column,
which is equivalent to not loading the source at all. Each institution
therefore contributes the official name **plus** every form a reporter
would write:

1. **Expand abbreviations** — `ELEM.` → `ELEMENTARY`, `SCHL` → `SCHOOL`,
   `SR. HIGH` → `HIGH SCHOOL`, `JR. HIGH` → `JUNIOR HIGH SCHOOL`,
   `ACAD.`, `CTR.`, `INT.`, `PRI.`
2. **Drop an honoured person's given names** — a middle initial marks the
   pattern: `MURIEL W. BATTLE HIGH SCHOOL` → `BATTLE HIGH SCHOOL`
3. **Drop an honorific** — `Father`, `St.`, `Dr.`, `Mother`, `Bishop`
4. **Complete the type word** — `Hickman High` → `Hickman High School`
5. **Take the stem** — remove the type word entirely (§4.4)

2,974 Missouri schools yield 6,207 index names by this route.

### 4.4 The stem, and why it needs three guards

The stem — `Southern Boone High School` → `Southern Boone` — is what
sports copy actually prints. Southern Boone appears in 287 Missouri
articles as the bare stem.

It is also the most dangerous derivation in the system, and is rejected
under three conditions:

**It must not be a place name.** Most schools are named for their own
town. `Poplar Bluff High School` stems to the town it sits in, which
locates nothing new. Worse, `St Peters Elementary` is a school in
**Joplin** and stems to a city near **St. Louis** — a confident answer
300 miles wrong. Every stem is tested against the Census place list:
**184 rejected, 107 kept.**

The comparison normalises saint forms, because the Census writes `St.
Peters` and the stem is `st peters`. Without that normalisation the
rejection silently fails.

**It must not be a single token.** `Battle High School` yields nothing.
`Battle` is labelled PERSON 51 times in this corpus; `Clark` is a filling
station; `Woods` is a business. A one-word stem is a surname more often
than an institution.

**It must not be wholly generic.** `Main Street Elementary`,
`North Elementary` — these say *which* school in town, not which town.
Matched as a whole string, never as a prefix: a prefix rule rejects
`Central Methodist` and `North Callaway`, which are real names.

### 4.5 Why variants are not generated generally

The same rules applied to arbitrary names degrade badly. Measured over
20,651 Missouri index names against every ORG and FAC span in the corpus:

| rule | variants articles use | mentions unlocked |
|---|---|---|
| strip honorifics, persons, legal suffixes, articles | 150 | 2,549 |
| the same, requiring a type word and two tokens | 36 | 126 |

The unconstrained rule's most productive variants are `smith` (556
mentions), `campbell` (540) and `truman` (144), derived from `Smith Co.`
and `Dr. X Campbell`. **A name stripped to a surname stops being an
institution.** Constrained, the yield collapses to 126 mentions of which
roughly half are collisions — `mary catholic church` and `paul catholic
church` from stripping `St.`, of which Missouri has dozens each.

Variant generation is therefore applied **only where the source
guarantees structure**: a federal registry name always carries a type
word and a distinctive token, so stripping the honoured person from
`MURIEL W. BATTLE HIGH SCHOOL` leaves something that is still a school
and still distinctive. OSM names carry no such guarantee.

The general lesson for a reimplementation: **derive variants from the
schema of the source, not from the surface form of the string.**

### 4.6 Curation

No rule reaches local shorthand. Missouri articles write `Tolton` 297
times, `Tolton Catholic` 25 times and `Tolton Catholic High School` six.
Honorific stripping reaches the six. Reaching the 297 requires indexing a
bare surname, which §4.4 forbids automatically and for good reason — but
a person who knows the beat can assert it and take responsibility.

A curated entry records name, place, author and note. Three things are
refused: a wholly generic name; a place the gazetteer has not geocoded,
since an entry may reference a known place but never create one; and an
entry without an author. Adding one re-counts that name alone.

Expect to need this. The share of local institutions that no registry
holds is small but not zero, and it is concentrated in exactly the
high-frequency names local sports copy uses.

---

## 5. The grounding rule

One function, called at both write sites, so the central place and the
mention set cannot diverge on what qualifies.

A place is defensible when either holds:

**Clause 1 — the article names it.** In body or headline, outside
furniture, and outside a dateline that identifies only the newsroom.

**Clause 2 — the article names an institution located in it.**

### 5.1 Why clause 2 carries the system

Over 215 points designated on articles the model classified as local:

| evidence available to the gate | accepted |
|---|---|
| article text alone | **1** |
| + OSM institutions | 32 |
| + federal school surveys | 49 |
| + generated short forms | 74 |

**One article in 215 names its own city.** Local reporting identifies a
school, a church, a fire district or a courthouse and assumes the reader
knows the town. A grounding rule that requires the place name is
therefore not a strict version of the right rule — it is the wrong rule,
and it deletes correct geography. An earlier form of clause 1 that
required the name alone removed 70 of 803 points whose article named an
institution in the removed city.

This is the central finding for anyone reimplementing: **the institution
index is not a refinement, it is the mechanism.** Budget accordingly —
completeness of institution data determines recall far more than prompt
quality does.

### 5.2 Datelines are asymmetric

A dateline matching the publisher's own city is furniture and is
excluded. A story in the Montgomery Standard is not thereby about
Montgomery City.

A dateline naming **any other place** is evidence. A Kirksville dateline
on a Columbia station's story says the story is in Kirksville.

The asymmetry is the whole value: the same token is noise or signal
depending on whether it duplicates the publisher's location.

### 5.3 Furniture

Matches are clause-bounded. A place name occurring inside a reporter's
biography, a subscription prompt, a photo credit or a wire attribution is
not the story's geography. The gate tests occurrences against clause
boundaries within a bounded window rather than accepting any occurrence
anywhere in the body.

---

## 6. Keeping both signals clean

### 6.1 Gazetteer side

| control | prevents |
|---|---|
| ambiguity rule (§2.4) | a name in >1 place answering with one |
| ungeocoded features counted (§2.4) | 52 Bethel Churches reading as one |
| description guard (§4.2) | `basketball` proposing Springfield |
| place names excluded as institutions | `Jefferson City → Jefferson City`, circular; 15.5% of candidates in one sample |
| stem validation (§4.4) | `St Peters Elementary` proposing a city 300 miles away |

### 6.2 Article side

**Corrupted text.** TownNews serves paywalled bodies ROT47-encoded. A
partial decode consumes the paragraph markers it matched while leaving
ciphertext outside them — so a detector keyed on those markers finds 11
of 561 affected articles. The detector must match the **residue**: the
ROT47 encodings of surviving HTML, computed from the markup rather than
transcribed. `&amp;` encodes to `U2>Aj`, which is why `University
Hospital` appears in the corpus as `U2>Ajniversity Hospital` and matches
nothing. Recall 98.8%. Markers shorter than four characters are excluded
because `&#` encodes to `UR`, which occurs inside MISSOURI.

**Span boundaries.** A longer span subsuming an institution name matches
nothing: `Southeast Missouri State gymnastics` is one span, while the
index holds `Southeast Missouri State University`. Unresolved, and the
principal residual cause of an unplaced local story.

### 6.3 Signals deliberately not used

| signal | measurement that excludes it |
|---|---|
| publisher's own city | places every story in the newsroom's town — the original defect |
| proximity to the publisher | 87% of *refused* points also fall within 20 miles; it cannot discriminate. Usable as a doubt flag, not as confirmation |
| spaCy entity labels | `George Washington` and `Ameren Missouri` are both PERSON (§3.3) |
| unconstrained variant generation | top yields are `smith`, `campbell`, `truman` (§4.5) |
| the model's own knowledge of institutions | against NCES ground truth on 120 schools: 43% correct, 18% confidently wrong, 39% declined. Failure mode is reading the school's name as the town — `Grandview High` → Grandview, actually Hillsboro |

The last is worth stating plainly: **the model knows famous institutions
and guesses at the long tail**, and local news is almost entirely long
tail. Its calibration is good — it declines 39% of the time rather than
guessing — but the 18% it answers confidently and wrongly is precisely
what a gate exists to catch.

---

## 7. Operating on stored geography

Evidence improves after articles are enriched: a school source is added,
a variant rule is extended. Two deterministic passes apply the improvement
without re-running the model.

| command | direction | model calls |
|---|---|---|
| `enrich reground` | removes stored geography the text does not support | none |
| `enrich restore-points` | writes a point for a stored claim the gate now accepts | none |

**Re-enrichment is not the mechanism.** Given an unchanged prompt and
profile, a second pass moved 34 of 167 points and demoted 32 from a city
to its containing county. The run-to-run variance exceeds the effect
being measured, so a change cannot be evaluated by re-enriching and
diffing.

The claim is already stored with its geoid; only the gate's answer has
changed. `point_method` distinguishes a restored row from a model-placed
one, and `point_support` records which clause admitted it, so a reviewer
can separate a place the story named from one an institution implied.

Recovered to date: 89 points — 71 on improved gazetteer data, 18 further
after re-extraction exposed the new names as entity spans.

---

## 8. Reproducing this for another state

In order, because each step depends on the last:

1. **Build the OSM extract** from the state PBF, filtered to the category
   vocabulary. This is the base layer and the only source for most
   categories.
2. **Load the federal school surveys.** CCD and PSS. Without these the
   institution clause is starved and the gate's recall collapses — the
   32-to-49 step in §5.1.
3. **Generate variants and stems** for institution categories only, with
   all three stem guards (§4.4) and the Census place list to test against.
4. **Geocode**, then **build the name index** by counting distinct places
   per name, including ungeocoded features in the count.
5. **Compute source scope** — own state plus border states above the 10%
   threshold.
6. **Extract entities** with the gazetteer as string patterns and
   `overwrite_ents` on.
7. **Enrich**, then gate.

Two properties to preserve above all: the gazetteer must never propose,
and the name index must answer nothing when a name is ambiguous. Every
serious error this system has produced came from violating one of them.

---

## 9. Limits

- **Span boundaries** (§6.2) — the main residual failure.
- **Local shorthand** — `Cape Central`, `Tolton`. Curation only.
- **Higher education** — IPEDS not loaded; universities rely on OSM.
- **Private school vintage** — PSS lags, so recently opened schools are
  absent.
- **Unplaced remainder** — approximately 7% of articles classified local
  end without a central place, split about evenly between the model
  proposing none and the gate refusing what it proposed.
