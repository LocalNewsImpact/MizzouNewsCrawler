"""Compare the Blue Book listing against the Mizzou dataset.

    python tools/compare_mo_bluebook.py

COUNT HOSTS, NOT MASTHEADS. The book lists mastheads and we hold domains, and
36 of its entries share 15 hosts -- St. Charles Community News and St. Louis
Community News are one office on www.mycnews.com, and myleaderpaper.com carries
four. Counting entries said 199 newspapers and 61 we do not hold; counting the
sites they publish on says 155 and 35.

A source is matched on `host` OR `host_norm`. The Washington Missourian is
`www.missourian.com` with a `host_norm` of `www.emissourian.com`, which is the
host the book prints -- matching on `host` alone reported it missing.

See docs/THE_BLUE_BOOK_LISTS_THE_NEWSPAPERS.md.
"""

import csv
import json
import os
import re
from collections import defaultdict

BOOK = "src/lookups/mo_bluebook_newspapers_2025_2026.json"
#: `host<TAB>host_norm<TAB>canonical_name<TAB>city<TAB>county<TAB>owner<TAB>type
#: <TAB>status<TAB>articles` for the dataset, as `psql -At -F'\t'` writes it.
OURS = os.environ.get("MIZZOU_SOURCES_TSV", "mizzou_sources.tsv")
OUT = os.environ.get("BLUEBOOK_OUT", "src/lookups/")


def bare(host):
    """A host reduced to what identifies the site: no www, no case."""
    return (host or "").strip().lower().removeprefix("www.")


def key(name):
    """A publication name reduced for comparison.

    Case, punctuation and the words a masthead carries either way -- "The",
    and the paper-type words -- come off, because "Daily Star-Journal" and
    "The Daily Star Journal" are one paper.
    """
    n = (name or "").lower()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    words = [w for w in n.split() if w not in {"the", "a", "of"}]
    return " ".join(words)


book = json.load(open(BOOK))
ours = []
with open(OURS) as fh:
    for row in csv.reader(fh, delimiter="\t"):
        if len(row) < 9:
            continue
        host, host_norm, name, city, county, owner, type_, status, articles = row[:9]
        ours.append(
            {
                "host": host,
                "bare": bare(host),
                # A site can be recorded under either column. The Washington
                # Missourian is `www.missourian.com` with a `host_norm` of
                # `www.emissourian.com`, which is the host the Blue Book prints
                # -- matching on `host` alone reported it as one we do not hold.
                "bare_norm": bare(host_norm),
                "name": name,
                "city": city,
                "county": county,
                "owner": owner,
                "type": type_,
                "status": status,
                "articles": int(articles or 0),
            }
        )

ours_by_host = {}
for o in ours:
    for spelling in (o["bare"], o["bare_norm"]):
        if spelling:
            ours_by_host.setdefault(spelling, o)
ours_by_name = defaultdict(list)
for o in ours:
    if o["name"]:
        ours_by_name[key(o["name"])].append(o)

matched, by_name_only, missing = [], [], []
for b in book:
    b_bare = bare(b["host"])
    hit = ours_by_host.get(b_bare)
    # A host may sit under a path in the book ("...com/thecarrolltondemocrat")
    # while we hold the bare domain, which `bare()` already reduces to the same
    # thing. A name hit without a host hit is the interesting middle case.
    name_hits = ours_by_name.get(key(b["name"]), [])
    if hit:
        matched.append((b, hit, name_hits))
    elif name_hits:
        by_name_only.append((b, name_hits))
    else:
        missing.append(b)

book_bares = {bare(b["host"]) for b in book if b["host"]}
book_names = {key(b["name"]) for b in book}
not_in_book = [
    o
    for o in ours
    if o["bare"]
    and o["bare"] not in book_bares
    and o["bare_norm"] not in book_bares
    and key(o["name"]) not in book_names
]

print(f"Blue Book newspapers      : {len(book)}")
print(f"  with a website          : {sum(1 for b in book if b['host'])}")
print(f"Mizzou sources            : {len(ours)}")
print()
print(f"Matched on host           : {len(matched)}")
print(f"Matched on name, not host : {len(by_name_only)}")
print(f"In the book, not in ours  : {len(missing)}")
print(f"In ours, not in the book  : {len(not_in_book)}")

with open(OUT + "mo_bluebook_diff_name_mismatch.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["host", "book_name", "our_name", "book_city", "our_city", "our_articles"])
    n = 0
    for b, o, _ in matched:
        if key(b["name"]) != key(o["name"]):
            w.writerow([o["host"], b["name"], o["name"], b["city"], o["city"], o["articles"]])
            n += 1
print(f"\nName differs on a matched host: {n}  -> diff_name_mismatch.csv")

with open(OUT + "mo_bluebook_diff_url_mismatch.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["book_name", "book_url", "our_host", "our_name", "our_articles"])
    for b, hits in by_name_only:
        for o in hits:
            w.writerow([b["name"], b["url"], o["host"], o["name"], o["articles"]])
print(f"Same paper, different host   : {len(by_name_only)}  -> diff_url_mismatch.csv")

with open(OUT + "mo_bluebook_missing_from_ours.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["name", "city", "url", "host", "publisher", "editor", "address", "telephone"])
    for b in missing:
        w.writerow([b["name"], b["city"], b["url"], b["host"], b["publisher"],
                    b["editor"], b["address"], b["telephone"]])
print(f"In the book, not in ours     : {len(missing)}  -> missing_from_ours.csv")

with open(OUT + "mo_bluebook_not_in_the_book.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["host", "name", "city", "county", "owner", "type", "status", "articles"])
    for o in sorted(not_in_book, key=lambda r: -r["articles"]):
        w.writerow([o["host"], o["name"], o["city"], o["county"], o["owner"],
                    o["type"], o["status"], o["articles"]])
print(f"In ours, not in the book     : {len(not_in_book)}  -> not_in_the_book.csv")

json.dump(
    {
        "missing_hosts": [b["host"] for b in missing if b["host"]],
        "missing": missing,
    },
    open(OUT + "mo_bluebook_missing.json", "w"),
    indent=2,
)
