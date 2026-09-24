# A nameplate is not a domain

`sources` has one row for two different things: a **domain we crawl** and a
**newspaper that exists**. Most of the time they coincide, so nothing complains.
Where they do not, every count drawn off the table is wrong and the error is
invisible.

**Nothing here is built.** This is a proposal, written after a day of
reconciling four lists against the corpus, and every case below is real.

## What the table cannot say today

### Several nameplates on one domain

`myleaderpaper.com` is one `sources` row named "Leader". Behind it the Missouri
Press directory and the Blue Book between them name the Arnold-Imperial Leader,
the Eureka Leader, the Jefferson County Leader and the West Side Leader — four
papers in Jefferson County, and we count one.

That is not rare. Folding the spelling variants away, **42 domains across the two
directories carry more than one nameplate**, and we hold 31 of them. A sample of
the unambiguous ones:

| Domain | Nameplates |
| --- | --- |
| `myleaderpaper.com` | Arnold-Imperial Leader, Eureka Leader, Jefferson County Leader, West Side Leader |
| `mainstreetnewsgroup.com` | Carrollton Democrat, Glasgow Missourian, Higginsville Advance, Lexington News |
| `threeriverspublishing.com` | Cuba Free Press, Saint James Press, Steelville Star-Crawford Mirror |
| `bentoncountyenterprise.com` | Benton County Enterprise, Cole Camp Courier, Lincoln New Era |
| `mycnews.com` | St. Charles Community News, St. Louis Community News |
| `standard-democrat.com` | New Madrid Weekly Record, Sikeston Standard-Democrat |
| `northmissouriannews.com` | Princeton Post-Telegraph, Unionville Republican |
| `maryvilleforum.com` | Grant City Times Tribune, Maryville Forum |
| `monroe-ralls.com` | Monroe County Appeal, Ralls County Herald-Enterprise |
| `clintondailydemocrat.com` | Clinton Daily Democrat, Windsor Review |

**What it costs.** A county-by-county comparison of the four lists puts Jefferson
County at 6 papers by the Blue Book, 6 by MPA, 2 by LNI — and 1 by us. The
shortfall is not missing coverage. It is one row standing for four papers. The
same arithmetic makes Lafayette look like a gap when the Higginsville Advance and
the Lexington News are both sections of `lafayettemonews.com`, which we already
crawl.

### A nameplate that moves, and a domain that dies

`lincolnnewsnow.com` was one site carrying three papers. It now serves only a
notice:

> We have launched new websites for The Lincoln County Journal, The Elsberry
> Democrat, and the Troy Free Press.

Three nameplates split out to `lincolncountyjournal.com`, `troyfreepress.com` and
`elsberrydemocrat.com`. We hold all three — but nothing records that they were
one site, so the Blue Book's printed URL for two of them looks simply wrong
rather than superseded.

The reverse happened to Main Street News Group. `mainstreetnewsgroup.com` 404s,
and the review marked all four of its nameplates dead. Two of them are not:
the Carrollton Democrat publishes at `carrolltondemocrat.com` with articles
through August 2026, and the Glasgow Missourian at `glasgowmissourian.com`.
**A dead group domain was read as four dead newspapers**, and the Carrollton
Democrat was absent from the dataset until 2026-09-24 because of it.

### A nameplate that is a section of another domain

`higginsvilleadvance.com` redirects to
`www.lafayettemonews.com/category/higginsville-advance/`. The nameplate is real,
its own domain is a signpost, and its articles live under a path on a domain we
already have. `sources.metadata.alternate_domains` cannot express this: it says
two hosts are the same site, not that a nameplate occupies part of one.

## What exists and why it is not enough

| | What it holds | Why it does not answer this |
| --- | --- | --- |
| `sources.canonical_name` | one name per domain | a domain with four nameplates has to pick one, and `Leader` is what four papers became |
| `sources.metadata.alternate_domains` | hosts that are the same site | symmetric and undated; cannot say "this nameplate, on this path, until this date" |
| `owner_groups` | owner string → group | ownership, not publication. Two papers can share an owner and be separate nameplates, or share a domain under different owners |

## The proposal

Two tables beside `sources`, which keeps its meaning: **a domain we crawl**.

### `nameplates`

One row per newspaper that exists, whether or not we can reach it.

| column | |
| --- | --- |
| `id` | |
| `name` | as its masthead reads |
| `city`, `county`, `fips` | where the newsroom is, geocoded from its office address |
| `status` | `publishing`, `print_only`, `replica_only`, `closed` |
| `first_seen`, `last_seen` | which readings of which directory carried it |

A nameplate with no domain is the point: the Osceola St. Clair County Courier and
the eight replica-only papers are newspapers that exist and that we cannot
collect. Today they can only be absent.

### `nameplate_domains`

Where a nameplate published, and when. One nameplate may have several rows; one
domain may carry several nameplates.

| column | |
| --- | --- |
| `nameplate_id`, `source_id` | |
| `path` | `/category/higginsville-advance/` where it is a section, else null |
| `from_date`, `to_date` | null `to_date` means current |
| `basis` | how this was established — `redirect`, `masthead_on_page`, `directory`, `decided` |
| `decided_by`, `decided_at` | |

`basis` matters for the same reason it does in `review/mopress.py`: a match
argued from a redirect is stronger than one argued from two directories
agreeing, and a reviewer weighing a conflict needs to see which they have.

Succession needs no third table. `lincolnnewsnow.com` closing is three
nameplates whose row on that domain gets a `to_date` and a new row on the new
one; the split and the merge are the same shape read in opposite directions.

## What this would have prevented today

- The Carrollton Democrat being absent because a **group** domain 404s.
- Jefferson and Lafayette counties reading as coverage gaps.
- "61 newspapers missing" when the honest number, counted as domains, was 35 —
  and, counted as nameplates we cannot reach, different again.
- Three hours spent working out whether `mycnews.com` is one newsroom or two.

## What it does not solve

Deciding that two spellings are one nameplate. "Cape Girardeau Southeast
Missourian" and "Southeast Missourian" are one paper; "Clinton Daily Democrat"
and "Windsor Review" are two. No rule separates those — it is the same judgement
the byline review already asks a person to make about a name, and it belongs in
the same queue.
