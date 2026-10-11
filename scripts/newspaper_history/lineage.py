"""Titles -> newspaper lineages -> period flows for a Sankey.

A LINEAGE is one newspaper through its renamings: titles joined where one title has exactly one successor
and that successor has exactly one predecessor. At a MERGER (a title with two or more predecessors) the
OLDEST predecessor carries the lineage on and the others end as "merged". A lineage with no predecessor was
FOUNDED; one whose last title has no successor CLOSED. A lineage is STILL PUBLISHING when SHSMO catalogues
it as current and holds an issue from 2020 or later.
"""

import collections
import json
import re

import numpy as np
import pandas as pd
from paths import IN, OUT, REGISTRY  # noqa: F401

ACTIVE_FROM = 2020
d = pd.read_csv(IN / "shsmo_missouri_titles.csv", dtype=str).dropna(subset=["title"])
for c in ("held_first", "held_last"):
    d[c] = pd.to_datetime(d[c])
d["start_year"] = pd.to_numeric(d.start_year)
d["end_year"] = pd.to_numeric(d.end_year)
# SHSMO's Texas County directory (p. 19) repeats Audrain's "Vandalia leader" entry with no town heading, and
# files the Summersville Beacon's 2023 and 2024 reels under it. The entry is dropped; its reels are the Beacon's.
_stray = (
    (d.county == "Texas") & (d.town == "Summersville") & (d.title == "Vandalia leader")
)
_beacon = (
    (d.county == "Texas") & (d.title == "Summersville Beacon") & (d.end_year == 2022)
)
assert (
    _stray.sum() == 1 and _beacon.sum() == 1
), "the Texas County Vandalia leader correction no longer matches"
d.loc[_beacon, "held_last"] = d.loc[_stray, "held_last"].iloc[0]
d.loc[_beacon, "end_year"] = 2024
d = d[~_stray]
# Two titles SHSMO files under the wrong county's directory: the town is not in that county. (Found by testing every
# catalogued town against the county polygon it lies in; the other mismatches are towns that straddle a county line.)
for _town, _filed, _county in (
    ("Princeton", "Macon", "Mercer"),
    ("El Dorado Springs", "Clay", "Cedar"),
):
    _m = (d.town == _town) & (d.county == _filed)
    assert _m.any(), f"the {_town} county correction no longer matches"
    d.loc[_m, "county"] = _county
# The Wentzville Journal, a Suburban Journals paper, survives on SHSMO film for one quarter (Oct.-Dec. 1989) as the
# "Wentzville Messenger Journal"; it was published until it was combined with the Warrenton paper in 2009 as the
# Suburban Journal Wentzville/Warrenton Edition (Wikipedia, "Suburban Journals": the Wentzville Journal through the
# 2005 Lee purchase and its 2006 move online; the combined title, SHSMO Warren County, 2009-2011).
_m = (d.county == "St. Charles") & (d.title == "Wentzville Messenger Journal")
assert _m.sum() == 1, "the Wentzville Journal correction no longer matches"
d.loc[_m, "end_year"] = 2009
# The Western Messenger's Cole County entry sits under SHSMO's "Eugene" heading; LOC's record places it in Jefferson
# City (sn 92059017: "The Western Messenger (Jefferson City, Mo.)").
_m = (
    (d.county == "Cole")
    & (d.town == "Eugene")
    & (d.title.str.lower() == "western messenger")
)
assert _m.sum() == 1, "the Western Messenger town correction no longer matches"
d.loc[_m, "town"] = "Jefferson City"
# Its St. Louis entry carries film from 1882, a reel of an earlier paper: LOC has it in St. Louis Dec. 16, 1916-1917.
_m = (d.county == "St. Louis") & (d.title.str.lower() == "western messenger")
assert _m.sum() == 1, "the Western Messenger St. Louis correction no longer matches"
d.loc[_m, "held_first"] = pd.Timestamp("1916-12-16")
d.loc[_m, "start_year"] = 1916
# "18??", "19??": the catalogue does not know the year; the first issue held is the better date
fuzzy = d.start.fillna("").str.contains(r"\?") | (d.start_year < 1800)
d.loc[fuzzy & d.held_first.notna(), "start_year"] = d.loc[
    fuzzy & d.held_first.notna(), "held_first"
].dt.year
d = d[d.start_year.notna()].copy()
# Editions and special issues are not newspapers of their own. The evidence is the catalogue title:
# "... Edition", "(Supplement)", "... insert", "Souvenir", "Anniversary", "Centennial", "reprint", and
# an "Extra" that ran a year or less (a one-off issue; an ongoing title called "Extra" is a paper).
EDITION = re.compile(
    r"\bedition\b|\beditio?n?$|\beditio?n?\)|supplement|\binsert|\bins$|souvenir|anniversary|centennial|salute to|reprint",
    re.I,
)
span = d.end_year.fillna(d.held_last.dt.year) - d.start_year
extra = d.title.str.contains(r"\bextra\b", case=False, na=False) & (span.fillna(0) <= 1)
# The Suburban Journals named their local papers "editions" ("Suburban Journal Wentzville/Warrenton Edition"): each
# is a town's paper, not a special issue of another.
suburban = d.title.str.match(r"(?i)suburban journal\b", na=False)
d["edition"] = (d.title.str.contains(EDITION, na=False) & ~suburban) | extra
d[d.edition].to_csv(OUT / "shsmo_editions_excluded.csv", index=False)
print("editions and special issues excluded:", int(d.edition.sum()))
d = d[~d.edition].copy()
import unicodedata as _ud

# accents folded first: "Mississippi Blätter" is SHSMO's "Mississippi Blatter"
n = lambda s: re.sub(
    r"[^a-z0-9]",
    "",
    re.sub(
        r"^the |&",
        " ",
        _ud.normalize("NFKD", str(s))
        .encode("ascii", "ignore")
        .decode()
        .lower()
        .replace("&", "and"),
    ).replace("the ", ""),
)
place = lambda p: n(str(p).split(",")[0])
d["k_title"] = d.title.map(n)
d["k_town"] = d.town.fillna("").map(place)
# one node per title+town+start (a title catalogued under two counties is one paper)
d = (
    d.sort_values("reels" if "reels" in d else "title")
    .drop_duplicates(["k_title", "k_town", "start_year"])
    .reset_index(drop=True)
)
# One paper catalogued twice under two counties: the County Herald-Enterprise (2020-) is filed under Paris (Monroe)
# and Center (Ralls). The Paris entry stands; the Center entry is the same film.
d = d[
    ~((d.county == "Ralls") & (d.title.str.lower() == "county herald-enterprise"))
].reset_index(drop=True)
# Paper names are proper names: the catalogue's sentence case ("Weekly record") becomes title case. Small words
# stay lower case inside a name; a word that already carries capitals (McDonald, St., KC) is left as it is.
SMALL = {
    "a",
    "an",
    "and",
    "the",
    "of",
    "in",
    "on",
    "at",
    "to",
    "for",
    "or",
    "by",
    "with",
    "de",
    "des",
    "und",
}


def title_case(t):
    words = str(t).split(" ")
    out = []
    for i, w in enumerate(words):
        if not w:
            out.append(w)
            continue
        if any(ch.isupper() for ch in w[1:]) or (
            w[0].isupper() and len(w) > 1 and not w[1:].islower()
        ):
            out.append(w)
            continue
        if i > 0 and w.lower() in SMALL:
            out.append(w.lower())
            continue
        out.append("-".join(p[:1].upper() + p[1:] for p in w.split("-")))
    return " ".join(out)


d["title"] = d.title.map(title_case)
# One paper filed twice in a county under two towns -- the same title with the same first and last year
# (the Southeast Missourian, 1894-1944, under New Madrid and Portageville; papers that moved town and kept
# their name). They are one paper: one entry, under its latest town, with the film and catalogue links of both.
import json as _json

_end = d.end_year.fillna(-1)
merged_dups = 0
drop = []
for _, g in d.groupby([d.k_title, d.start_year, _end, d.county]):
    if len(g) < 2:
        continue
    keep = max(
        g.index,
        key=lambda i: (
            d.at[i, "held_last"] if pd.notna(d.at[i, "held_last"]) else pd.Timestamp(0)
        ),
    )
    for i in g.index:
        if i == keep:
            continue
        for col in ("preceding_links", "succeeding_links", "related_links"):
            a_ = _json.loads(d.at[keep, col] or "[]")
            b_ = _json.loads(d.at[i, col] or "[]")
            d.at[keep, col] = _json.dumps(a_ + [x for x in b_ if x not in a_])
        if pd.notna(d.at[i, "held_first"]) and (
            pd.isna(d.at[keep, "held_first"])
            or d.at[i, "held_first"] < d.at[keep, "held_first"]
        ):
            d.at[keep, "held_first"] = d.at[i, "held_first"]
        if str(d.at[i, "catalogue_current"]) == "True":
            d.at[keep, "catalogue_current"] = "True"
        drop.append(i)
        merged_dups += 1
d = d.drop(index=drop).reset_index(drop=True)
print("same paper filed under two towns in one county, merged:", merged_dups)
# Papers that moved between counties and kept their name: the same title and years, film resuming within 45
# days, towns within 30 miles, a name of two or more significant words -- plus two the reviewer judged the same
# paper further apart (the Missouri Army Argus, a Confederate army paper that moved with the troops in 1861; the
# World's Cresset). One entry, under its last town.
MOVED = [  # title, the towns in the order the film runs
    ("Post-Tribune", ["Parma", "Bernie"]),
    ("Lake Sun", ["Camdenton", "Osage Beach"]),
    ("Lake Sun-Leader", ["Osage Beach", "Camdenton"]),
    ("Otter Ozark Outdoor News", ["Clinton", "Appleton City"]),
    ("Missouri Intelligencer and Boon's Lick Advertiser", ["Fayette", "Columbia"]),
    ("North Missouri Register", ["Brashear", "Macon"]),
    (
        "Missouri Army Argus",
        ["Neosho", "Pineville", "Greenfield", "Osceola", "Springfield"],
    ),
    # Leroy Garrett's colony paper: one weekly, 1891 to Dec. 26, 1918, moving with the colony through Miller,
    # Benton, Carter, Douglas, Howell, Texas and Wright counties without a break (LOC sn93060090 essay).
    (
        "World's Cresset",
        [
            "Fowler",
            "Norwood",
            "Pomona",
            "Trask",
            "Brushy Knob",
            "Mountain Grove",
            "Fremont",
        ],
    ),
    # the Oakville Call (St. Louis Call Newspapers, callnewspapers.com/about-us): filed under St. Louis to Apr. 2015,
    # under Oakville from May 2015
    ("Oakville Call", ["St. Louis", "Oakville"]),
]
moved = 0
drop = []
for t, towns in MOVED:
    rows = [
        d.index[
            (d.title.str.lower() == t.lower())
            & (d.town.fillna("").str.lower() == tw.lower())
        ]
        for tw in towns
    ]
    if any(len(r) == 0 for r in rows):
        print(
            "  MOVED not found:", t, [tw for tw, r in zip(towns, rows) if len(r) == 0]
        )
        continue
    rows = [int(r[0]) for r in rows]
    keep = rows[-1]
    for i in rows[:-1]:
        for col in ("preceding_links", "succeeding_links", "related_links"):
            a_ = _json.loads(d.at[keep, col] or "[]")
            b_ = _json.loads(d.at[i, col] or "[]")
            d.at[keep, col] = _json.dumps(a_ + [x for x in b_ if x not in a_])
        if pd.notna(d.at[i, "held_first"]) and (
            pd.isna(d.at[keep, "held_first"])
            or d.at[i, "held_first"] < d.at[keep, "held_first"]
        ):
            d.at[keep, "held_first"] = d.at[i, "held_first"]
        drop.append(i)
        moved += 1
d = d.drop(index=drop).reset_index(drop=True)
print("papers that moved between counties, entries merged:", moved)
# Library of Congress (US Newspaper Directory, src/lookups/mo_loc_newspaper_directory.json): links SHSMO does not
# make, each with its LOC record (loc_links.csv, matched by match_loc.py). Titles are keyed by title, town,
# county and first year, so they survive the renumbering above.
LOC = pd.read_csv(IN / "loc_links.csv")


def loc_find(t, town, county, start):
    m = d.index[
        (d.title.str.lower() == str(t).lower())
        & (d.county == county)
        & (d.start_year == start)
    ]
    if len(m) > 1 and isinstance(town, str) and town:
        m = [i for i in m if str(d.at[i, "town"]).lower() == town.lower()] or m
    if not len(m) and (str(t).lower(), county, start) in ABSORBED:
        return loc_find(*ABSORBED[(str(t).lower(), county, start)])
    if not len(m):
        # a corrected parse can move a start year (the SunCrest Call's 1856 was another paper's film): the same
        # title, county and town, if there is only one
        m = d.index[
            (d.title.str.lower() == str(t).lower())
            & (d.county == county)
            & (d.town.fillna("").str.lower() == str(town or "").lower())
        ]
        if len(m) != 1:
            return None
    return int(m[0]) if len(m) else None


loc_moved = 0
drop = []
ABSORBED = (
    {}
)  # an entry a move merged away -> the entry that absorbed it, so links to it follow
for x in LOC[LOC.kind == "move"].itertuples():
    a = loc_find(x.a_title, x.a_town, x.a_county, x.a_start)
    b = loc_find(x.b_title, x.b_town, x.b_county, x.b_start)
    if a is None or b is None or a == b or a in drop or b in drop:
        continue
    keep, other = (
        (a, b)
        if (d.at[a, "held_last"] if pd.notna(d.at[a, "held_last"]) else pd.Timestamp(0))
        >= (d.at[b, "held_last"] if pd.notna(d.at[b, "held_last"]) else pd.Timestamp(0))
        else (b, a)
    )
    for col in ("preceding_links", "succeeding_links", "related_links"):
        a_ = _json.loads(d.at[keep, col] or "[]")
        b_ = _json.loads(d.at[other, col] or "[]")
        d.at[keep, col] = _json.dumps(a_ + [y for y in b_ if y not in a_])
    if pd.notna(d.at[other, "held_first"]) and (
        pd.isna(d.at[keep, "held_first"])
        or d.at[other, "held_first"] < d.at[keep, "held_first"]
    ):
        d.at[keep, "held_first"] = d.at[other, "held_first"]
    ABSORBED[
        (
            d.at[other, "title"].lower(),
            d.at[other, "county"],
            int(d.at[other, "start_year"]),
        )
    ] = (
        d.at[keep, "title"],
        d.at[keep, "town"],
        d.at[keep, "county"],
        int(d.at[keep, "start_year"]),
    )
    drop.append(other)
    loc_moved += 1
d = d.drop(index=drop).reset_index(drop=True)
print("LOC: papers that moved, entries merged:", loc_moved)
# Newsrooms publishing today that SHSMO never filmed (founded since filming, or digital), with the founding year a
# reviewer or the paper itself gives (registry_founded.csv; Springfield Daily Citizen, 2022, from its own notes).
# Each enters as a title of its own, founded that year, so publishing today counts it.
_f = pd.read_csv(IN / "registry_founded.csv", dtype=str).fillna("")
_f = pd.concat(
    [
        _f,
        pd.DataFrame(
            [
                dict(
                    outlet="Springfield Daily Citizen",
                    city="Springfield",
                    county="Greene",
                    founded_year="2022",
                )
            ]
        ),
    ],
    ignore_index=True,
)
new = []
for x in _f[_f.founded_year != ""].itertuples():
    c = str(x.county).replace(" County", "")
    new.append(
        dict(
            county=c,
            town=x.city,
            title=x.outlet,
            start=x.founded_year,
            end="current",
            start_year=int(x.founded_year),
            end_year=None,
            catalogue_current="True",
            pub_dates=f"{x.founded_year}-current",
            frequency="",
            preceding="",
            succeeding="",
            related="",
            preceding_links="[]",
            succeeding_links="[]",
            related_links="[]",
            held_first=pd.NaT,
            held_last=pd.NaT,
            reels=0,
            edition=False,
            k_title=n(x.outlet),
            k_town=place(x.city),
        )
    )
if new:
    d = pd.concat([d, pd.DataFrame(new)], ignore_index=True)
print("newsrooms not on SHSMO film, added with their founding year:", len(new))
# Papers SHSMO's directories do not list, known from the SHSMO Digital Newspaper Project on newspapers.com
# (newspapers_com_titles.csv: title, town, its county by where the town lies, the years digitized). No
# catalogue dates when they began or ended, so they are map-only: shown as their surviving issues, not
# counted in the river or the county trees.
d["digitized_only"] = False
_nc = pd.read_csv(IN / "newspapers_com_titles.csv", dtype=str).fillna("")
_nc_rows = [
    dict(
        county=x.county,
        town=x.town,
        title=x.title,
        start=x.first_year,
        end=x.last_year,
        start_year=int(x.first_year),
        end_year=int(x.last_year),
        catalogue_current="False",
        pub_dates=None,
        frequency="",
        preceding="",
        succeeding="",
        related="",
        preceding_links="[]",
        succeeding_links="[]",
        related_links="[]",
        held_first=pd.Timestamp(f"{x.first_year}-01-01"),
        held_last=pd.Timestamp(f"{x.last_year}-12-31"),
        reels=0,
        edition=False,
        k_title=n(x.title),
        k_town=place(x.town),
        digitized_only=True,
    )
    for x in _nc.itertuples()
]
if _nc_rows:
    d = pd.concat([d, pd.DataFrame(_nc_rows)], ignore_index=True)
print("papers known only from newspapers.com, map-only:", len(_nc_rows))
d["cur"] = d.catalogue_current.eq("True")
d["active"] = d.cur & (d.held_last.dt.year >= ACTIVE_FROM)
# end year: catalogued, else last issue held; still-publishing titles have none
d["end"] = np.where(d.active, np.nan, d.end_year.fillna(d.held_last.dt.year))
d["end"] = pd.to_numeric(d["end"]).fillna(d.start_year)
# Film that predates the catalogue's own start is film of another title on the same reels (the Neosho
# Daily News & Seneca News-Dispatch, catalogued 2021-current, carries 1966-68 reels). An end before the
# start is that error; the catalogue's start stands and the end falls back to it.
d.loc[d["end"] < d.start_year, "end"] = d.loc[d["end"] < d.start_year, "start_year"]
by_title = collections.defaultdict(list)
for i, r in d.iterrows():
    by_title[r.k_title].append(i)


def resolve(link, county=None):
    c = by_title.get(n(link["title"]), [])
    if not c:
        return None
    t = place(link.get("place", ""))
    same = (
        [i for i in c if d.at[i, "k_town"] == t]
        if t
        else [i for i in c if d.at[i, "county"] == county]
    )
    if not same:
        if not t:
            return None  # a bare title outside the county is not evidence
        # The named town has no title of that name: one in the same county, else one elsewhere in the state that
        # began within 4 years of the year the link gives (papers moved between counties: the Intelligencer,
        # Franklin 1819 -> Fayette). A name alone does not cross a county line: "Sun (Liberty, Mo) 1969" is not
        # the Fulton Sun of 1891.
        same = [i for i in c if d.at[i, "county"] == county]
        if not same:
            s0 = re.sub(r"\?", "0", link.get("start") or "")
            if not (s0.isdigit() and "?" not in (link.get("start") or "")):
                return None
            same = [
                i
                for i in c
                if pd.notna(d.at[i, "start_year"])
                and abs(d.at[i, "start_year"] - int(s0)) <= 4
            ]
            if not same:
                return None
    s = re.sub(r"\?", "0", link.get("start") or "")
    s = int(s) if s.isdigit() else None
    return (
        min(
            same,
            key=lambda i: abs(
                (d.at[i, "start_year"] or 0) - (s or d.at[i, "start_year"])
            ),
        )
        if s
        else same[0]
    )


succ = collections.defaultdict(set)
pred = collections.defaultdict(set)
unresolved = 0
for i, r in d.iterrows():
    for k, way in (("succeeding_links", "s"), ("preceding_links", "p")):
        for l in json.loads(r[k] or "[]"):
            j = resolve(l, r.county)
            if j is None or j == i:
                unresolved += j is None
                continue
            a, b = (i, j) if way == "s" else (j, i)
            if d.at[b, "start_year"] + 1 < d.at[a, "start_year"]:
                continue  # a link backwards in time is a catalogue slip
            succ[a].add(b)
            pred[b].add(a)
# Continuations the catalogue did not link. SHSMO still lists the earlier title as current while its film
# stops; film of a title in the same town, sharing a name word other than the town's, resumes within 31
# days; neither has a recorded link. These are one paper going on (often a name dropped some years after
# a merger): "Leader", Brookfield, film to 2003-12-31 -> Linn County Leader, film from 2004-01-02.
CONT_STOP = {
    "the",
    "and",
    "of",
    "mo",
    "daily",
    "weekly",
    "news",
    "county",
    "saint",
    "st",
    "city",
    "missouri",
}


def cont_words(t, town):
    tw = set(re.findall(r"[a-z]+", str(town).lower()))
    return {
        w
        for w in re.findall(r"[a-z]+", str(t).lower())
        if len(w) > 2 and w not in CONT_STOP and w not in tw
    }


continuations = []
PROV = {}  # (pred,succ) -> where the link comes from; SHSMO catalogue unless set
held = d[d.held_first.notna() & d.held_last.notna()]
for (_, _t), g in held.groupby(["county", "k_town"]):
    for a in g.index:
        if succ.get(a) or d.at[a, "catalogue_current"] != "True":
            continue
        for b in g.index:
            if a == b or pred.get(b):
                continue
            gap = (d.at[b, "held_first"] - d.at[a, "held_last"]).days
            if 0 < gap <= 31 and cont_words(
                d.at[a, "title"], d.at[a, "town"]
            ) & cont_words(d.at[b, "title"], d.at[a, "town"]):
                continuations.append((a, b))
                PROV[(a, b)] = (
                    "continuation: film resumes within 31 days, same town, shared name"
                )
# Within a county, a title whose name contains an earlier paper's whole name, with film resuming within 31
# days, carries that paper on (Appleton City Journal -> St. Clair County Courier and Appleton City Journal, 2024).
for (_c), g in held.groupby("county"):
    for a in g.index:
        if succ.get(a):
            continue
        wa = cont_words(d.at[a, "title"], "")
        if len(wa) < 1:
            continue
        for b in g.index:
            if a == b:
                continue
            gap = (d.at[b, "held_first"] - d.at[a, "held_last"]).days
            wb = cont_words(d.at[b, "title"], "")
            if (
                0 < gap <= 31
                and wa < wb
                and d.at[a, "town"] != d.at[b, "town"]
                and len(wa) >= 2
            ):
                continuations.append((a, b))
                PROV[(a, b)] = (
                    "continuation: later name contains the earlier one, film resumes within 31 days"
                )
# Named mergers the catalogue does not link, each with its evidence.
# The SunCrest Call began in 1996 (callnewspapers.com/about-us); the catalogue's 1856 start is an error.
d.loc[
    (d.title.str.lower() == "suncrest call") & (d.county == "St. Louis"), "start_year"
] = 1996
# The Daily Guide (Pulaski County) was first published in July 1971, as the Daily Fort Gateway Guide (reviewer,
# 2026-10-10); SHSMO's catalogue starts it in 1973, its first filmed issue.
d.loc[
    (d.title.str.lower() == "daily fort gateway guide") & (d.county == "Pulaski"),
    "start_year",
] = 1971
EXTRA_LINKS = [  # (title, county) -> (title, county): evidence
    # "As of 2020, we are the St. Louis Call, previously known as the Concord Call, Green Park Call, Mail Call,
    # Oakville Call and SunCrest Call" (callnewspapers.com/about-us). SHSMO's film of the three editions ends 2004.
    (
        ("Concord Call", "St. Louis"),
        ("Oakville Call", "St. Louis"),
        "Call Newspapers About page: consolidated as the St. Louis Call",
    ),
    (
        ("Green Park Call", "St. Louis"),
        ("Oakville Call", "St. Louis"),
        "Call Newspapers About page: consolidated as the St. Louis Call",
    ),
    (
        ("Suncrest Call", "St. Louis"),
        ("Oakville Call", "St. Louis"),
        "Call Newspapers About page: consolidated as the St. Louis Call",
    ),
    (
        ("Monroe County Appeal", "Monroe"),
        ("County Herald-Enterprise", "Monroe"),
        "SHSMO film: Appeal ends 2020-05-28, joint County Herald-Enterprise (Paris and Center) from 2020-06-04; today Monroe | Ralls",
    ),
    (
        ("Ralls County Herald-Enterprise", "Ralls"),
        ("County Herald-Enterprise", "Monroe"),
        "SHSMO film: Herald-Enterprise ends 2020-05-28, joint paper from 2020-06-04",
    ),
    # The Leader began first (1895), so the catalogue's links from these two run backwards in time and are not
    # placed; SHSMO's Audrain entry lists both among the Leader's preceding titles.
    (
        ("Vandalia Mail", "Audrain"),
        ("Vandalia Leader", "Audrain"),
        "SHSMO Audrain directory: preceding title of the Vandalia Leader, 1903-1945",
    ),
    (
        ("Vandalia Press and Laddonia Herald", "Audrain"),
        ("Vandalia Leader", "Audrain"),
        "SHSMO Audrain directory: preceding title of the Vandalia Leader, 1945-1961",
    ),
    # One paper, four SHSMO entries: the catalogue links the first two straight to the Baptist Record as well,
    # which read as a three-way merger (CHAIN_REPLACES drops those).
    (
        ("Western Messenger", "Cole"),
        ("Western Messenger", "St. Louis"),
        "The Western Messenger, organ of the Missouri Negro Baptist Convention, moved Jefferson City -> St. Louis (Dec. 16, 1916) -> Kansas City (1917 or 1918) and was renamed the Baptist Record (reviewer, 2026-10-10; LOC sn 92059017)",
    ),
    (
        ("Western Messenger", "St. Louis"),
        ("Western Messenger", "Jackson"),
        "The Western Messenger, organ of the Missouri Negro Baptist Convention, moved Jefferson City -> St. Louis (Dec. 16, 1916) -> Kansas City (1917 or 1918) and was renamed the Baptist Record (reviewer, 2026-10-10; LOC sn 92059017)",
    ),
    (
        ("Western Messenger", "Jackson"),
        ("Baptist Record", "Jackson"),
        "The Western Messenger, organ of the Missouri Negro Baptist Convention, moved Jefferson City -> St. Louis (Dec. 16, 1916) -> Kansas City (1917 or 1918) and was renamed the Baptist Record (reviewer, 2026-10-10; LOC sn 92059017)",
    ),
]
EXTRA_LINKS += [
    (
        ("Warrenton Journal", "Warren"),
        ("Suburban Journal Warrenton Edition", "Warren"),
        "Suburban Journals: the Wentzville and Warrenton papers combined in 2009 as the Suburban Journal Wentzville/Warrenton Edition (reviewer, 2026-10-10; Wikipedia, 'Suburban Journals'; SHSMO Warren County film)",
    ),
    (
        ("Suburban Journal Warrenton Edition", "Warren"),
        ("Suburban Journal Wentzville/Warrenton Edition", "Warren"),
        "Suburban Journals: the Wentzville and Warrenton papers combined in 2009 as the Suburban Journal Wentzville/Warrenton Edition (reviewer, 2026-10-10; Wikipedia, 'Suburban Journals'; SHSMO Warren County film)",
    ),
    (
        ("Wentzville Messenger Journal", "St. Charles"),
        ("Suburban Journal Wentzville/Warrenton Edition", "Warren"),
        "Suburban Journals: the Wentzville and Warrenton papers combined in 2009 as the Suburban Journal Wentzville/Warrenton Edition (reviewer, 2026-10-10; Wikipedia, 'Suburban Journals'; SHSMO Warren County film)",
    ),
]
EXTRA_LINKS += [
    (
        ("Daily Standard", "Clay"),
        ("Excelsior Springs Standard", "Clay"),
        "newspapers.com groups these titles as The Daily Standard (Excelsior Springs), and the film runs on: Daily Standard to Mar. 31, 1998; Excelsior Springs Standard from Apr. 3, 1998 to Jan. 31, 2020; The Standard from Feb. 7, 2020",
    ),
    (
        ("Excelsior Springs Standard", "Clay"),
        ("The Standard", "Clay"),
        "newspapers.com groups these titles as The Daily Standard (Excelsior Springs), and the film runs on: Daily Standard to Mar. 31, 1998; Excelsior Springs Standard from Apr. 3, 1998 to Jan. 31, 2020; The Standard from Feb. 7, 2020",
    ),
]
# Catalogue links a reviewer's chain replaces: the title did not go straight to that successor.
CHAIN_REPLACES = [
    (("Western Messenger", "Cole"), ("Baptist Record", "Jackson")),
    (("Western Messenger", "St. Louis"), ("Baptist Record", "Jackson")),
]


def find_title(t, c):
    # the catalogue can hold one name twice (Monroe County Appeal, 1875 and 1948): the entry with the latest film
    m = d.index[(d.title.str.lower() == t.lower()) & (d.county == c)]
    if not len(m):
        return None
    return int(
        max(
            m,
            key=lambda i: (
                d.at[i, "held_last"]
                if pd.notna(d.at[i, "held_last"])
                else pd.Timestamp(0)
            ),
        )
    )


for pa, pb in CHAIN_REPLACES:
    a, b = find_title(*pa), find_title(*pb)
    assert (
        a is not None and b is not None
    ), f"chain correction no longer matches: {pa} -> {pb}"
    succ[a].discard(b)
    pred[b].discard(a)
for pa, pb, ev in EXTRA_LINKS:
    a = find_title(*pa)
    b = find_title(*pb)
    if a is None or b is None:
        print("  EXTRA link not found:", pa, pb)
        continue
    succ[a].discard(b)
    pred[b].discard(a)
    continuations.append((a, b))
    PROV[(a, b)] = f"reviewer: {ev}"
# LOC renamings, mergers and splits, earlier title -> later title. LOC states these, so they are kept even where
# the later title began first (a newer paper merged into an older one).
loc_links = 0
for x in LOC[LOC.kind != "move"].itertuples():
    a = loc_find(x.a_title, x.a_town, x.a_county, x.a_start)
    b = loc_find(x.b_title, x.b_town, x.b_county, x.b_start)
    if a is None or b is None:
        print(
            "  LOC link not placed:",
            x.kind,
            "|",
            x.a_title,
            x.a_town,
            x.a_start,
            "->",
            x.b_title,
            x.b_town,
            x.b_start,
            "|",
            x.lccn,
            "| missing:",
            "earlier" if a is None else "",
            "later" if b is None else "",
        )
        continue
    if a == b or b in succ.get(a, ()):
        print(
            "  LOC link already present:",
            x.kind,
            "|",
            x.a_title,
            "->",
            x.b_title,
            "|",
            "same entry" if a == b else "SHSMO now links them",
        )
        continue
    continuations.append((a, b))
    loc_links += 1
    PROV[(a, b)] = f"Library of Congress {x.lccn}"
print("LOC: links added:", loc_links)
for a, b in continuations:
    succ[a].add(b)
    pred[b].add(a)
print("unlinked continuations added:", len(continuations))
[
    print("  CONT", d.at[a, "title"], "->", d.at[b, "title"], d.at[a, "town"])
    for a, b in continuations
]


# A catalogue link from a title in one town to a title in another joins them as one paper (it MOVED) only on
# evidence: a Library of Congress record of either title that places it in both towns; or towns within 40 miles
# with film that runs on (the new town's first issue within a year of the old town's last, overlapping by no more
# than three months) or a name in common. A link across 200 miles, or years apart under a common name ("The
# Rambler", Linneus 1954, linked to the Fair Play Advocate, Polk County, 1943) is not evidence of one paper, and
# the two are separate papers. The same test holds for a split or a merger between towns: three "Rambler"
# entries (Linneus, Trenton, Fair Play) all name the Fair Play Advocate before and after them, and only the Fair
# Play one is near it. Links the Library of Congress or a reviewer states are kept without this test.
import geo as _geo

LOC_DATED = set()  # (title, town) with a dated LOC record: evidence of when it ran
_LOC_PLACES = collections.defaultdict(
    set
)  # normalised title -> towns LOC records it published in
for _r in json.load(open(IN / "loc_newspaper_directory.json")):
    _t = n(re.sub(r"\s*\(.*$", "", _r.get("title") or ""))
    for _c in _r.get("location_city") or []:
        _LOC_PLACES[_t].add(_geo.norm(_c))
        if re.search(r"\b1[789]\d\d\b", _r.get("title") or ""):
            LOC_DATED.add((_t, n(_c)))


def _loc_places_both(a, b):
    ta, tb = _geo.norm(d.at[a, "town"]), _geo.norm(d.at[b, "town"])
    return any({ta, tb} <= _LOC_PLACES.get(n(d.at[i, "title"]), set()) for i in (a, b))


def _continuous(a, b):
    la, fb = d.at[a, "held_last"], d.at[b, "held_first"]
    if pd.notna(la) and pd.notna(fb):
        return -0.25 <= (fb - la).days / 365.25 <= 1
    ea, sb = d.at[a, "end_year"], d.at[b, "start_year"]
    return pd.notna(ea) and pd.notna(sb) and 0 <= sb - ea <= 1


def _near(a, b, limit=40):
    pa = _geo.point(d.at[a, "town"], d.at[a, "county"])
    pb = _geo.point(d.at[b, "town"], d.at[b, "county"])
    return pa is not None and pb is not None and _geo.miles(pa, pb) <= limit


def _shares_name(a, b):
    return bool(
        cont_words(d.at[a, "title"], d.at[a, "town"])
        & cont_words(d.at[b, "title"], d.at[b, "town"])
    )


def _evidence(a, b):
    if _loc_places_both(a, b):
        return "LOC places it in both towns"
    if _near(a, b) and (_continuous(a, b) or _shares_name(a, b)):
        return "nearby, " + ("film runs on" if _continuous(a, b) else "name in common")
    return None


unproven = [
    (a, b)
    for a, bs in succ.items()
    for b in list(bs)
    if (a, b) not in PROV
    and pd.notna(d.at[a, "town"])
    and pd.notna(d.at[b, "town"])
    and d.at[a, "town"] != d.at[b, "town"]
    and _evidence(a, b) is None
]
for a, b in unproven:
    succ[a].discard(b)
    pred[b].discard(a)
print(
    f"catalogue links to another town without evidence, not followed: {len(unproven)}"
)
pd.DataFrame(
    [
        dict(
            title=d.at[a, "title"],
            town=d.at[a, "town"],
            county=d.at[a, "county"],
            last_film=d.at[a, "held_last"],
            next_title=d.at[b, "title"],
            next_town=d.at[b, "town"],
            next_county=d.at[b, "county"],
            next_first_film=d.at[b, "held_first"],
        )
        for a, b in unproven
    ]
).to_csv(OUT / "links_to_another_town_not_followed.csv", index=False)
# union-find over continuity edges
par = list(range(len(d)))


def f(x):
    while par[x] != x:
        par[x] = par[par[x]]
        x = par[x]
    return x


merged_out = set()
for b, ps in pred.items():
    if not ps:
        continue  # its only link was one not followed
    ps = sorted(ps, key=lambda a: (d.at[a, "start_year"], a))
    keep = ps[0]
    par[f(keep)] = f(b)
    for a in ps[1:]:
        if len(succ[a]) == 1:
            merged_out.add(a)  # absorbed into b's lineage
        else:
            pass
d["lineage"] = [f(i) for i in range(len(d))]
# The registry is the authority for the present: each registry newspaper is matched to its SHSMO title
# in the same county -- exact name and town first, else the title sharing most of its significant words
# (half or more) -- among titles SHSMO still lists as current or has filmed since 2000. A matched title
# is publishing today, whatever the film says. Spelling differs between the two ("News Tribune" /
# "Jefferson City News Tribune", "News Press Now" / "St. Joseph News-Press"), so name equality alone
# left ~59 live papers looking closed.
import csv as _csv

REG = REGISTRY
STOP = {
    "the",
    "and",
    "of",
    "news",
    "newspaper",
    "county",
    "daily",
    "weekly",
    "co",
    "online",
    "mo",
    "missouri",
}
W = lambda t: {
    w
    for w in re.sub(r"[^a-z0-9 ]+", " ", str(t).lower().replace("/", " ")).split()
    if len(w) > 2 and w not in STOP
}
d["W"] = d.title.map(W)
d["cty"] = (
    d.county.astype(str)
    .str.replace(".", "", regex=False)
    .str.lower()
    .str.replace(" ", "")
)
recent = d.cur | (d.held_last.dt.year >= 2000)


# The registry is the source of truth for which papers publish today: active print papers (and print-only and
# replica rows), not student papers or magazines.
def reg_live(x):
    # local newsrooms, whatever they publish in -- print or digital -- not broadcasters
    alive = (
        x["status"] == "active"
        and x["type"] in ("print native", "newspaper", "digital native")
    ) or x["status"] in ("print", "replica")
    student = bool(re.search(r"universit|college", x["owner"], re.I))
    magazine = bool(re.search(r"magazine", x["outlet"], re.I))
    # not local news (reviewer, 2026-10-10); the registry carries it once sources.status is updated
    not_local = x["outlet"] in ("Metro Voice Christian Newspaper", "Missouri Lawyers")
    # a company site whose papers are registry rows of their own (northmissourinews.com: the Post-Telegraph,
    # Unionville Republican, The Courier, Beachcomber and Amish Country) -- not a newsroom to count again
    if x["outlet"] in ("North Missouri News",):
        return False
    return (
        alive
        and x["county_fips"].startswith("29")
        and not student
        and not magazine
        and not not_local
    )


LIVE_REG = {x["outlet"]: x for x in _csv.DictReader(open(REG)) if reg_live(x)}
d["in_registry"] = False
d["reg_name"] = None
d["reg_town"] = None
matched = 0
for x in _csv.DictReader(open(REG)):
    if x["outlet"] not in LIVE_REG:
        continue
    c = x["county"].replace(" County", "").replace(".", "").lower().replace(" ", "")
    pool = d[recent & (d.cty == c)]
    exact = pool[(pool.k_title == n(x["outlet"])) & (pool.k_town == place(x["city"]))]
    if len(exact):
        d.loc[exact.index, "in_registry"] = True
        d.loc[exact.index, "reg_name"] = x["outlet"]
        d.loc[exact.index, "reg_town"] = x["city"]
        matched += 1
        continue
    w = W(x["outlet"])
    if not w or pool.empty:
        continue
    sc = pool.W.map(lambda v: len(w & v) / len(w))
    if sc.max() >= 0.5:
        top = sc[sc == sc.max()].index
        best = max(
            top,
            key=lambda i: (
                d.at[i, "held_last"]
                if pd.notna(d.at[i, "held_last"])
                else pd.Timestamp(0)
            ),
        )
        d.at[best, "in_registry"] = True
        d.at[best, "reg_name"] = x["outlet"]
        d.at[best, "reg_town"] = x["city"]
        matched += 1
# Second pass: a live registry paper whose SHSMO film stopped before 2000 (the Lawrence County Record,
# filed as "Record", Mount Vernon, to 1989) is the same paper when an older title in the SAME TOWN shares
# at least half its significant words. The registry says it publishes today, so its lineage does.
older = 0
matched_ids = set(d.index[d.in_registry])
for x in _csv.DictReader(open(REG)):
    if x["outlet"] not in LIVE_REG:
        continue
    c = x["county"].replace(" County", "").replace(".", "").lower().replace(" ", "")
    pool = d[(d.cty == c) & (d.k_town == place(x["city"]))]
    w = W(x["outlet"])
    if pool.empty or not w:
        continue
    sc = pool.W.map(lambda v: len(w & v) / len(w))
    if sc.max() < 0.5:
        continue
    top = sc[sc == sc.max()].index
    if any(i in matched_ids for i in top):
        continue
    best = max(
        top,
        key=lambda i: (
            d.at[i, "held_last"] if pd.notna(d.at[i, "held_last"]) else pd.Timestamp(0)
        ),
    )
    if not d.at[best, "in_registry"]:
        d.at[best, "in_registry"] = True
        d.at[best, "reg_name"] = x["outlet"]
        d.at[best, "reg_town"] = x["city"]
        older += 1
print(
    "registry newspapers matched to an SHSMO title:",
    matched,
    "| plus older same-town titles:",
    older,
)
# Registry names that share no word with their SHSMO title: the registry's "Monroe | Ralls" is the County
# Herald-Enterprise (Paris) under its current flag.
REG_ALIAS = {
    ("County Herald-Enterprise", "Monroe"): ("Monroe | Ralls", "Paris"),
    # fstop's print weekly (the Jasper County Citizen merged into it, Dec 2025) -- not Carthage News Online,
    # Drop Cap Publishing's separate digital newsroom, which shares only the town's name
    ("Carthage Chronicle", "Jasper"): ("Carthage Chronicle", "Sarcoxie"),
    # the combined edition of the Ash Grove Commonwealth and the Republic Monitor (2016); the registry files it
    # at Squibb Media's Mount Vernon office (Lawrence County), SHSMO at Republic (Greene)
    ("Greene County Commonwealth", "Greene"): (
        "Greene County Commonwealth",
        "Mount Vernon",
    ),
    # the St. Louis Call (2020), formerly the Oakville Call and its sister editions
    ("Oakville Call", "St. Louis"): ("St. Louis Call Newspapers", "St. Louis"),
}
for (t, c), (nm, town) in REG_ALIAS.items():
    i = find_title(t, c)
    if i is not None:
        d.at[i, "in_registry"] = True
        d.at[i, "reg_name"] = nm
        d.at[i, "reg_town"] = town


# A title that carries on into a later one is not itself the paper publishing today -- the later title is.
# (The Monroe County Appeal and Ralls County Herald-Enterprise film runs to May 2020, inside ACTIVE_FROM, but
# both became the County Herald-Enterprise in June.)
def carried_on(i):
    # a successor that began after this title's film ended (not a spin-off begun while it kept publishing)
    hl = d.at[i, "held_last"]
    return pd.notna(hl) and any(
        pd.notna(d.at[b, "held_first"]) and (d.at[b, "held_first"] - hl).days >= -31
        for b in succ[i]
    )


for i in d.index:
    if succ.get(i) and carried_on(i):
        d.at[i, "active"] = False
        if d.at[i, "in_registry"]:
            # the registry paper is the title it became: follow the line to its latest title and match it there
            j = i
            seen = {i}
            while succ.get(j):
                nxt = max(
                    succ[j],
                    key=lambda b: (
                        d.at[b, "held_last"]
                        if pd.notna(d.at[b, "held_last"])
                        else pd.Timestamp(0)
                    ),
                )
                if nxt in seen:
                    break
                seen.add(nxt)
                j = nxt
            if not d.at[j, "in_registry"]:
                d.at[j, "in_registry"] = True
                d.at[j, "reg_name"] = d.at[i, "reg_name"]
                d.at[j, "reg_town"] = d.at[i, "reg_town"]
            d.at[i, "in_registry"] = False
            d.at[i, "reg_name"] = None
            d.at[i, "reg_town"] = None
# Third pass: a live registry paper still unmatched is the continuation of its town's most recent filmed paper
# (film to 2010 or later) when that town has exactly one such paper left unmatched (News-Xpress, Butler, is today's
# Mid American News-Review).
reg_matched = set(d.reg_name.dropna())
third = 0
NOT_THE_TOWNS_PAPER = {
    "Pulaski County Weekly"
}  # Salem bought it with the Rolla Daily News in 2021 and closed the RDN
for nm, x in LIVE_REG.items():
    if nm in reg_matched or nm in NOT_THE_TOWNS_PAPER:
        continue
    c = x["county"].replace(" County", "").replace(".", "").lower().replace(" ", "")
    pool = d[
        (d.cty == c)
        & (d.k_town == place(x["city"]))
        & (d.held_last.dt.year >= 2010)
        & (~d.in_registry)
    ]
    pool = pool[[not succ.get(i) for i in pool.index]]
    if len(pool) == 1:
        i = pool.index[0]
        d.at[i, "in_registry"] = True
        d.at[i, "reg_name"] = nm
        d.at[i, "reg_town"] = x["city"]
        third += 1
print("registry: same-town recent paper matched:", third)
# Publishing today is the registry's word alone: SHSMO film to 2020 or later no longer makes a paper live.
# One registry paper is one paper: where its name landed on titles in more than one line, it stays on the most
# recently filmed title (lines are not yet built here, so compare by catalogue reach: the latest film).
for nm, g in d[d.in_registry].groupby("reg_name"):
    if len(g) < 2:
        continue
    keep = max(
        g.index,
        key=lambda i: (
            d.at[i, "held_last"] if pd.notna(d.at[i, "held_last"]) else pd.Timestamp(0)
        ),
    )
    for i in g.index:
        if i != keep and not (keep in succ.get(i, ()) or i in succ.get(keep, ())):
            d.at[i, "in_registry"] = False
            d.at[i, "reg_name"] = None
            d.at[i, "reg_town"] = None
d["active"] = d.in_registry & d.reg_name.isin(list(LIVE_REG))
# End years were set while SHSMO's film still decided who was live. A title the registry does not count as live
# ends at its catalogued end or, failing that, its last filmed issue (the Rolla Daily News, "1946-current" with
# film to April 2021, ended 2021, not 1946); a live one has no end.
d["end"] = np.where(d.active, np.nan, d.end_year.fillna(d.held_last.dt.year))
d["end"] = pd.to_numeric(d["end"]).fillna(d.start_year)
d.loc[d["end"] < d.start_year, "end"] = d.loc[d["end"] < d.start_year, "start_year"]
unmatched_live = [nm for nm in LIVE_REG if nm not in set(d.reg_name.dropna())]
print(
    "registry live papers:",
    len(LIVE_REG),
    "| matched to an SHSMO line:",
    len(LIVE_REG) - len(unmatched_live),
    "| no SHSMO line:",
    len(unmatched_live),
)
pd.Series(unmatched_live, name="outlet").to_csv(
    OUT / "registry_live_without_shsmo.csv", index=False
)
rows = []
for L, g in d.groupby("lineage"):
    idx = list(g.index)
    first = min(idx, key=lambda i: d.at[i, "start_year"])
    last = max(idx, key=lambda i: (d.at[i, "end"], d.at[i, "active"]))
    active = bool(g.active.any())
    if active:
        end_type = "still publishing"
    elif any(i in merged_out for i in idx) and not any(
        succ[i] - set(idx) and i not in merged_out for i in idx
    ):
        end_type = "merged"
    elif succ[last] - set(idx):
        end_type = "merged"
    else:
        end_type = "closed"
    # The paper that absorbed a merged one: the lineage of the title its last title flowed into.
    into = None
    if end_type == "merged":
        outs = [b for i in idx for b in succ[i] if b not in set(idx)]
        if outs:
            into = int(d.at[max(outs, key=lambda b: d.at[b, "start_year"]), "lineage"])
    rows.append(
        dict(
            lineage=L,
            into=into,
            start=int(g.start_year.min()),
            end=None if active else int(g.end.max()),
            end_type=end_type,
            founded=len(pred[first]) == 0,
            titles=len(g),
            name=(
                g.reg_name.dropna().iloc[0]
                if g.reg_name.notna().any()
                else d.at[last, "title"]
            ),
            town=(
                g.reg_town.dropna().iloc[0]
                if g.reg_town.notna().any()
                else d.at[last, "town"]
            ),
            # The registry is the truth for where a paper is now; the catalogue is the truth for its past.
            county=(
                LIVE_REG[g.reg_name.dropna().iloc[0]]["county"].replace(" County", "")
                if active and g.reg_name.dropna().iloc[0] in LIVE_REG
                else d.at[last, "county"]
            ),
            registry=g.reg_name.dropna().iloc[0] if g.reg_name.notna().any() else "",
            # Known only from surviving issues: no title dated in the catalogue, under a year of film, and no
            # other record of it. When it began and ended is unknown, so it is shown as the issues that survive
            # -- publishing in the years they cover, neither founded nor closed then (the Wentzville Messenger
            # Journal was one, until Wikipedia and its 2009 title said otherwise).
            # Map-only: no record of when it opened or closed -- no catalogued dates for any of its titles, no
            # dated Library of Congress record of them, not in the registry. Its film or digitized issues show
            # only that issues survive, so it is not in the river or the county trees, and the map shows it as
            # those issues (the reviewer: "we need evidence for open/close to be in the river or lineage").
            surviving_issues=bool(
                not active
                and end_type == "closed"  # a merger is a record of how it ended
                and g.pub_dates.isna().all()
                and not any(
                    (d.at[i, "k_title"], d.at[i, "k_town"]) in LOC_DATED for i in idx
                )
                and not g.reg_name.notna().any()
                and g.held_first.notna().all()
            ),
        )
    )
lin = pd.DataFrame(rows)
# The registry records mergers SHSMO has not filmed or linked: a registry row with status "merged" and a
# named survivor (merged_into: a name, or the host the paper is now published on) is evidence that the
# paper ended by merging into that survivor. Its SHSMO lineage is found by name within the county; the
# survivor's likewise (by outlet name, or by the outlet whose host it names). The year is the one the
# registry gives ("Dec 2025"), else the last issue SHSMO filmed. A paper merged in the current year is
# not publishing at the present checkpoint, so its end is the year before.
lin["registry_merge"] = ""


def lineage_for(name, county, prefer_active=True):
    w = W(name)
    c = str(county).replace(" County", "").replace(".", "").lower().replace(" ", "")
    pool = d[d.cty == c]
    if not w or pool.empty:
        return None
    sc = pool.W.map(lambda v: len(w & v) / len(w))
    if sc.max() < 0.5:
        return None
    top = sc[sc == sc.max()].index
    best = max(
        top,
        key=lambda i: (
            (d.at[i, "active"] if prefer_active else 0),
            d.at[i, "held_last"] if pd.notna(d.at[i, "held_last"]) else pd.Timestamp(0),
        ),
    )
    return int(d.at[best, "lineage"])


reg_rows = list(_csv.DictReader(open(REG)))
by_host = {}
for (
    x
) in (
    reg_rows
):  # survivors are live outlets; a merged row sharing the host is the paper itself
    h = x["host"].lower().replace("www.", "").strip("/")
    if h and x["map"] == "yes" and x["status"] != "merged":
        by_host.setdefault(h.split("/")[0], x)
review = []
li = lin.set_index("lineage")
# Datadesk's recorded merger events (visuals.OutletEvent: merged, or status -> merged), exported to
# datadesk_merged_events.csv: their date and survivor outrank the registry's text.
EV = {}
for e in _csv.DictReader(open(IN / "datadesk_merged_events.csv")):
    if e["outlet_id"]:
        EV[e["outlet_id"]] = e
reg_by_id = {x["outlet_id"]: x for x in reg_rows}
# The registry's "merged" means "no website of its own" (for collection), not a merger in print: eight of
# its merged rows are papers still printing under a group's site (MPA, LNI, Blue Book). Only events with
# evidence of the paper itself ending count here, at their own year; 2026 events end after the last
# checkpoint, so the paper is still publishing in 2025 but not today.
PRINT_EVENTS = {  # registry outlet -> (year, how it ended, evidence)
    "The Monett Times": (
        2024,
        "merged",
        "Lawrence County Record, 2024-06-26: part of the Record from the July 3, 2024 issue",
    ),
    "Jasper County Citizen": (
        2025,
        "merged",
        "MPA February 2026 Notebook: combined with the Carthage Chronicle, Dec 2025",
    ),
    "Lee's Summit Missouri Journal News": (
        2026,
        "merged",
        "datadesk event: merged into The Kansas City Star, March 2026",
    ),
    "Farmington Press": (
        2026,
        "merged",
        "datadesk event: a section of the Daily Journal; a separate title as of Sept 2025",
    ),
    "Grant City Times Tribune": (
        2026,
        "closed",
        "MPA 2026-04-03: closed Feb. 26, 2026",
    ),
    # final issue Jan 1, 2021; the name continues as pages of the Wednesday Standard Democrat (Sikeston, Scott
    # County). The registry files the paper under Scott, its survivor's county; SHSMO files it in New Madrid.
    "New Madrid Weekly Record": (
        2021,
        "merged",
        "Standard Democrat 2021-01-19: final issue Jan 1, 2021; continues as pages of the Standard Democrat",
        "New Madrid",
        "Weekly record",
    ),
}
merges = [
    x
    for x in reg_rows
    if x["outlet"] in PRINT_EVENTS and x["status"] in ("merged", "closed")
]
merges += [
    reg_by_id[i]
    for i in EV
    if i in reg_by_id
    and reg_by_id[i]["outlet"] in PRINT_EVENTS
    and reg_by_id[i]["status"] not in ("merged", "closed")
]
for x in merges:
    if not x["county_fips"].startswith("29"):
        continue
    e = EV.get(x["outlet_id"])
    if e:
        x = dict(x)
        x["merged_into"] = e["merged_into"] or x["merged_into"]
        if e["effective_date"]:
            x["status_basis"] = e["effective_date"] + " " + x["status_basis"]
    ev0 = PRINT_EVENTS.get(x["outlet"])
    # an event may name the SHSMO title and county outright, where the registry's name or county would not find it
    L = (
        lineage_for(ev0[4], ev0[3], prefer_active=False)
        if ev0 and len(ev0) > 4
        else lineage_for(
            x["outlet"],
            ev0[3] if ev0 and len(ev0) > 3 else x["county"],
            prefer_active=False,
        )
    )
    if L is None:
        print("  registry merge, no SHSMO title:", x["outlet"])
        continue
    into = x["merged_into"].strip()
    host = re.sub(r"^https?://", "", into.lower()).replace("www.", "").split("/")[0]
    surv = None
    surv_row = None
    if into in reg_by_id:  # an event names the survivor by its registry id
        surv_row = reg_by_id[into]
        surv = lineage_for(surv_row["outlet"], surv_row["county"])
    elif "." in host and host in by_host:
        surv_row = by_host[host]
        surv = lineage_for(surv_row["outlet"], surv_row["county"])
    if surv is None and into:
        nm = re.sub(r"\(.*?\)", "", into).strip()
        surv_row = surv_row or next(
            (
                y
                for y in reg_rows
                if y["map"] == "yes"
                and y["status"] != "merged"
                and n(y["outlet"]) == n(nm)
            ),
            None,
        )
        surv = lineage_for(nm, x["county"]) or (
            lineage_for(surv_row["outlet"], surv_row["county"]) if surv_row else None
        )
    if surv == L:
        # SHSMO already files this paper inside its survivor's lineage (The Home Press in the Macon
        # County Home Press, the Appleton City Journal in the Courier): the merger is already drawn.
        print(f"  {x['outlet']}: already inside its survivor's lineage")
        continue
    m = re.search(r"\b(18|19|20)\d{2}\b", x["status_basis"] + " " + x["merged_into"])
    shsmo_end = li.at[L, "end"]
    ev = PRINT_EVENTS.get(x["outlet"])
    if ev and ev[1] == "closed":
        li.at[L, "end_type"] = "closed"
        li.at[L, "end"] = ev[0]
        li.at[L, "into"] = None
        li.at[L, "registry_merge"] = f"{x['outlet']} closed {ev[0]}"
        print(f"  {x['outlet']}: closed {ev[0]}")
        continue
    if ev:
        yr = ev[0]
    elif m:
        yr = int(m.group(0))
    elif pd.notna(shsmo_end) and shsmo_end >= 2000:
        yr = int(shsmo_end)
    elif li.at[L, "end_type"] == "still publishing":
        yr = 2024
    else:
        review.append(
            dict(
                outlet=x["outlet"],
                county=x["county"],
                merged_into=into,
                shsmo_last_year=shsmo_end,
            )
        )
        print(
            f"  {x['outlet']}: no year in the registry and SHSMO's last issue is {shsmo_end}; left for review"
        )
        continue
    # a survivor live in the registry but not on SHSMO film is still publishing: -1 says so
    if surv is None and surv_row is not None:
        surv = -1
    li.at[L, "end_type"] = "merged"
    li.at[L, "end"] = yr
    li.at[L, "into"] = surv
    li.at[L, "registry_merge"] = f"{x['outlet']} -> {x['merged_into']}"
    print(
        f"  {x['outlet']}: ended {yr}, into {'a registry paper not on SHSMO film' if surv==-1 else ('lineage '+str(surv) if surv is not None else 'survivor not identified')}"
    )
lin = li.reset_index()
# A paper the registry says has CLOSED closed, whatever the catalogue's last link says, and in the year the registry
# gives when it gives one (the Newton County News: "closed 2025"; SHSMO's last link read as a 2024 merger).
REG_ROWS = {x["outlet"]: x for x in _csv.DictReader(open(REG))}
for i, x in lin.iterrows():
    # matched to a registry row, or -- a paper no longer live -- the registry row of its name in its county
    r = REG_ROWS.get(x.registry) if isinstance(x.registry, str) and x.registry else None
    if r is None:
        r = REG_ROWS.get(x["name"])
        if r is not None and r["county"].replace(" County", "") != x.county:
            r = None
    if r is None or r["status"] != "closed" or x.end_type == "still publishing":
        continue
    y = re.search(r"(18|19|20)\d\d", r.get("status_basis") or "")
    # only the paper the registry row describes: one whose catalogued end is near the registry's closing year (an
    # older paper of the same name in the same county is another paper)
    if not y or pd.isna(x.end) or abs(int(y.group(0)) - int(x.end)) > 5:
        continue
    print(
        f"  registry: {x['name']} ({x.county}) {x.end_type} {int(x.end)} -> closed {y.group(0)}"
    )
    lin.at[i, "end_type"], lin.at[i, "into"], lin.at[i, "end"] = (
        "closed",
        None,
        int(y.group(0)),
    )
pd.DataFrame(review).to_csv(OUT / "registry_mergers_for_review.csv", index=False)
print(f"titles {len(d)}, links unresolved {unresolved}, lineages {len(lin)}")
print(
    lin.end_type.value_counts().to_dict(),
    "| earliest",
    lin.start.min(),
    "| still publishing",
    (lin.end_type == "still publishing").sum(),
)
print(
    lin.sort_values("start")
    .head(5)[["start", "end", "end_type", "name", "town"]]
    .to_string(index=False)
)
lin.to_csv(OUT / "shsmo_lineages.csv", index=False)
pd.DataFrame(
    [
        dict(pred=a, succ=b, source=PROV.get((a, b), "SHSMO catalogue"))
        for a, bs in succ.items()
        for b in bs
    ]
).to_csv(OUT / "shsmo_edges.csv", index=False)
d.to_csv(OUT / "shsmo_titles_resolved.csv", index=False)
