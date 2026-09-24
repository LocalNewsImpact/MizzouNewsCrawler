# A newsroom belongs to a network

`sources.owner` says who owns a domain. It is one string, it is legal, and it
answers a question nobody is asking. The question the corpus keeps asking is
**who commonly shares bylines**, and ownership answers that wrongly in both
directions.

**Nothing here is built.** This is a proposal, written from a day of reconciling
byline rulings against the corpus, and every case below is real. It follows
[A nameplate is not a domain](A_NAMEPLATE_IS_NOT_A_DOMAIN.md) and depends on it.

## What exists

`owner_groups` maps a normalised owner to a group, and `byline_review.owner_group`
reads it. Its own docstring says what it is for — "the cross-owner test" — which
is not ownership. It is an answer to *should I be surprised that this byline
appears here*.

The table holds **three rows**, all one group:

| owner_key | group |
| --- | --- |
| `missourianassociation` | University of Missouri |
| `missourischooljournalism` | University of Missouri |
| `universitymissouri` | University of Missouri |

One owner key maps to one group. That is the limit this proposal is about.

## Ownership is the wrong axis

### It over-groups

KCUR is the University of Missouri-Kansas City. STL Public Radio is the
University of Missouri-St. Louis. KBIA and KOMU are the University of Missouri.
One system, four newsrooms, and no byline traffic between the Columbia ones and
the other two — they are separate NPR member stations on separate campuses.

### It under-groups

Six Missouri NPR member stations, six different owners:

| station | owner |
| --- | --- |
| KBIA | University of Missouri |
| KCUR | University of Missouri-Kansas City |
| STL Public Radio | University of Missouri-St. Louis |
| KSMU | Missouri State University |
| KRCU | Southeast Missouri State University |
| KXCV | Northwest Missouri State University |

Five NBC affiliates, five owners: KSDK (Tegna), KSHB (Scripps), KY3 (Gray),
KQTV (News-Press & Gazette), KOMU (University of Missouri).

### One newsroom holds several memberships at once

KOMU is owned by the University of Missouri, is an NBC affiliate, and is part of
the Missouri School of Journalism newsroom group with KBIA and the Columbia
Missourian. `owner_key -> group_key` holds one of those three.

## It is owner, and affiliations of any type

Two facts, not a hierarchy.

**Owner** is exactly one, legal, and already a column.

**Affiliations** are many and typed, with no tier among them. There is no level
at which NPR sits above NBC; a station holds both and they mean different things.

| affiliation | type | why ownership cannot say it |
| --- | --- | --- |
| NBC, CBS, ABC, Fox | broadcast network | KOMU is NBC and owned by a university |
| NPR | public radio | six members, six owners |
| States Newsroom | national nonprofit network | separate nonprofits per state |
| Missouri Press Association | press association | membership, nothing more |
| Mission Broadcasting / Nexstar | operating agreement | legally separate, operationally one |

"Chain" is not on that list because it collapses into owner: Gray owns KY3,
Nexstar owns fox4kc. What remains is what ownership genuinely cannot express.

## AFFILIATION DOES NOT CLASSIFY A STORY

This is the constraint that keeps the model honest, and the easiest one to get
wrong.

Kansas Reflector content republished in the Missouri Independent **is still
wire** for the Missouri Independent. Both are States Newsroom. The shared
affiliation explains why the copy is there; it says nothing about whether the
Independent reported it.

One domain, one network, three verdicts:

| story on `missouriindependent.com` | verdict | origin |
| --- | --- | --- |
| Steph Quinn, Missouri statehouse | local | Missouri Independent |
| Sherman Smith | wire | Kansas Reflector |
| `/repub/` national roundups | wire | States Newsroom national desk |

The corpus makes the same point from the other side. We hold two States Newsroom
nodes — `missouriindependent.com` (731 bylined articles) and
`washingtonstatestandard.com` (76). They share **zero bylines**. The Washington
sample is thin and this is not proof, but membership plainly does not produce
byline traffic on its own.

So an affiliation does two jobs, and neither is classification:

1. It stops the cross-owner signal spending a reviewer on a byline whose
   appearance is already explained.
2. It suggests where the home newsroom is.

**The reporter's home newsroom is the strong signal, not the network.** Sherman
Smith belongs to the Kansas Reflector; that one fact settles all 18 of his
Missouri copies, and no amount of network structure settles any of them.

## The proposal

Two tables beside `sources`, which keeps its meaning and its `owner` column.

### `affiliations`

One row per thing a newsroom can belong to.

| column | |
| --- | --- |
| `id` | |
| `key` | normalised, as `owner_key` normalises an owner |
| `name` | NBC, NPR, States Newsroom, Missouri Press Association |
| `type` | an open vocabulary — `broadcast`, `public_radio`, `network`, `association`, `operating_agreement` |
| `note` | |

`type` is a label, not a rank. Nothing sorts by it; the cross-owner test may
weigh types differently, and that weighting belongs in the test, not the schema.

### `source_affiliations`

Which newsroom belongs to what, and when.

| column | |
| --- | --- |
| `source_id`, `affiliation_id` | |
| `from_date`, `to_date` | null `to_date` means current |
| `basis` | how this was established, as `nameplate_domains.basis` does |
| `decided_by`, `decided_at` | |

**Dated, because affiliations change and this table is already wrong.** KCTV5 and
KMOV are recorded as Meredith, four years after Gray bought Meredith's stations.
An undated membership cannot record that without destroying the fact that it was
true in 2020.

### `owner_groups` becomes one case of this

A group is an affiliation of type `owner`. The three University of Missouri rows
migrate unchanged and `owner_group()` keeps its behaviour; it gains the ability
to answer for a station that holds three memberships.

## What this changes about syndication credit

Credit is per-story and points at a **newsroom**. Not a domain, and not a
network.

- Not a network: a Columbia Missourian story republished by KOMU is real
  syndication between two Mizzou newsrooms. Rolled up to the University of
  Missouri it disappears.
- Not a domain: the Columbia Missourian is three `sources` rows —
  `columbiamissourian.com`, `www.columbiamissourian.com` and
  `columbiamissourian.com/boonecountyjournal`, which is the Boone County Journal,
  a nameplate on a path. Credit keyed to a domain splits three ways.

So the credit column points at `nameplates.id`, not `sources.id`. The Kansas
Reflector settles it: it is the home newsroom of 18 wire stories in the Missouri
corpus and it has no `sources` row at all, because we do not crawl it. A
nameplate exists whether or not we can reach it. That is what the table is for.

**A guard the backfill needs.** "Every wire story carrying this byline takes the
byline's home newsroom as its origin" would stamp the 16 `/repub/` roundups on
`missouriindependent.com` with origin = Missouri Independent, on the Missouri
Independent. The home newsroom's own domain is excluded from the rule.

## What it does not solve

Deciding which newsroom a byline belongs to. Sherman Smith's home is the Kansas
Reflector and his largest Missouri footprint is the Dexter Statesman, which
republishes him eighteen times over. Counting articles picks the wrong answer.
It is the same judgement the byline review already asks a person to make, and it
belongs in the same queue.

## Data this would need cleaned first

Any grouping keyed on the owner string inherits these:

| | |
| --- | --- |
| `Gray Media` / `Gray Television` | two spellings, one owner |
| `Meredith Corportation` / `Meredith Local Media` | a typo, and stale since 2021 |
| `Nothwest Missouri State University` | typo |
| `ky3.com` / `www.ky3.com` | two source rows, two owner spellings, one station |
