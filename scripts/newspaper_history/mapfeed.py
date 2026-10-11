"""The event-map feed: every founding, merger and closure at its town, and the papers
publishing in each county in each year.

Built from the river feed's papers and events (exports.py), so the map, the river and the
county trees count the same papers. A town is placed at its Census place's centre, else at
its county's centre (flagged `approx`). A merger into a paper in another town carries the
survivor's point. Counties are keyed by FIPS; a St. Louis paper in the town of St. Louis is
the city (29510), any other is the county.
"""

import collections
import json
import re

from paths import GEO, OUT


def decode(topo, obj):
    t = topo.get("transform")
    arcs = []
    for a in topo["arcs"]:
        x = y = 0
        pts = []
        for p in a:
            if t:
                x += p[0]
                y += p[1]
                pts.append(
                    (
                        x * t["scale"][0] + t["translate"][0],
                        y * t["scale"][1] + t["translate"][1],
                    )
                )
            else:
                pts.append(tuple(p))
        arcs.append(pts)
    out = []
    for g in topo["objects"][obj]["geometries"]:
        polys = (
            g["arcs"]
            if g["type"] == "MultiPolygon"
            else [g["arcs"]] if g["type"] == "Polygon" else []
        )
        pts = []
        for poly in polys:
            for i in poly[0]:
                pts += arcs[i] if i >= 0 else arcs[~i][::-1]
        if pts:
            out.append(
                (
                    g.get("properties", {}),
                    g.get("id"),
                    sum(p[0] for p in pts) / len(pts),
                    sum(p[1] for p in pts) / len(pts),
                )
            )
    return out


norm = lambda s: re.sub(
    r"[^a-z]", "", re.sub(r"\bst\.?\s", "saint ", s.lower().replace("mount ", "mt "))
)
places = {}
for props, _, x, y in decode(json.load(open(GEO / "places" / "29.json")), "places"):
    places.setdefault(norm(props["NAME"]), (x, y))
counties = {}
ct = json.load(open(GEO / "counties-10m.json"))
obj = [k for k in ct["objects"] if "count" in k][0]
for props, gid, x, y in decode(ct, obj):
    if str(gid).startswith("29"):
        counties[norm(props.get("name", ""))] = (x, y)
print("places", len(places), "MO counties", len(counties))
d = json.load(open(OUT / "missouri_newspaper_river.json"))
towns = collections.Counter(
    (e["town"], e["county"])
    for e in d["events"]
    if e["event"] in ("founded", "closed", "merged", "moved", "issues survive")
)
# and where papers went: survivors' towns and new towns
towns.update(
    (e["other_town"], e["other_county"])
    for e in d["events"]
    if e["event"] in ("merged", "moved") and e["other_county"]
)
res = {}
how = collections.Counter()
miss = collections.Counter()
for (town, county), n in towns.items():
    c = norm(county.replace("City of St. Louis", "St. Louis city"))
    if town and norm(town) in places:
        res[f"{town}|{county}"] = (*places[norm(town)], "place")
        how["place"] += n
    elif c in counties or norm(county + " city") in counties:
        res[f"{town}|{county}"] = (
            *(counties.get(c) or counties[norm(county + " city")]),
            "county",
        )
        how["county"] += n
        miss[(town, county)] += n
    else:
        how["none"] += n
        print("NO COUNTY", town, county)
print(dict(how))
print("top county-fallback towns:", miss.most_common(15))

T = res
town_of = collections.defaultdict(set)
for p in d["papers"]:
    town_of[p["paper"]].add((p["town"], p["county"]))
pt = lambda town, county: T.get(f"{town}|{county}")
rows, unplaced = [], 0
for e in d["events"]:
    if (
        e["event"] not in ("founded", "closed", "merged", "moved", "issues survive")
        or e["year"] == ""
    ):
        continue
    a = pt(e["town"], e["county"])
    if not a:
        unplaced += 1
        continue
    r = dict(
        year=e["year"],
        event=e["event"],
        paper=e["paper"],
        town=e["town"] or e["county"] + " County",
        county=e["county"],
        x=round(a[0], 4),
        y=round(a[1], 4),
        approx=a[2] == "county",
    )
    if e["event"] == "issues survive" and e.get("through"):
        r["through"] = e["through"]
    if e["event"] in ("merged", "moved"):
        # where the paper went: the survivor's town at the time of the merger, or the new town of a move,
        # as the events table records it
        if e["event"] == "merged":
            r["into"] = e["other_paper"]
        else:
            r["to"] = e["other_paper"]
        b = pt(e["other_town"], e["other_county"]) if e["other_county"] else None
        if b and (abs(b[0] - a[0]) > 1e-6 or abs(b[1] - a[1]) > 1e-6):
            r["into_town"] = e["other_town"] or e["other_county"] + " County"
            r["into_county"] = e["other_county"]
            r["ix"] = round(b[0], 4)
            r["iy"] = round(b[1], 4)
    rows.append(r)
today = [
    dict(
        paper=p["paper"],
        town=p["town"],
        county=p["county"],
        x=round(pt(p["town"], p["county"])[0], 4),
        y=round(pt(p["town"], p["county"])[1], 4),
    )
    for p in d["papers"]
    if p["outcome"] == "still publishing" and pt(p["town"], p["county"])
]
years = [dict(year=y["year"], publishing=y["publishing"]) for y in d["years"]]
c = collections.Counter(r["event"] for r in rows)
print(
    c,
    "unplaced",
    unplaced,
    "merges with an arc",
    sum(1 for r in rows if "ix" in r),
    "today",
    len(today),
    "of",
    sum(1 for p in d["papers"] if p["outcome"] == "still publishing"),
)

# ---- county shading: papers publishing in each county in each year --------------------------------------------
# A paper is counted where its title of that year was published: one that moved counts in the old county until
# the move. The map starts at the first founding (the river at 1820), so no county is shaded before the event
# that put a paper there.
import pandas as pd

ct = json.load(open(GEO / "counties-10m.json"))
geo = {}
for g in ct["objects"]["counties"]["geometries"]:
    if str(g["id"]).startswith("29") and g["id"] != "29510":
        geo[g["properties"]["name"]] = g["id"]
gid = lambda county, town: (
    "29510" if county == "St. Louis" and town == "St. Louis" else geo[county]
)
Ls = pd.read_csv(OUT / "shsmo_lineages.csv")
Ts = pd.read_csv(OUT / "shsmo_titles_resolved.csv")
Y1 = years[-1]["year"]
Y0 = int(Ls.start.min())
counts = collections.defaultdict(lambda: [0] * (Y1 - Y0 + 1))
now = collections.Counter()
for x in Ls.itertuples():
    if x.surviving_issues:
        continue  # map-only: a grey dot, no dates to shade a county with
    ts = Ts[Ts.lineage == x.lineage].sort_values("start_year")
    end = Y1 if x.end_type == "still publishing" else int(x.end)
    for y in range(int(x.start), end + 1):
        cur = ts[ts.start_year <= y]
        t = cur.iloc[-1] if len(cur) else ts.iloc[0]
        counts[gid(t.county, t.town)][y - Y0] += 1
    if x.end_type == "still publishing":
        now[gid(x.county, x.town)] += 1
# the map's own timeline runs from the first founding; from 1820 it is the river's
river_w = {r["year"]: r["publishing"] for r in years}
years = [
    dict(year=y, publishing=river_w.get(y, sum(c[y - Y0] for c in counts.values())))
    for y in range(Y0, Y1 + 1)
]
# The papers publishing today. Each holds a dot from the year it settled in its present town -- its founding, or
# its last move -- to the end, through any papers that merge into it; by the last frame all are there.
cen = {}
for k, v in T.items():
    cen.setdefault(k.split("|")[1], v)


def settled(x):
    ts = Ts[(Ts.lineage == x.lineage) & Ts.town.notna()]
    ts = ts.assign(
        _k=pd.to_datetime(ts.held_first).fillna(pd.Timestamp.max)
    ).sort_values(["start_year", "_k"])
    year = int(x.start)
    for i in range(1, len(ts)):
        if ts.iloc[i].town != ts.iloc[i - 1].town:
            year = int(ts.iloc[i].start_year)
    return year


today = []
for x in Ls[Ls.end_type == "still publishing"].itertuples():
    town = "" if pd.isna(x.town) else x.town
    a = pt(town, x.county) or cen.get(x.county)
    today.append(
        dict(
            paper=x.name,
            town=town,
            county=x.county,
            since=settled(x),
            x=round(a[0], 4),
            y=round(a[1], 4),
        )
    )
json.dump(
    dict(events=rows, today=today, years=years, y0=Y0, counties=counts, now=now),
    open(OUT / "missouri_newspaper_event_map.json", "w"),
    separators=(",", ":"),
    ensure_ascii=False,
)
print(
    "today",
    len(today),
    "| counties with papers",
    len(counts),
    "| today counties",
    len(now),
    "max today",
    now.most_common(3),
)
