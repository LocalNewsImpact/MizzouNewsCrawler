### TASK: Classify the **Scope** of a local news article

You are an assistant that identifies the article's **geographic scope of impact** — the primary level at which the story's events, decisions, or effects matter.
Scope reflects **who is affected**, not who is mentioned, quoted, or referenced.

Choose **one** scope — the single **dominant** level of impact.

## Categories
- neighborhood_community
- city_municipality
- regional
- statewide
- national
- international
- elsewhere_to_local
- local_to_elsewhere
- other

## Scope definitions

| Label | Definition | Key Signals |
|-------|------------|-------------|
| `neighborhood_community` | Impacts a single neighborhood, district, school, or hyperlocal community. | Street-level issues; school boundary debates; neighborhood conflicts; park changes. |
| `city_municipality` | Impacts residents of an entire city or town. | Citywide policy, mayoral decisions, municipal services, city elections. |
| `regional` | Impacts multiple communities or counties within a broader geographic area (metro or non-metro). Includes multi-county regions, tribal nations, and multi-state regions like the Upper Midwest. | Metro-wide transit; Northern Minnesota wildfires; Iron Range mining issues. |
| `statewide` | Impacts residents across the entire state. | State legislation, state programs, governor's actions, state agency decisions. |
| `national` | Impacts people across the United States; no specific local or state focus. | Federal elections; national economic trends; Supreme Court decisions (unless localized). |
| `international` | Impacts multiple countries or deals with global affairs; no specific U.S. or local focus. | Global conflicts; international markets; WHO guidelines; diplomatic issues. |
| `elsewhere_to_local` | A national or global trend, policy, or event **that directly affects the local area**. | Federal loan changes affecting MN graduates; global inflation hitting local stores; Canadian wildfire smoke impacting MN air. |
| `local_to_elsewhere` | A local action, innovation, discovery, or event with **impact beyond the local area**. | Mayo Clinic breakthrough; local court ruling shaping national precedent; Minnesota climate research used worldwide. |
| `other` | Does not clearly fit any category. | Meta stories about journalism; personal essays; ambiguous or mixed-scope content. |

### Rules

- **Choose only one scope** — the level at which the story's *impact* is primarily felt.
- **Mention is not impact.** If Congress is mentioned but does not affect locals, the story is not national.
- **Choose the smallest scale** that accurately describes who is affected.
- Use `regional` for metro areas, multi-county regions, non-metro regions, multi-state regions, and tribal nations.
- Use `elsewhere_to_local` when the story's main dynamic is external forces affecting locals.
- Use `local_to_elsewhere` only when the local action **creates meaningful broader influence**, not merely symbolic attention.
- If the story is national or global with **no local impact**, use `national` or `international`.
- Use `other` when scope is unclear, meta, or does not map to geography.
- **A state event is the venue, not the impact.** A story about a team, school,
  athlete, student or business from a particular town competing in, placing at,
  or honored at a state tournament, state championship, state fair, state
  contest or state conference is about that town or school: use
  `neighborhood_community` or `city_municipality` (or `regional` when it is
  about teams from several counties). It is `statewide` only when the story is
  about the event or the state body itself -- the bracket, the association's
  rules, results across the whole state.
- **A name with the state in it is still in one place.** The University of
  Missouri and its teams (Mizzou, the Tigers) are in Columbia; Missouri State
  University is in Springfield; the Missouri State Fair is in Sedalia; a state
  park, prison or hospital is in its town. A story about the team, the campus,
  the fair or the facility is about that town -- `city_municipality` -- not
  `statewide`. "Mizzou forward will return for fourth season" and "Tiger
  baseball drops game to Lindenwood" are Columbia stories; "Country star to
  play the Missouri State Fair" is a Sedalia story.
- **A state official acting on named local places is about those places.**
  "Attorney general accuses 13 Kansas City hemp shops" is a Kansas City story;
  "MoDOT to close Route 5 bridge" is about the communities on Route 5. It is
  `statewide` only when the action applies across the state: a law, a rule, a
  statewide program, a budget, an election for statewide office.
- **The publication is in {publication}.** A state event or institution in
  the publication's own community is local news for it.
- **Statewide means statewide in the state the story is about.** A Kansas bill,
  a Kansas agency or a Kansas lawsuit reported by a Missouri outlet is
  `statewide` (for Kansas), not `regional` and not `elsewhere_to_local`, unless
  the story is about its effect on the outlet's own community.

### Few-shot examples

#### Example 1 — Neighborhood / Community
**Headline:** "Residents push back on proposed bike lanes in Linden Hills"

```json
{
  "category": "neighborhood_community",
  "confidence": 0.94,
  "rationale": "The impact is limited to a single neighborhood within the city."
}
```

#### Example 2 — City / Municipality
**Headline:** "Mayor proposes $2.3B Minneapolis budget with expanded youth programs"

```json
{
  "category": "city_municipality",
  "confidence": 0.93,
  "rationale": "The proposed budget affects residents across the entire city."
}
```

#### Example 3 — Regional
**Headline:** "New transit line will link multiple suburbs to downtown"

```json
{
  "category": "regional",
  "confidence": 0.91,
  "rationale": "The project spans several communities across the metro area."
}
```

#### Example 4 — Statewide
**Headline:** "Minnesota passes law raising minimum teacher salary statewide"

```json
{
  "category": "statewide",
  "confidence": 0.94,
  "rationale": "The policy applies across the entire state."
}
```

#### Example 4b — A local team at a state event
**Headline:** "Doniphan girls cruise in sectional rout of Potosi"

```json
{
  "category": "city_municipality",
  "confidence": 0.9,
  "rationale": "A state playoff game is the venue; the story is about the Doniphan team and its community."
}
```

#### Example 4c — A state-named institution
**Headline:** "Mizzou forward Trent Pierce will return for fourth season"

```json
{
  "category": "city_municipality",
  "confidence": 0.9,
  "rationale": "Mizzou's teams are in Columbia; the story is about Columbia's team, not the state."
}
```

#### Example 5 — National
**Headline:** "Supreme Court limits EPA authority in major environmental ruling"

```json
{
  "category": "national",
  "confidence": 0.92,
  "rationale": "The ruling has nationwide implications without a specific local focus."
}
```

#### Example 6 — International
**Headline:** "World Health Organization declares new global health emergency"

```json
{
  "category": "international",
  "confidence": 0.93,
  "rationale": "The story addresses a global issue with no specific local emphasis."
}
```

#### Example 7 — Elsewhere → Local
**Headline:** "Federal student loan changes leave Minnesota graduates uncertain"

```json
{
  "category": "elsewhere_to_local",
  "confidence": 0.92,
  "rationale": "A national policy imposes direct consequences on local residents."
}
```

#### Example 8 — Local → Elsewhere
**Headline:** "Mayo Clinic discovery could reshape cancer treatment nationwide"

```json
{
  "category": "local_to_elsewhere",
  "confidence": 0.95,
  "rationale": "A local development has influence beyond the region."
}
```

#### Example 9 — Other
**Headline:** "A behind-the-scenes look at how our newsroom covered election night"

```json
{
  "category": "other",
  "confidence": 0.70,
  "rationale": "Meta content without a clear geographic impact."
}
```

## Article text

{text}
