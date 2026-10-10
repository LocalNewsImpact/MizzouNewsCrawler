"""Where a Missouri town is: its Census place's centre, else its county's.

Read from datadesk's geometry (paths.GEO), the files the map draws, so a
distance measured here is between the points the map shows.
"""

import json
import math
import re

from paths import GEO


def _arcs(topo):
    t = topo["transform"]
    out = []
    for a in topo["arcs"]:
        x = y = 0
        pts = []
        for p in a:
            x += p[0]
            y += p[1]
            pts.append(
                (
                    x * t["scale"][0] + t["translate"][0],
                    y * t["scale"][1] + t["translate"][1],
                )
            )
        out.append(pts)
    return out


def _centres(topo, obj):
    arcs = _arcs(topo)
    for g in topo["objects"][obj]["geometries"]:
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        pts = []
        for poly in polys:
            for i in poly[0]:
                pts += arcs[i] if i >= 0 else arcs[~i][::-1]
        if pts:
            yield g, sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(
                pts
            )


def norm(s):
    s = re.sub(r"\bst\.?\s", "saint ", str(s).lower().replace("mount ", "mt "))
    return re.sub(r"[^a-z]", "", s)


with open(GEO / "places" / "29.json") as f:
    _places = {}
    for g, x, y in _centres(json.load(f), "places"):
        _places.setdefault(norm(g["properties"]["NAME"]), (x, y))
with open(GEO / "counties-10m.json") as f:
    _counties = {
        norm(g["properties"]["name"]): (x, y)
        for g, x, y in _centres(json.load(f), "counties")
        if str(g["id"]).startswith("29") and g["id"] != "29510"
    }


def point(town, county):
    """(lon, lat) of a town: its Census place, else its county's centre, else None."""
    return _places.get(norm(town)) or _counties.get(norm(county))


def miles(a, b):
    """Great-circle miles between two (lon, lat) points."""
    (x1, y1), (x2, y2) = a, b
    p1, p2 = math.radians(y1), math.radians(y2)
    h = (
        math.sin((p2 - p1) / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(x2 - x1) / 2) ** 2
    )
    return 3959 * 2 * math.asin(math.sqrt(h))
