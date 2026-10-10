"""Parse SHSMO county newspaper directories (files.shsmo.org/research/newspapers/counties/<County>.pdf).

One row per catalogued title: county, town, title, publication years as catalogued, frequency, and the
preceding / succeeding / related titles SPLIT into structured links; plus the span of issues SHSMO holds
on microfilm (held_first / held_last), which dates a title when the catalogue says only "19??" or "current".
"""

import csv
import datetime as dt
import json
import re
import sys

import pdfplumber
from paths import IN, OUT, REGISTRY  # noqa: F401

REEL = re.compile(
    r"^(?P<t>.+?) (?P<b>\d{1,2}/\d{1,2}/\d{4}) (?P<e>\d{1,2}/\d{1,2}/\d{4}) (?P<reel>\S+) "
)
#: Reel rows the two-date pattern misses: one date, or none, then a reel number and its status columns.
REEL_STUB = re.compile(r"(\d{1,2}/\d{1,2}/\d{4} )?\d{3,6} (Filming|Yes|No)\b")


def looks_like_town(line):
    """A town heading is a short place name: no digits, no colon, no reel columns. Anything else
    above a title is a wrapped subtitle or a stray reel row, and the town carries over.
    """
    return (
        bool(line)
        and len(line) <= 40
        and not re.search(r"[\d:]", line)
        and not REEL_STUB.search(line)
    )


NOISE = (
    "County Newspaper Directory",
    "Title Begin Date End Date",
    "Number Copy for ILL Online",
    "Reels with a Patron Copy",
    "Centers. Reels available",
    "the online column",
    "Newspapers marked as Online",
)
LABELS = (
    "Dates of Publication",
    "Frequency",
    "Preceding Title",
    "Succeeding Title",
    "Related Titles",
)
KEY = {
    "Preceding Title": "preceding",
    "Succeeding Title": "succeeding",
    "Related Titles": "related",
}
LINK = re.compile(
    r"(?P<title>[^;()]+?)\s*\((?P<place>[^()]*)\)\s*(?P<s>[\d?]{4}|1\?\?\?)?\s*-?\s*(?P<e>[\d?]{4}|[Cc]urrent)?"
)


def lines(path):
    out = []
    with pdfplumber.open(path) as p:
        for pg in p.pages:
            for l in (pg.extract_text() or "").splitlines():
                l = l.strip()
                if (
                    not l
                    or any(n in l for n in NOISE)
                    or re.search(r"Page \d+ of \d+$", l)
                ):
                    continue
                out.append(l)
    return out


def links(text):
    """Linked titles as written: "Title (Town, Mo) 1906 - 1927", several to a field; a bare title with no
    place in parentheses ("Pike County News") is a link too, resolved later within the same county.
    """
    out = []
    if text and "(" not in text:
        for t in re.split(r";\s*", text):
            t = t.strip(" ;,")
            if t:
                out.append(dict(title=t, place="", start="", end=""))
        return out
    for m in LINK.finditer(text or ""):
        t = m["title"].strip(" ;,")
        if t:
            out.append(
                dict(
                    title=t,
                    place=m["place"].strip(),
                    start=(m["s"] or "").strip(),
                    end=(m["e"] or "").strip(),
                )
            )
    return out


def year(v, lo=True):
    v = (v or "").strip()
    if not v or v.lower() == "current":
        return None
    if "?" in v:
        v = v.replace("?", "0" if lo else "9")
    try:
        return int(v[:4])
    except ValueError:
        return None


_SIG = lambda t: {
    w
    for w in re.findall(r"[a-z0-9]+", str(t).lower())
    if len(w) > 2 and w not in ("the", "and", "daily", "weekly")
}


def same_paper(reel_title, cur):
    """Does a reel row's title belong to the open entry? Its own name, a name it has already used on a reel, or
    one sharing at least half its significant words with either (catalogue and reel names vary: "Missourian"
    for "Columbia Missourian")."""
    if cur is None:
        return True
    # a heading owns the first reels printed under it, whatever name they carry (the County Herald-Enterprise's
    # reels are filed under its current flag, "Monroe-Ralls"); the name test is for reels after its own
    if not cur["reel_titles"]:
        return True
    names = [cur["title"], *cur["reel_titles"]]
    w = _SIG(reel_title)
    if not w:
        return True
    for nm in names:
        v = _SIG(nm)
        if v and len(w & v) / min(len(w), len(v)) >= 0.5:
            return True
    return False


def parse(path, county):
    L = lines(path)
    titles = []
    town = None
    cur = None
    field = None
    for i, l in enumerate(L):
        if l.startswith("Dates of Publication"):
            prev = L[i - 1] if i else ""
            if prev.startswith(LABELS) or REEL.match(
                prev
            ):  # page-continuation template: same title continues
                field = "dates"
                continue
            prev2 = L[i - 2] if i > 1 else ""
            if (
                i > 1
                and not REEL.match(prev2)
                and not prev2.startswith(LABELS)
                and looks_like_town(prev2)
            ):
                town = prev2
            cur = dict(
                county=county,
                town=town,
                title=prev,
                pub_dates=l[len("Dates of Publication") :].strip(),
                frequency="",
                preceding="",
                succeeding="",
                related="",
                held_first=None,
                held_last=None,
                reels=set(),
                reel_titles={},
            )
            titles.append(cur)
            field = "dates"
            continue
        if cur is None:
            continue
        hit = next((lab for lab in LABELS[1:] if l.startswith(lab)), None)
        if hit:
            field = hit
            v = l[len(hit) :].strip()
            if v:
                cur[KEY.get(hit, "frequency")] = v
            continue
        m = REEL.match(l)
        if m and not same_paper(m["t"], cur):
            # A reel row names its title. One that names a different paper belongs to a catalogue entry printed
            # without its heading (the entry's label block was read as the open title's page continuing): the
            # Sunday Herald's 1856-60 reels were credited to the SunCrest Call. Start that entry from its reels.
            cur = dict(
                county=county,
                town=town,
                title=m["t"],
                pub_dates="",
                frequency="",
                preceding="",
                succeeding="",
                related="",
                held_first=None,
                held_last=None,
                reels=set(),
                reel_titles={},
            )
            titles.append(cur)
        if m:
            b = dt.datetime.strptime(m["b"], "%m/%d/%Y").date()
            e = dt.datetime.strptime(m["e"], "%m/%d/%Y").date()
            cur["held_first"] = min(filter(None, [cur["held_first"], b]))
            cur["held_last"] = max(filter(None, [cur["held_last"], e]))
            cur["reels"].add(m["reel"])
            cur["reel_titles"][m["t"]] = cur["reel_titles"].get(m["t"], 0) + 1
            field = None
            continue
        nxt = L[i + 1] if i + 1 < len(L) else ""
        if field in KEY and not nxt.startswith("Dates of Publication"):
            cur[KEY[field]] = (cur[KEY[field]] + " " + l).strip()
    for t in titles:
        # a heading with no catalogue record ("Blytheville AR") is a place: the title is what the reels say
        if not t["pub_dates"] and not t["frequency"] and t["reel_titles"]:
            rt = max(t["reel_titles"], key=t["reel_titles"].get)
            if rt.lower() != t["title"].lower():
                t["town"] = t["title"] if not t["town"] else t["town"]
                t["title"] = rt
        a, _, b = t["pub_dates"].partition("-")
        t["start"] = a.strip()
        t["end"] = b.strip()
        t["start_year"] = year(t["start"]) or (
            t["held_first"].year if t["held_first"] else None
        )
        cur_ = t["end"].lower() == "current"
        t["end_year"] = (
            None
            if cur_
            else (
                year(t["end"], lo=False)
                if t["end"] and "?" not in t["end"]
                else (
                    t["held_last"].year if t["held_last"] else year(t["end"], lo=False)
                )
            )
        )
        t["catalogue_current"] = cur_
        for k in KEY.values():
            t[k + "_links"] = json.dumps(links(t[k]))
        t["reels"] = len(t["reels"])
        t.pop("reel_titles")
    return titles


COLS = [
    "county",
    "town",
    "title",
    "start",
    "end",
    "start_year",
    "end_year",
    "catalogue_current",
    "pub_dates",
    "frequency",
    "preceding",
    "succeeding",
    "related",
    "preceding_links",
    "succeeding_links",
    "related_links",
    "held_first",
    "held_last",
    "reels",
]
if __name__ == "__main__":
    import glob
    import os

    out = csv.DictWriter(
        open(sys.argv[2], "w", newline=""), fieldnames=COLS, extrasaction="ignore"
    )
    out.writeheader()
    for p in sorted(glob.glob(os.path.join(sys.argv[1], "*.pdf"))):
        c = os.path.basename(p)[:-4]
        try:
            rows = parse(p, c)
            out.writerows(rows)
            print(f"{c}: {len(rows)}", file=sys.stderr)
        except Exception as e:
            print(f"{c}: FAILED {e}", file=sys.stderr)
