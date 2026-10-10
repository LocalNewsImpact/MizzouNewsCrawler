"""Lineages -> the river feed: one row per year with the papers publishing, and the papers founded,
merged and closed that year, by name. A merger counts the papers absorbed (every paper in it but the one
that carries on), and is named as the papers that went in and the paper that came out.
"""

import collections
import csv
import json

import pandas as pd
from paths import IN, OUT, REGISTRY  # noqa: F401

L = pd.read_csv(OUT / "shsmo_lineages.csv")
d = pd.read_csv(OUT / "shsmo_titles_resolved.csv")
E = [
    (int(e["pred"]), int(e["succ"]))
    for e in csv.DictReader(open(OUT / "shsmo_edges.csv"))
]
preds = collections.defaultdict(set)
for a, b in E:
    preds[b].add(a)
Y0, Y1 = 1820, 2026  # to today: the last row is the registry's papers publishing now
nm = lambda name, town: (
    f"{name} ({town})" if isinstance(town, str) and town else str(name)
)
L["e"] = L.end.fillna(9999)  # still publishing: no end
rows = {
    y: dict(
        kind="year",
        year=y,
        publishing=int(((L.start <= y) & (L.e >= y)).sum()),
        founded=[],
        closed=[],
        merged=[],
        absorbed=0,
    )
    for y in range(Y0, Y1 + 1)
}
# the last row is today: only the papers that have not ended (the registry's papers publishing now)
rows[Y1]["publishing"] = int((L.end_type == "still publishing").sum())
for _, r in L.iterrows():
    if Y0 <= r.start <= Y1:
        rows[int(r.start)]["founded"].append(nm(r["name"], r.town))
    if r.end_type == "closed" and pd.notna(r.end) and Y0 <= r.end <= Y1:
        rows[int(r.end)]["closed"].append(nm(r["name"], r.town))
shsmo_merge = set()
for b, ps in preds.items():
    if len(ps) >= 2:
        y = int(d.at[b, "start_year"])
        shsmo_merge.add((int(d.at[b, "lineage"]), y))
        if Y0 <= y <= Y1:
            rows[y]["merged"].append(
                " + ".join(sorted(str(d.at[a, "title"]) for a in ps))
                + " → "
                + nm(d.at[b, "title"], d.at[b, "town"])
            )
            rows[y]["absorbed"] += len(ps) - 1
names = dict(zip(L.lineage, L["name"]))
import csv as _csv

REG_NAMES = {x["outlet_id"]: x["outlet"] for x in _csv.DictReader(open(REGISTRY))}
for _, r in L[
    L.registry_merge.notna() & (L.end_type == "merged") & (L.end <= Y1)
].iterrows():
    y = int(r.end)
    if pd.notna(r.into) and (int(r.into), y) in shsmo_merge:
        continue
    surv = (
        names.get(int(r.into))
        if pd.notna(r.into) and int(r.into) >= 0
        else r.registry_merge.split(" -> ")[-1]
    )
    surv = REG_NAMES.get(surv, surv)  # a survivor named by its registry id
    rows[y]["merged"].append(f"{r['name']} → {surv}")
    rows[y]["absorbed"] += 1
out = list(rows.values())
json.dump(
    out,
    open(OUT / "missouri_newspaper_river.json", "w"),
    separators=(",", ":"),
    ensure_ascii=False,
)
tot = lambda k: sum(len(r[k]) for r in out)
print(
    len(out),
    "years | founded",
    tot("founded"),
    "closed",
    tot("closed"),
    "merger events",
    tot("merged"),
    "absorbed",
    sum(r["absorbed"] for r in out),
)
import os

print(round(os.path.getsize(OUT / "missouri_newspaper_river.json") / 1024), "KB")
