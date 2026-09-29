# The Missouri outlet registry

`src/lookups/mo_outlet_registry.csv` is every Missouri news outlet any of our
lists knows about, one row per outlet, located well enough to map. It is built
by `scripts/build_mo_outlet_registry.py` and rebuilt whenever a list or the
sources table changes.

## Where the rows come from

| List | File | Carries |
| --- | --- | --- |
| Our sources | production `sources`, dataset Mizzou-Missouri-State | canonical owner, county, status, March article count |
| Missouri Press Association | `datadesk/data/sources/mopress-2026-08-22.json` | street address, county, website |
| SOS Blue Book 2025-2026 | `src/lookups/mo_bluebook_newspapers_2025_2026.csv` | street address, website |
| Northwestern LNI 2025 | `src/lookups/mo_lni_*_2025.csv` | county and FIPS, no address |
| 2025 working sheet | `src/lookups/mo_working_urls_2025.csv` | closure and e-edition notes only |

**Only the registry is in this repository**, which is public. Every input
above, and a reviewer's corrections and additions below, stays local
(git-ignored under `src/lookups/mo_*`): they are other people's data or working
notes. The builder reads them from a working copy that holds them; the
registry it writes is the one file committed.

**Datadesk imports it from a bucket, not from this repository.** `--publish`
uploads each rebuild to
`gs://mizzou-news-maps-data/registry/mo_outlet_registry.csv`, and datadesk's
`manage.py import_outlet_registry` reads it from there, so a rebuild reaches
the map without a pull request. A reviewer's word on what an outlet is --
replica, print, merged, a duplicate -- is a `status` event on the outlet's
page in datadesk, laid over every import (datadesk `docs/OUTLET_EVENTS.md`).

**Our sources table is canonical** for any outlet it holds. The lists supply
what it does not: addresses, and outlets we do not hold.

## Identity

`outlet_id` is a UUID and never changes.

- An outlet we hold carries its `sources.id`, as both `outlet_id` and
  `source_id`.
- Several nameplates can share one of our sources -- one website, several
  papers. The source's UUID goes to the nameplate its name matches best; the
  others get UUIDs of their own and keep `source_id` pointing at the source.
- An outlet we do not hold gets a new UUID the first time it appears and keeps
  it on every rebuild. If it is added to `sources`, that UUID is the id it
  takes.

## Location

Every row is mappable today by its town: `lat`/`lon` are the Census place
centroid, and `location_basis` says so. `address_basis` records where a street
address came from: `sources`, `mpa`, `bluebook`, or `missing`.

**Our sources table's address is never replaced.** Where `sources.metadata`
holds one (`address1`/`address2`/`zip`, or `address`/`zip_code`), it is the
address, whatever a list says. The lists fill a gap; nothing here writes to
`sources`.

**A broadcaster's FCC facility is its own set of columns.** The FCC licenses
a transmitter at a point, for a community: `fcc_call_signs`,
`fcc_facility_id`, `fcc_community`, `tx_lat`, `tx_lon`, built by
`scripts/build_mo_broadcast_facilities.py` into
`src/lookups/mo_broadcast_facilities.csv` and joined by website. Call signs
are mapped by hand, because a newsroom's name often does not carry its own
(KY3 is KYTV, Fox 2 Now is KTVI, STL Public Radio is KWMU).

The licensee's mailing address is not used anywhere: for a group-owned
station it is the group's headquarters -- Sinclair's in Maryland, Audacy's in
Pennsylvania. AM stations have a facility and community but no transmitter
point, because the FCC's AM text query no longer answers; they come from the
CDBS facility file instead. A street address replaces
a town point when one is found; `county_basis` does the same for county:
`listed` by a list or our table, `town` from the outlet's town, or `address`
from the town in its street address -- which is the publisher's office, not
always the paper's own town (New Madrid Weekly Record's office is in
Sikeston).

A platform host -- Facebook, Instagram, X, YouTube, Wix, an e-edition viewer
-- is not a publisher's website. Two outlets on Facebook do not share a site,
and a platform host never matches one outlet to another.

## Mergers, closures and duplicates

Two kinds of column, and the builder treats them differently.

**`signals` is evidence, recomputed every run.** It never decides anything:

| Signal | Means |
| --- | --- |
| `active but never collected` | `active` in sources, no article ever |
| `no articles since <date>` | nothing collected in 90 days |
| `retired in sources` / `paused in sources` | our table already stopped it |
| `website shared with N other outlet(s)` | nameplates on one site: a merger, a sister paper, or one paper listed twice |
| `possible duplicate` | two rows with the same name in the same town |
| `2025 sheet: ...` | the 2025 working sheet noted a closure, e-edition-only, or a move |
| `website gone`, `print or replica only`, `no web edition` | carried from the 2026-09-24 review |

**`status`, `merged_into`, `status_basis`, `reviewed_by`, `reviewed_at` are a
person's answer**, and a rebuild never overwrites them. Where we hold an
outlet and nobody has reviewed it, `status` starts as the sources table's own
status.

`status` values, lower case: `active`; `print`, `replica`, `facebook`,
`social` (mapped as print, replica or social); `closed`, `merged`,
`duplicate`, `legal`, `shopper`, `business`, `magazine`, `not_local_news`
(not mapped). A closure date goes in `status_basis` ("closed June 2025"), not
in `merged_into`. A reviewer's status wins over the 2026-09-24 web-access
note.

For `merged`, `merged_into` is the **website the outlet's work now appears
on** -- the Cole Camp Courier on bentoncountyenterprise.com -- and
`status_basis` names the surviving outlet and its `outlet_id`, with any date
known ("merged into the Maryville Times, January 2026"). For `duplicate`,
`merged_into` is the `outlet_id` of the row it duplicates.

**A name change is not a merger.** `aka` (the last column, also a reviewer's)
lists the other names an outlet is known by, separated by `;`: "Moberly
Monitor-Index" on the Moberly Monitor, the five Call editions on St. Louis
Call Newspapers. It sits on the canonical row -- the one holding the
`sources.id` -- and never becomes a row of its own. The builder reads it
before matching any list, so a list using an old name attaches to that row
instead of adding a second one. The outlet keeps its status.

`src/lookups/mo_public_notices_publications_2026.csv` is the Missouri Press
public-notice list of legal publications, with its ceased flags. "Ceased"
there can mean a paper stopped being a legal publication rather than stopped
publishing -- the St. Louis Business Journal is marked ceased and is active --
so it is evidence for a reviewer, not a status.

To review: filter `signals` non-empty, decide each row, fill the five review
columns, commit the CSV. A decision about an outlet we hold is then applied to
`sources` in its own change; the registry records it, it does not write it.

## Mapping

Two derived columns, recomputed every run, say what a map draws.

`map` is `yes` for one point per surviving outlet and `no` for a row whose
status is `merged`, `duplicate`, `closed` or `not_local_news` (or marked not
local news): a merged or duplicate row's work is counted at the outlet it
points to. An also-known-as name is already the same row.

`map_category` colours the points, in this order of precedence:

| Category | Means |
| --- | --- |
| `print` | reviewer status `print`/`print_only`, or listed print or replica only / no web edition |
| `replica` | reviewer status `replica`: a page-image e-edition |
| `social` | reviewer status `facebook`/`social`, or only a social-media page and nothing collected |
| `collected` | we collected articles from it in March 2026 |
| `not collected` | anything else on the map |
| `legal`, `shopper`, `business`, `magazine` | off the map, named for the reason |

`county_fips` is the point's county: the first county of a service area
("Clay County, Ray" is Clay), St. Louis city as 29510, and looked up in the
outlet's own `state` -- the county name alone is not unique (Johnson County is
in Missouri and Kansas; KMBZ is in the Kansas one). An outlet's `state` is our
sources table's; the lists' outlets are Missouri.

## Corrections and additions

Two more files, both a reviewer's, both applied on every rebuild:

- `src/lookups/mo_outlet_overrides.csv` -- `outlet_id, field, value, was, by,
  at`: a correction to a field the builder would otherwise recompute
  (`outlet`, `city`, `county`, `host`, `owner`, `address`), applied last. `was`
  is the value it replaced, and is how the builder recognises the row on the
  next rebuild: a renamed row is looked up under its original name, so it
  keeps its `outlet_id` and its review. An outlet we hold is corrected in
  `sources`, not here.
- `src/lookups/mo_outlets_added.csv` -- an outlet no list holds, with its own
  `outlet_id` minted once, joined before the lists are matched. StoneCounty.news
  (Crane, operated by Crane.news, launched August 2026) is the first.

A reviewer's spreadsheet comes back through these: the review columns into
the registry, the corrected fields into the overrides file. Dates Excel
reformats (`7/28/26`) are read back to ISO; derived columns are recomputed,
never imported.
