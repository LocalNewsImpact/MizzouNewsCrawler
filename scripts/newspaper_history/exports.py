"""The river and county-tree feeds as named, flat tables a reader can download.

years  -- one row per year: what the river draws (counts, and the papers by name, "; "-separated)
papers -- one row per newspaper: its whole history in a row
events -- one row per paper founded, merged, moved or closed (or, known only from surviving issues, one row
          when they begin), and per title renamed, split or combined, with its
          source; other_town/other_county are where the other paper (or the new town) was

The river feed is {years, papers, events}; the county-tree feed is {titles, links, papers, events}. datadesk offers
each list as its own CSV.
"""

import collections
import json

import pandas as pd
from paths import IN, OUT, REGISTRY  # noqa: F401

d = pd.read_csv(OUT / "shsmo_titles_resolved.csv")
L = pd.read_csv(OUT / "shsmo_lineages.csv")
E = pd.read_csv(OUT / "shsmo_edges.csv")
river = json.load(open(OUT / "missouri_newspaper_river.json"))
tree = json.load(open(OUT / "missouri_newspaper_family_trees.json"))

s = lambda v: "" if pd.isna(v) else str(v)
yr = lambda v: "" if pd.isna(v) else int(v)
name_of = dict(zip(L.lineage, L["name"]))
filmed = d.held_first.notna()


# ---- events --------------------------------------------------------------------------------------------
nin = collections.Counter(E.succ)
nout = collections.Counter(E.pred)
joined = (
    {}
)  # lineage -> the latest title in ANOTHER lineage that one of its titles combined into
for e in E.sort_values("succ").itertuples():
    a, b = d.loc[e.pred], d.loc[e.succ]
    if nin[e.succ] >= 2 and a.lineage != b.lineage:
        prev = joined.get(a.lineage)
        if prev is None or (b.start_year or 0) >= (prev[0].start_year or 0):
            joined[a.lineage] = (b, e.source)


def where(lineage, year):
    """The town and county a paper was published in, in a given year: its title of that year."""
    ts = d[d.lineage == lineage].sort_values("start_year")
    cur = ts[ts.start_year <= year] if pd.notna(year) else ts
    r = cur.iloc[-1] if len(cur) else ts.iloc[0]
    return s(r.town), r.county


def survivor(x):
    """(name, source, town, county) of the paper x merged into, where it was at the time."""
    if pd.notna(x.into) and int(x.into) >= 0 and int(x.into) in name_of:
        src = (
            "registry / datadesk outlet event"
            if isinstance(x.registry_merge, str)
            else "SHSMO catalogue"
        )
        return (name_of[int(x.into)], src, *where(int(x.into), x.end))
    if isinstance(x.registry_merge, str) and "->" in x.registry_merge:
        return (
            x.registry_merge.split(" -> ")[-1],
            "registry / datadesk outlet event",
            "",
            "",
        )
    if x.lineage in joined:
        b, src = joined[x.lineage]
        return name_of.get(int(b.lineage), b.title), src, s(b.town), b.county
    return "", "SHSMO catalogue", "", ""


events = []
for x in L.itertuples():
    t = d[d.lineage == x.lineage].sort_values("start_year")
    first = t.iloc[0]
    added = pd.isna(first.held_first) and first.in_registry
    if x.surviving_issues:
        # Known only from the issues that survive: one event in the year they begin -- neither a founding nor a
        # closing, which the record does not show.
        events.append(
            dict(
                year=yr(x.start),
                event="issues survive",
                paper=first.title,
                town=s(first.town),
                county=first.county,
                other_paper="",
                other_town="",
                other_county="",
                source="SHSMO film only: no dates catalogued",
            )
        )
        continue
    events.append(
        dict(
            year=yr(x.start),
            event="founded",
            paper=first.title,
            town=s(first.town),
            county=first.county,
            other_paper="",
            other_town="",
            other_county="",
            source=(
                "reviewer or the paper's own record (not on SHSMO film)"
                if added
                else "SHSMO catalogue"
            ),
        )
    )
    if x.end_type == "closed":
        last = t.iloc[-1]
        events.append(
            dict(
                year=yr(x.end),
                event="closed",
                paper=s(x.name),
                town=s(x.town),
                county=x.county,
                other_paper="",
                other_town="",
                other_county="",
                source="SHSMO catalogue (last issue held or catalogued)",
            )
        )
    elif x.end_type == "merged":
        # A merger is a paper that ended in one -- what the river counts, and what keeps its width equal to
        # the foundings less the closings and mergers. The survivor is the registry's when it names one,
        # else the paper the catalogue says it joined.
        into, src, itown, icounty = survivor(x)
        events.append(
            dict(
                year=yr(x.end),
                event="merged",
                paper=s(x.name),
                town=s(x.town),
                county=x.county,
                other_paper=s(into),
                other_town=itown,
                other_county=icounty,
                source=src,
            )
        )
for e in E.itertuples():
    a, b = d.loc[e.pred], d.loc[e.succ]
    # A title-to-title link. "combined": this title and others went into the next one; whether a PAPER
    # ended there is the lineage's "merged" event above.
    how = (
        "combined" if nin[e.succ] >= 2 else "split" if nout[e.pred] >= 2 else "renamed"
    )
    events.append(
        dict(
            year=yr(b.start_year),
            event=how,
            paper=a.title,
            town=s(a.town),
            county=a.county,
            other_paper=b.title
            + (f" ({b.town})" if s(b.town) and b.town != a.town else ""),
            other_town=s(b.town),
            other_county=b.county,
            source=e.source,
        )
    )
# A paper that carried on in another town MOVED: both towns see it, as the paper leaving one and arriving in the
# other. Read from its titles in date order (first issue held breaks a tie), so a move is a change of town
# between one title and the next, never a link followed backwards.
for x in L.itertuples():
    ts = d[(d.lineage == x.lineage) & d.town.notna()]
    ts = ts.assign(_k=ts.held_first.fillna(pd.Timestamp.max)).sort_values(
        ["start_year", "_k"]
    )
    prev = None
    for i, b in ts.iterrows():
        # A title several papers combined into is a merger, not a move -- nor is any change of town by a title
        # that went into one (the Laddonia Herald, into the Vandalia Press and Laddonia Herald, 1945). A move is dated when the old title stopped -- its catalogued end or its last filmed
        # issue, whichever is earlier -- not by the new title's catalogued start: the three Rambler entries
        # are all catalogued 1945-1965, and their film runs Linneus 1954-56, Trenton 1956-57, Fair Play 1957-65.
        if (
            prev is not None
            and b.town != prev.town
            and b.start_year >= prev.start_year
            and nin[i] < 2
            and not any(nin[s] >= 2 for s in E.succ[E.pred == prev.name])
        ):
            stops = [
                v
                for v in (prev.end_year, str(prev.held_last)[:4])
                if pd.notna(v) and str(v)[:4].isdigit()
            ]
            when = (
                max(b.start_year, min(float(v) for v in stops))
                if stops
                else b.start_year
            )
            events.append(
                dict(
                    year=yr(when),
                    event="moved",
                    paper=prev.title,
                    town=s(prev.town),
                    county=prev.county,
                    other_paper=b.title,
                    other_town=s(b.town),
                    other_county=b.county,
                    source="SHSMO catalogue",
                )
            )
        prev = b
events.sort(
    key=lambda r: (r["year"] if r["year"] != "" else 9999, r["county"], r["paper"])
)

# ---- years ---------------------------------------------------------------------------------------------
# What the river draws. Its mergers are the papers that ended in one (the events above), so in every year
# the width moves by the foundings less the closings and mergers.
merged_in = collections.defaultdict(list)
for e in events:
    if e["event"] == "merged" and e["year"] != "":
        merged_in[e["year"]].append(
            f"{e['paper']} ({e['town']})"
            + (f" → {e['other_paper']}" if e["other_paper"] else "")
        )
years = [
    dict(
        year=r["year"],
        publishing=r["publishing"],
        founded=len(r["founded"]),
        merged=len(merged_in[r["year"]]),
        closed=len(r["closed"]),
        founded_papers="; ".join(r["founded"]),
        mergers="; ".join(merged_in[r["year"]]),
        closed_papers="; ".join(r["closed"]),
    )
    for r in river
]

# ---- papers --------------------------------------------------------------------------------------------
src_by_title = collections.defaultdict(set)
for e in E.itertuples():
    src_by_title[e.pred].add(e.source.split(":")[0])
    src_by_title[e.succ].add(e.source.split(":")[0])
papers = []
for x in L.itertuples():
    t = d[d.lineage == x.lineage].sort_values("start_year")
    names = list(dict.fromkeys(t.title))
    towns = list(dict.fromkeys(t.town.dropna()))
    srcs = set()
    for i in t.index:
        srcs |= src_by_title.get(i, set())
    if filmed[t.index].any():
        srcs.add("SHSMO catalogue")
    if t.in_registry.any():
        srcs.add("Missouri outlet registry")
    into = ""
    if x.end_type == "merged":
        into = survivor(x)[0]
    papers.append(
        dict(
            paper=s(x.name),
            town=s(x.town),
            county=x.county,
            first_year=yr(x.start),
            last_year="" if x.end_type == "still publishing" else yr(x.end),
            outcome="known from surviving issues" if x.surviving_issues else x.end_type,
            merged_into=s(into),
            earlier_titles="; ".join(n for n in names if n != x.name),
            towns="; ".join(towns),
            title_count=len(names),
            sources="; ".join(sorted(srcs)),
        )
    )
papers.sort(
    key=lambda r: (
        r["county"],
        r["first_year"] if r["first_year"] != "" else 9999,
        r["paper"],
    )
)

# ---- feeds ---------------------------------------------------------------------------------------------
titles = [r for r in tree if r["kind"] == "title"]
links = [r for r in tree if r["kind"] == "link"]
json.dump(
    dict(years=years, papers=papers, events=events),
    open(OUT / "missouri_newspaper_river.json", "w"),
    separators=(",", ":"),
    ensure_ascii=False,
)
json.dump(
    dict(titles=titles, links=links, papers=papers, events=events),
    open(OUT / "missouri_newspaper_family_trees.json", "w"),
    separators=(",", ":"),
    ensure_ascii=False,
)
import os

print(
    f"years {len(years)} | papers {len(papers)} | events {len(events)} "
    f"({dict(collections.Counter(e['event'] for e in events))})"
)
print(
    "river feed",
    round(os.path.getsize(OUT / "missouri_newspaper_river.json") / 1024),
    "KB | tree feed",
    round(os.path.getsize(OUT / "missouri_newspaper_family_trees.json") / 1024),
    "KB",
)
