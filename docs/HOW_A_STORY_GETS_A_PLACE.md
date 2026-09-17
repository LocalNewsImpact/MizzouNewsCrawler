# How a story gets a place

Written for engineers who know NER, gazetteers and LLM pipelines, and who
have never seen this codebase.

The problem is deceptively narrow: given a local news article, decide
where it happens. Not which places it mentions — where it *is*. A school
board story that names four towns is about one of them. A high school
basketball roundup names two schools and belongs to whichever one hosted.

The pipeline answers this with two systems that know nothing about each
other, and a rule that requires them to agree.

---

## 1. Why two systems

A language model reads an article and says "this is about Sedalia." It is
right most of the time and confidently wrong the rest, and nothing in its
output distinguishes the two cases. Measured on this corpus, 17.2% of the
places a model recorded were not supported by the article at all.

A gazetteer knows that Smith-Cotton High School is in Sedalia. It cannot
read, so it cannot tell you that *this* article is about the school rather
than merely naming it — and asked to nominate a place on its own, it
produces nonsense: a Greene County sheriff story located to St. Louis via
a park bench tagged `George Washington`.

Neither signal is trustworthy alone. The design is therefore asymmetric:

> **The model proposes. The gazetteer confirms or refuses. The gazetteer
> never proposes.**

Confirmation requires two independent signals to coincide. A noisy signal
that agrees with an independent one is evidence; the same signal alone is
noise with a place attached.

---

## 2. The gazetteer

### 2.1 Sources

Per US state, assembled once and installed on demand when a dataset
introduces a state the corpus has not seen. Missouri, as of this writing:

| source | features | what it is |
|---|---|---|
| OpenStreetMap POI extract | 32,274 | every named node and way in the state, categorised |
| NCES CCD | 5,000-odd | public K-12 schools, federal survey |
| NCES PSS | ~1,200 | private schools, federal survey |
| generated short forms | 114 | see §3.3 |
| added by a curator | 1 | see §3.5 |

Plus two reference files that are not features: the **Census place
gazetteer** (name → GEOID for every incorporated place in the state) and
the **Census geocoder** (`geographies/coordinates`) for assigning a
lat/lon to a place and county.

Everything is static. The build fetches once per state and writes CSVs to
object storage; installing a state reads those files and makes no network
request of its own. This matters operationally — a gazetteer build is
reproducible and free — and it matters for correctness, because a source
that can change under you cannot be reasoned about.

### 2.2 Why OSM alone is not enough

OSM coverage is whatever volunteers entered. Missouri's OSM extract held
3,759 names under `schools` and did not contain Battle High School,
Smith-Cotton, Warrior Ridge, Hickman or Rock Bridge — the schools local
stories are actually about. A missing school is not a cosmetic gap: it is
the difference between placing a story and refusing it, for reasons §4
makes clear.

The federal surveys are authoritative and complete for K-12. They do not
cover higher education, which is why universities still arrive through
OSM.

### 2.3 The name index

Features are the raw material; the thing queried at match time is a
**name index**: `(state, name_norm) → place_geoid`, built by counting how
many distinct Census places bear each name.

Two rules govern it.

**A name borne by more than one place locates nothing.** `First Baptist
Church` occurs in 55 Missouri places. It is in the index with
`place_count = 55` and no geoid, and therefore answers no question. This
is the single most important guard against confident error.

**A feature with no place assigned still counts against its name.** This
is subtle and cost us: `bethel church` has 52 features in Missouri, 51 of
them ungeocoded and one resolving to Wildwood. Counting only the geocoded
one made the name look unambiguous, so every Missouri story naming a
Bethel Church resolved to Wildwood with total confidence. Unplaced
features now add one to the count — we do not know *where* they are, only
that they are other features wearing the same name, which is enough to
deny the name a single answer.

---

## 3. Names

The hardest part of this system is not matching. It is that the name in
the article and the name in the reference data are rarely the same string.

### 3.1 Normalisation is asymmetric

Two functions, deliberately different:

- **Gazetteer side** (`normalize_name`): case, punctuation and whitespace
  only. **Affixes are kept.** Stripping the possessive turned `Love's`
  into `love`, `Casey's` into `casey` and `Applebee's` into `applebee` —
  335 Missouri names collapsing onto common words, after which the matcher
  fired on the word "love" in ordinary prose. The leading article is the
  same trap one word earlier: `The Hill` became `hill`.

- **Article side** (`lookup_keys`): affixes stripped. An article writes
  "the Kansas City Police Department" and "Kansas City's mayor"; the
  affix is noise *there* and part of the name *here*.

An affix is part of a place's name and not part of a sentence's grammar.
Which side you are on decides what to do with it.

### 3.2 A description is not a name

OSM's `name` tag is where mappers put descriptions. The extract contains
features genuinely named `Basketball`, `Locker Rooms`, `The Track`,
`Honor Roll` and `High School football field`. Each becomes a matcher
pattern, so the word "basketball" anywhere in prose proposes a city —
Springfield, on an article about sports-betting advice.

The guard: **a name whose every token describes a kind of place is a
description, not an identity.** `Fire Station` goes; `Boone County Fire
Protection District` stays, because `boone` is not generic. One
distinctive token is enough to keep a name. The vocabulary is a curated
list of ~167 facility, sport and fixture words.

Two earlier rules sit underneath it: names under three characters are
rejected (a POI called `A` fired on every "a" in an article — 22,251
matches), as are names with no alphabetic character at all.

### 3.3 Short forms

A registry name is not what a newspaper prints.

```
MURIEL W. BATTLE HIGH SCHOOL      →  Battle High School
DAVID H. HICKMAN HIGH             →  Hickman High School
WARRIOR RIDGE ELEM.               →  Warrior Ridge Elementary
Southeast Missouri State University → Southeast Missouri
Southern Boone High School        →  Southern Boone
```

Every institution contributes the official name plus the forms a reporter
would write: abbreviations expanded, the honoured person's given names
dropped, `High` completed to `High School`, and — the largest win — the
**stem**, the name with its type word removed.

The stem rule is dangerous and is constrained accordingly. A stem is
refused if it:

- **is itself a place name.** Most schools are named for their own town.
  `Poplar Bluff High School` stems to `Poplar Bluff`, which locates
  nothing new, and `St Peters Elementary` — a school in Joplin — stems to
  a city near St. Louis. 184 stems refused on this rule against 107 kept.
- **is one word.** `Battle High School` yields nothing, which is correct:
  `Battle` is labelled PERSON 51 times in this corpus.
- **is generic as a whole.** `Main Street Elementary`, `North Elementary`.
  Matched whole, not as a prefix — `Central Methodist` and `North
  Callaway` are real names.

### 3.4 What was measured and rejected

Generating variants for *every* institution, not just those with known
structure, was measured over 20,651 names against every ORG and FAC span
in the corpus:

| rule | variants articles use | mentions unlocked |
|---|---|---|
| strip honorifics, persons, legal suffixes, articles | 150 | 2,549 |
| the same, requiring a type word and two tokens | 36 | 126 |

The unconstrained rule's top results are `smith` (556 mentions),
`campbell` (540) and `truman` (144) — surnames from `Smith Co.` and
`Dr. X Campbell`. A name stripped to a surname stops being an
institution. Constrained, it is too small to matter and still half wrong.

The rule survives only where the source guarantees the structure: a
federal registry name always carries a type word and a distinctive token.
OSM names carry no such guarantee.

### 3.5 Curation

No rule covers everything. Missouri articles write `Tolton` 297 times and
`Tolton Catholic High School` six; OSM holds `Father Tolton Catholic High
School`. Stripping the honorific reaches the six. Reaching the 297 means
indexing a bare surname, which no rule should do automatically.

So there is a curated path — one entry, with who added it and why — and
the tool refuses three things: a name whose every word is generic, a town
the gazetteer has not geocoded (an entry may point at a place the corpus
knows, never invent one), and an entry with nobody's name on it. Adding
one re-counts that single name rather than rebuilding the state.

---

## 4. Entity extraction

spaCy, with the gazetteer loaded as an `EntityRuler` in front of the
statistical model.

**Patterns are strings, not token dictionaries.** `EntityRuler` routes a
string pattern to the `PhraseMatcher` — a trie over the vocabulary,
costing what the document costs — and a list of token dicts to the
`Matcher`, which is linear in the number of patterns. Measured on 32,274
features over 20 articles: **0.3 ms per article against 892 ms**, a
2,661× difference that stayed hidden while gazetteers were per-publisher
and about 2,000 patterns.

Single-token names keep a token pattern, because `IS_LOWER: False` is
what stops a POI called `Mobile` firing on the word "mobile", and that is
a token-level condition a string cannot express.

**`overwrite_ents=True`.** Without it a span the statistical model had
already claimed stays claimed: `Mizzou Arena` came back as
`Arena`/PERSON. The same model files `Columbia` as ORG 3,047 times and
`REWRITTEN` as ORG 1,726, so its claims are not the ones to defer to.

**Scope.** A source matches against its own state plus any border state
supplying at least 10% of its reachable POIs. A Kansas City publisher
gets Kansas; a Springfield one does not.

---

## 5. What the model produces

Per article, structured output with a rationale for each decision:

- **scope** — hyperlocal, city, regional, statewide, national
- **a central place** — one location, with a geocoded geoid
- **mentions** — every other place the story names
- **people and organisations** — with role, affiliation and mention count
- classification fields (subject, topic, format, timeframe, user need),
  each with a confidence and a written justification

The central place is the claim this document is about. The model writes
it with a resolved geoid, so what reaches the gate is not a name to be
looked up but a decision to be checked.

---

## 6. The grounding gate

One function, called identically at both write sites so the point claim
and the mention set cannot drift apart on what counts.

**A place is defensible when the story's own reporting gets you there:**

1. **The article names it** — in body or headline, outside furniture, and
   outside a dateline that only says where the newsroom is; **or**
2. **The article names an institution that is in it.**

Clause 2 is the point. Naming Tolton Catholic High School locates a story
in Columbia; naming Westminster College locates one in Fulton. That is
induction from evidence in the story, and it is what the pipeline should
keep. The first version of the rule required the place *name* and deleted
it — 70 of the 803 points a backfill cleared had an institution sitting in
the very city that was removed.

**Datelines are handled asymmetrically and on purpose.** A dateline
matching the publisher's own city is furniture: a story in the Montgomery
Standard is not thereby about Montgomery City. A dateline naming
*anywhere else* is a real signal — a Kirksville dateline on a Columbia
station's story says the story is in Kirksville.

**Why the institution clause carries the weight.** Over 215 points the
model designated on stories it had itself classified as local, the gate
accepted:

```
text alone, no institutions      1
+ OSM institutions              32
+ federal school surveys        49
+ generated short forms         74
```

**One of 215** is supported by the article naming its own city. Local
journalism does not say where it is; it says which school, which church,
which fire district. The institution clause is not a nicety bolted onto a
name check — it is doing nearly all of the work, which is why the
completeness of the institution data is the system's central quality
problem.

---

## 7. Clean signals on both sides

The gate is only as good as what it reads. Both inputs are defended
explicitly.

### On the gazetteer side

- **Ambiguity** — a name in more than one place answers nothing (§2.3).
- **Descriptions** — rejected at index build and, for states loaded under
  an older vocabulary, dropped from the index on the next rebuild (§3.2).
- **Place names as institutions** — `Jefferson City → Jefferson City` is
  the article naming the place, not evidence about it. 15.5% of candidates
  in one measurement.
- **Bad stems** — refused against the Census place list (§3.3).

### On the article side

- **Corrupted text.** TownNews serves paywalled bodies ROT47-encoded.
  Where the decoder half-succeeds it consumes its own markers, so a
  detector looking for them found 11 of 561 affected articles — 2%
  recall. The detector now looks for the *residue*: the ROT47 encodings of
  the HTML that survives. `&amp;` encodes to `U2>Aj`, which is why
  `University Hospital` reached the corpus as `U2>Ajniversity Hospital`
  and matched nothing. 98.8% recall, and the markers are computed from the
  markup rather than transcribed.
- **Span boundaries.** spaCy extracts what it extracts; a longer span that
  swallows the institution name matches nothing. This is unsolved and is
  the main residual cause of a local story going unplaced.
- **Entity labels are not trusted.** Filtering candidates by spaCy's label
  was measured and rejected: `George Washington` comes back PERSON and so
  does `Ameren Missouri`. The label is a guess; the gazetteer category is
  curated data.

### What is not used, and why

- **The publisher's own city.** It would place every story in the
  newsroom's town — the original defect.
- **Proximity.** Measured: 87% of refused points are also within the
  publisher's 20-mile radius, so it cannot discriminate. It is a plausible
  *doubt* signal and a useless *confirmation* one.
- **The model's own knowledge of institutions.** Asked for the city of 120
  Missouri schools with NCES as ground truth: 43% correct, 18% confidently
  wrong, 39% declined. It reads the school's name as the town —
  `Grandview High → Grandview` when the school is in Hillsboro. Good
  calibration, unusable precision.

---

## 8. Operating on stored data

Two passes exist because the evidence improves after articles are
enriched, and re-enriching is the wrong tool: asked the same question
twice with the same prompt and profile, the model moved 34 of 167 points
and demoted 32 from a city to the county around it. The churn is larger
than any effect being measured.

- **reground** re-reads stored geography and removes what the article does
  not support. It only removes.
- **restore-points** reads a claim the model already made, asks the gate
  once, and writes the point where the answer is now yes. It asks the
  model nothing.

Both are deterministic. `point_method` records that a row was written this
way, and `point_support` records which clause kept it, so a reviewer can
tell a place the story named from a place an institution implied.

A recent measurement of the second: 71 points recovered on improved
gazetteer data, and 18 more after re-extraction made the new names
available as entity spans — 89 in total, at no model cost.

---

## 9. What this does not solve

- **Span boundaries.** `Southeast Missouri State gymnastics` is one span
  and matches nothing, though `Southeast Missouri State University` is in
  the index.
- **Local shorthand.** `Cape Central`, `Tolton` — names no registry holds
  and no rule can safely derive. These need curation.
- **Higher education coverage.** IPEDS is the equivalent of CCD for
  colleges and has not been loaded.
- **The unplaced remainder.** About 7% of stories the pipeline itself
  calls local end without a central place: roughly half because the model
  proposed nothing, half because the gate refused what it proposed.
