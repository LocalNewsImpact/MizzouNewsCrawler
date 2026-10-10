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

Each is in `lineage.py` with the record it answers and an assertion that fails
if the catalogue changes under it: a stray Vandalia Leader entry in the Texas
County directory, two titles filed under the wrong county (Princeton, El
Dorado Springs), and links between titles that SHSMO states but the parser
cannot place. A catalogue link is placed by the town it names, its county, or a
start year within four years -- never by a name alone.
