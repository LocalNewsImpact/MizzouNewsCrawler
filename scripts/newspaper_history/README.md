# Missouri newspaper history

The feeds behind three datadesk visuals: the river (papers publishing each
year), the county family trees and the event map. One build writes all three
from one set of papers and events, and stops before anything is published if
any two disagree.

```bash
.venv/bin/python scripts/newspaper_history/build.py             # build + check
.venv/bin/python scripts/newspaper_history/build.py --publish   # ... and upload
```

The inputs are other people's data (the SHSMO catalogue) and a reviewer's
notes, and this repository is public, so they are not in git: they live in
`gs://mizzou-news-maps-data/newspaper_history/inputs/` and the build fetches
any that are missing into `src/lookups/newspaper_history/` (ignored). After
editing one, `build.py --push-inputs` uploads them.

`--publish` uploads the three feeds to `gs://mizzou-news-maps-data/visuals/`.
The datadesk visuals are then re-pinned together (refresh_snapshot + publish),
so no page shows a newer history than the others.

## Sources of truth

- **The past** -- titles, renamings, mergers, moves: the State Historical
  Society of Missouri's county directories (`shsmo_missouri_titles.csv`, parsed
  from the 115 county PDFs by `parse.py`) and Library of Congress links
  (`loc_links.csv`).
- **Today** -- which papers are publishing, and where: the Missouri outlet
  registry (`src/lookups/mo_outlet_registry.csv`). Its status, town and county
  override the catalogue's last record; a registry closure or merger sets the
  paper's end.
- **Newsrooms with no film** -- founding years from the reviewer
  (`registry_founded.csv`); mergers recorded in datadesk
  (`datadesk_merged_events.csv`).

The history counts local newsrooms of any medium, print or digital. It leaves
out student papers, magazines and broadcasters.

## Steps

| Step | Reads | Writes |
|---|---|---|
| `lineage.py` | the inputs, the registry | titles, links (edges), lineages |
| `tree.py` | titles, links, lineages | the county-tree titles and links |
| `river.py` | titles, links, lineages | the river's years |
| `exports.py` | all of the above | the river and tree feeds as named tables: years, papers, events |
| `mapfeed.py` | the river feed, datadesk's Census geometry | the event-map feed |
| `check.py` | the three feeds | nothing; exits 1 if they disagree |

`exports.py` defines the events every view shares: a paper **founded**,
**merged** (it ended by joining another paper), **moved** (it carried on in
another town) or **closed**, and the title-to-title links **renamed**,
**split** and **combined**.

The map's geometry is datadesk's (`static/geo/`), read from a datadesk checkout
beside this repo (`DATADESK_DIR` to point elsewhere), so every county and town
the feed names is one the page can draw.

## Corrections to the catalogue

A reviewer's correction is data, not code: one row of
`reviewer_corrections.csv` in the inputs bucket. Adding one is an edit to that
file, `build.py --push-inputs`, `build.py --publish` and a re-pin of the three
visuals -- no pull request. Every row carries its evidence, and a row that no
longer matches its entry stops the build.

| kind | what the row says | columns used |
|---|---|---|
| `set` | a catalogue field is wrong: town, county, a start or end year, a first reel | title, county, town (to match); field, value |
| `drop` | an entry is the same film as another | title, county |
| `reels_belong_to` | an entry's reels are another paper's; the entry goes, its last reel moves over | title, county, town; other_title, other_county (exact spelling); field, value |
| `moved` | one paper filmed under several towns | title; value = towns in film order, `" > "` between |
| `link` | one title carried on as another (a renaming or merger the catalogue does not link) | title, county -> other_title, other_county |
| `unlink` | a catalogue link a reviewer's chain replaces | title, county -> other_title, other_county |
| `registry_alias` | the registry's name for a catalogue title that shares no word with it | title, county; other_title, other_town = the registry's name and town |
| `not_a_newsroom` | a registry row not counted as a local newsroom | title = registry outlet |
| `not_the_towns_paper` | a registry row that is not its town's continuing paper | title = registry outlet |
| `print_ended` | a registry paper's print run ended, with its year | title = registry outlet; field = merged or closed; value = year; other_county, other_title = the SHSMO entry where the registry would not find it |

Founding years of newsrooms SHSMO never filmed are rows of
`registry_founded.csv`.

The code holds only rules (thresholds, distances, name patterns).

A catalogue link is placed by the town it names, its county, or a
start year within four years -- never by a name alone.
