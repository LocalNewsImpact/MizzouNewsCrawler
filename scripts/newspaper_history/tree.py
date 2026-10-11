"""Titles + catalogue links -> county family-tree feed.

One row per title (kind "title") and one per link (kind "link"). A link is "merged" when its successor
has two or more predecessors, "split" when its predecessor has two or more successors, else "renamed".
Registry mergers SHSMO has not linked add a "merged" link from the merged paper's last title to the
survivor's current title.
"""

import collections
import csv
import json

import pandas as pd
from paths import IN, OUT, REGISTRY  # noqa: F401

d = pd.read_csv(
    OUT / "shsmo_titles_resolved.csv", dtype={"reg_name": str, "reg_town": str}
)
lin = pd.read_csv(OUT / "shsmo_lineages.csv")
E = [
    (int(e["pred"]), int(e["succ"]))
    for e in csv.DictReader(open(OUT / "shsmo_edges.csv"))
]
nin = collections.Counter(b for a, b in E)
nout = collections.Counter(a for a, b in E)
active = d.active.astype(str).eq("True")
end = {i: (None if active[i] else int(d.at[i, "end"])) for i in d.index}
links = [
    dict(
        kind="link",
        source=a,
        target=b,
        how="merged" if nin[b] >= 2 else "split" if nout[a] >= 2 else "renamed",
    )
    for a, b in E
]
for _, r in lin[lin.registry_merge.notna()].iterrows():
    titles = d.index[d.lineage == r.lineage]
    last = max(titles, key=lambda i: (end[i] or 3000))
    for i in titles:  # the registry says the paper ended; its titles stop publishing
        if end[i] is None:
            end[i] = int(r.end)
    if pd.notna(r.into) and int(r.into) >= 0:
        surv = d.index[d.lineage == int(r.into)]
        tgt = max(surv, key=lambda i: (end[i] or 3000, d.at[i, "start_year"]))
        links.append(dict(kind="link", source=int(last), target=int(tgt), how="merged"))
        nin[tgt] += 1
clean = lambda s: s if pd.notna(s) else ""
rows = []
for i, r in d.iterrows():
    live = end[i] is None
    rows.append(
        dict(
            kind="title",
            id=int(i),
            county=r.county,
            town=clean(r.town),
            title=(r.reg_name if live and pd.notna(r.reg_name) else r.title),
            start=int(r.start_year),
            end=end[i],
            live=live,
        )
    )
# map-only papers (known only from surviving issues) have no dates: not in the county trees
mapped_only = set(lin.lineage[lin.surviving_issues.fillna(False).astype(bool)])
drop = {int(i) for i in d.index[d.lineage.isin(mapped_only)]}
rows = [r for r in rows if r["id"] not in drop]
links = [l for l in links if l["source"] not in drop and l["target"] not in drop]
# a title with no links stood alone
linked = {l["source"] for l in links} | {l["target"] for l in links}
for t in rows:
    t["alone"] = t["id"] not in linked
out = rows + links
json.dump(
    out, open(OUT / "missouri_newspaper_family_trees.json", "w"), separators=(",", ":")
)
c = collections.Counter(l["how"] for l in links)
print(
    len(rows),
    "titles",
    len(links),
    "links",
    dict(c),
    "alone",
    sum(t["alone"] for t in rows),
    "live",
    sum(t["live"] for t in rows),
)
