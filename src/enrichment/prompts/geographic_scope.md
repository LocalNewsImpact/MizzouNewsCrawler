### TASK: Classify the **Scope** of a local news article

You are an assistant that identifies the article's **geographic scope**: the level of the place the story is **about** — where its events happen, and whose community, government or institution it concerns.
Scope is the story's **subject**, not the reach of its effects. A story set in one town whose effects spread to neighboring places, a county or a service area is still about that town.

Choose **one** scope — the level of the place the story is about.

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
| `neighborhood_community` | About a single neighborhood, district, school, or hyperlocal community. | Street-level issues; school boundary debates; neighborhood conflicts; park changes. |
| `city_municipality` | About one city or town: its government, services, events, businesses, institutions or places. | Citywide policy, mayoral decisions, municipal services, city elections; a storm, closure or opening in the town; a town's clinic, park or school. |
| `regional` | A county, or multiple communities or counties within a broader geographic area (metro or non-metro). Includes a single county's government and programs, multi-county regions, tribal nations, river basins, and multi-state regions like the Upper Midwest. | County commission decisions; countywide programs; metro-wide transit; Northern Minnesota wildfires; Iron Range mining issues. |
| `statewide` | Impacts residents across the entire state. | State legislation, state programs, governor's actions, state agency decisions. |
| `national` | Impacts people across the United States; no specific local or state focus. | Federal elections; national economic trends; Supreme Court decisions (unless localized). |
| `international` | Impacts multiple countries or deals with global affairs; no specific U.S. or local focus. | Global conflicts; international markets; WHO guidelines; diplomatic issues. |
| `elsewhere_to_local` | A national or global trend, policy, or event **that directly affects the local area**. | Federal loan changes affecting MN graduates; global inflation hitting local stores; Canadian wildfire smoke impacting MN air. |
| `local_to_elsewhere` | A local action, innovation, discovery, or event with **impact beyond the local area**. | Mayo Clinic breakthrough; local court ruling shaping national precedent; Minnesota climate research used worldwide. |
| `other` | Does not clearly fit any category. | Meta stories about journalism; personal essays; ambiguous or mixed-scope content. |

### Rules

- **Choose only one scope** — the level of the place the story is about.
- **Mention is not subject.** If Congress is mentioned but the story is about a local program, the story is not national.
- **Choose the smallest scale** that contains the story's subject. Effects that reach further do not raise the scale.
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
- **A story set in one town is about that town, even when its effects reach
  past it.** An event, closure, opening, storm, project or institution in one
  town is `city_municipality` for that town, even when the story also names
  nearby communities, the county, a highway, or a service area that spans
  several counties. "Ellensburg reopens downtown after water main break" is an
  Ellensburg story even when it names the county and the interstate; "Colville
  hospital wins grant to expand care" is a Colville story whatever counties the
  hospital serves. Naming other places is mention, not a second subject.
- **A county agency acting in a town is about that town.** Deputies arresting
  someone in Fulton, or a county court hearing about a crime in one town, are
  stories about that town.
  The agency is the actor; the town is where the story happens.
- **`regional` is for a county or a wider area as the subject.** Use it when:
  - the story is about the county government's own business -- its budget,
    ordinances, commission decisions, countywide programs, elections, or the
    county government acting on its own property and facilities (a county park
    it buys or reopens, fees it sets at a county transfer station);
  - the story is set in the county but in no particular town;
  - the story is a county-wide event or institution -- a county fair or
    festival, a county chamber of commerce -- even when it is held in one town;
  - the story is local to two or more communities that share it equally --
    the same thing happening in each, such as food banks in two towns. Where
    the people involved are from is not a second community: a crash near
    Centerville whose driver lives in Ellington is a Centerville story;
  - the story is about a business, service or organization AS A WHOLE that
    has locations across several communities, wherever its headquarters is: a
    warning about a chain with stores across a metro area is `regional`. When
    the story is about what that organization is doing in one town -- a branch,
    a building, a grant or an expansion there -- it is about that town;
  - several communities share the story with no single one at its center; or
  - the subject is a river, basin, watershed or other system that crosses
    community lines.
  Never use it only because a one-town story mentions neighboring places.
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

#### Example 3b — One town, with effects beyond it
**Headline:** "Ellensburg reopens downtown after water main break"

```json
{
  "category": "city_municipality",
  "confidence": 0.9,
  "rationale": "The story is set in Ellensburg; the county and the interstate are mentioned, not a second subject."
}
```

#### Example 3c — A county as the subject
**Headline:** "Benton County commissioners approve $4 million for rural road repairs"

```json
{
  "category": "regional",
  "confidence": 0.92,
  "rationale": "A county government's decision applied across the county; no single town is the subject."
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
