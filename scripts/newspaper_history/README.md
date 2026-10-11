# Missouri newspaper history

The feeds behind three datadesk visuals: the river (papers publishing each
year), the county family trees and the event map. One build writes all three
from one set of papers and events, and stops before anything is published if
any two disagree.

```bash
.venv/bin/python scripts/newspaper_history/build.py             # build + check
.venv/bin/python scripts/newspaper_history/build.py --publish   # ... and upload
```

Nothing the build reads is in git (this repository is public):

- **The catalogues** -- other people's data, parsed (SHSMO, Library of
  Congress, newspapers.com): in
  `gs://mizzou-news-maps-data/newspaper_history/inputs/`, fetched into
  `src/lookups/newspaper_history/` (ignored) when missing. After a re-parse,
  `build.py --push-inputs` uploads them.
- **A reviewer's facts** -- corrections, founding years, mergers: in datadesk's
  database (datadesk `docs/NEWSPAPER_HISTORY.md`). Every build first writes
  them into `src/lookups/newspaper_history/` with
  `dd-prod export_newspaper_history_inputs`; those files are output, never
  edited.

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
- **Newsrooms with no film** -- founding years (`launched` outlet events in
  datadesk, exported as `registry_founded.csv`); mergers (datadesk outlet
  events, exported as `datadesk_merged_events.csv`).

The river and the county trees count local newsrooms of any medium, print or
digital. They leave out student papers, magazines and broadcasters.

The event map also draws the radio and TV stations whose news we collect
(datadesk's `broadcast_station` table, exported as `broadcast_stations.csv`):
each from its first air date, at its city of license, added to its county's
shading and to what is active today. They are a list of their own in the map's
feed, never papers, so the river and the trees are unchanged.

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

A reviewer's correction is a row of datadesk's `newspaper_history_correction`
table, added in datadesk's admin with its evidence; the kinds and their fields
are in datadesk `docs/NEWSPAPER_HISTORY.md`. A correction reaches the visuals
with a rebuild, `--publish` and a re-pin -- no pull request. A row that no
longer matches its catalogue entry stops the build.

The code holds only rules (thresholds, distances, name patterns).

A catalogue link is placed by the town it names, its county, or a
start year within four years -- never by a name alone.
