"""The three feeds count the same papers, or nothing is published.

The river, the county family trees and the event map are three views of one
history. Each assertion here is a number two of them both show a reader:

- the trees carry the river's papers and events table for table;
- the map holds exactly the river's foundings, mergers and closings;
- in every year, the papers the map shades across the counties add up to the
  river's width, and in the last frame to the papers publishing today;
- in every year, the river's founded, merged and closed counts are the events
  of that year.
"""

import collections
import json
import sys

from paths import OUT


def load(name):
    with open(OUT / name, encoding="utf-8") as f:
        return json.load(f)


def main():
    river = load("missouri_newspaper_river.json")
    trees = load("missouri_newspaper_family_trees.json")
    emap = load("missouri_newspaper_event_map.json")
    bad = []

    for table in ("papers", "events"):
        if river[table] != trees[table]:
            bad.append(f"the trees' {table} differ from the river's")

    kept = [e for e in river["events"] if e["event"] in ("founded", "merged", "closed")]

    def key(e):
        return (e["year"], e["event"], e["paper"], e["county"])

    shown = [e for e in emap["events"] if e["event"] != "moved"]
    if collections.Counter(map(key, kept)) != collections.Counter(map(key, shown)):
        bad.append(
            f"the map's events differ from the river's "
            f"({len(shown)} on the map, {len(kept)} in the river)"
        )

    y0 = emap["y0"]
    width = {r["year"]: r["publishing"] for r in river["years"]}
    last = max(width)
    for y, n in width.items():
        shaded = sum(c[y - y0] for c in emap["counties"].values())
        if y == last:
            today = sum(emap["now"].values())
            if not (n == today == len(emap["today"])):
                bad.append(
                    f"today: river {n}, map counties {today}, map points {len(emap['today'])}"
                )
        elif shaded != n:
            bad.append(f"{y}: river {n}, map counties {shaded}")

    per = collections.Counter((e["year"], e["event"]) for e in kept)
    for r in river["years"]:
        for ev, col in (
            ("founded", "founded"),
            ("merged", "merged"),
            ("closed", "closed"),
        ):
            if per[(r["year"], ev)] != r[col]:
                bad.append(
                    f"{r['year']} {ev}: river {r[col]}, events {per[(r['year'], ev)]}"
                )

    if bad:
        print("OUT OF SYNC -- not publishing:\n  " + "\n  ".join(bad[:40]))
        sys.exit(1)
    print(
        f"in sync: {len(river['papers'])} papers, {len(kept)} events, "
        f"{len(river['years'])} years, {len(emap['today'])} publishing today"
    )


if __name__ == "__main__":
    main()
