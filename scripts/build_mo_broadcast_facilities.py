"""Where each Missouri broadcaster's licensed facility is, from the FCC.

A broadcaster's licensee address is its owner's headquarters -- Sinclair's
in Maryland, Audacy's in Pennsylvania -- and says nothing about where the
station is. The facility is: the FCC licenses a transmitter at a point, for
a community. This reads both from the FCC's per-station query and writes
src/lookups/mo_broadcast_facilities.csv, which the outlet registry joins by
website.

Call signs are mapped by hand, by website, because a newsroom's name often
does not carry its call sign: KY3 is KYTV, Fox 2 Now is KTVI, STL Public
Radio is KWMU, ABC 30 is KDNL.

    python scripts/build_mo_broadcast_facilities.py
"""

from __future__ import annotations

import csv
import datetime
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "lookups" / "mo_broadcast_facilities.csv"

#: website -> call signs, the station the newsroom is first.
CALLS = {
    "ktvo.com": ["KTVO"],
    "abc17news.com": ["KMIZ"],
    "kbia.org": ["KBIA"],
    "komu.com": ["KOMU-TV"],
    "kq2.com": ["KQTV"],
    "krcgtv.com": ["KRCG"],
    "kbsi23.com": ["KBSI"],
    "kfvs12.com": ["KFVS-TV"],
    "krcu.org": ["KRCU"],
    "ozarksfirst.com": ["KOLR"],
    "929thebeat.com": ["KOSP"],
    "ksmu.org": ["KSMU"],
    "ky3.com": ["KYTV", "KSPR-LD"],
    "ktts.com": ["KTTS-FM"],
    "northwestmoinfo.com": ["KAAN-FM", "KAAN"],
    "kprs.com": ["KPRS", "KPRT"],
    "fox4kc.com": ["WDAF-TV"],
    "kctv5.com": ["KCTV"],
    "kcur.org": ["KCUR-FM"],
    "kmbc.com": ["KMBC-TV"],
    "kshb.com": ["KSHB-TV"],
    "koamnewsnow.com": ["KOAM-TV"],
    "fourstateshomepage.com": ["KODE-TV"],
    "newstalkkzrg.com": ["KZRG"],
    "949kcmo.com": ["KCMO-FM"],
    "audacy.com": ["KMBZ-FM"],
    "khqa.com": ["KHQA-TV"],
    "kxcv.org": ["KXCV"],
    "mymoinfo.com": ["KREI"],
    "abcstlouis.com": ["KDNL-TV"],
    "audacy.com/971talk": ["KFTK-FM"],
    "firstalert4.com": ["KMOV"],
    "fox2now.com": ["KTVI", "KPLR-TV"],
    "ksdk.com": ["KSDK"],
    "stlpr.org": ["KWMU"],
    "legends1063.fm": ["KRZK"],
}

QUERIES = ("tvq", "fmq")

#: A call sign is reused across the country -- KPRT is a Kansas City AM and a
#: New Mexico FM -- so a licence counts only in Missouri or a state whose
#: stations are licensed to serve it.
STATES = ("MO", "KS", "IL", "IA", "AR", "NE", "OK", "TN", "KY")

#: The CDBS facility file. The AM text query no longer answers -- all of
#: Missouri returns nothing -- so an AM station gets its community and
#: licence from here, without transmitter coordinates.
CDBS = "https://transition.fcc.gov/Bureaus/MB/Databases/cdbs/facility.zip"


def _dms(parts):
    deg, minutes, sec = (float(p) for p in parts)
    return deg + minutes / 60 + sec / 3600


def parse(line: str):
    """One pipe-delimited FCC record: call, service, status, community, the
    transmitter's coordinates, the facility id and the licensee."""
    f = [p.strip() for p in line.split("|")]
    if len(f) < 30:
        return None
    for i in range(len(f) - 8):
        if f[i] in ("N", "S") and f[i + 4] in ("W", "E"):
            try:
                lat = _dms(f[i + 1 : i + 4]) * (1 if f[i] == "N" else -1)
                lon = _dms(f[i + 5 : i + 8]) * (-1 if f[i + 4] == "W" else 1)
            except ValueError:
                continue
            facility = next((p for p in f[i - 8 : i] if p.isdigit() and len(p) >= 3), "")
            licensee = next((p for p in f[i + 8 : i + 14] if p and not p[0].isdigit()), "")
            return {
                "call": f[1], "service": f[3], "status": f[9], "community": f[10],
                "state": f[11], "facility_id": facility, "tx_lat": round(lat, 6),
                "tx_lon": round(lon, 6), "licensee": licensee,
            }
    return None


def lookup(call: str):
    base = call.split("-")[0]
    for q in QUERIES:
        url = f"https://transition.fcc.gov/fcc-bin/{q}?call={base}&list=4"
        with urllib.request.urlopen(url, timeout=30) as resp:
            text = resp.read().decode("latin-1")
        records = [
            r
            for r in (parse(line) for line in text.splitlines())
            if r and r["state"] in STATES
        ]
        records = [r for r in records if r["status"] == "LIC" and r["call"] == call] or [
            r for r in records if r["status"] == "LIC" and r["call"].split("-")[0] == base
        ]
        if records:
            return records[0], url
        time.sleep(0.5)
    return None, ""


def cdbs_facilities():
    """{call sign: record} from the CDBS facility file, Missouri region only."""
    import io
    import zipfile

    with urllib.request.urlopen(CDBS, timeout=120) as resp:
        data = zipfile.ZipFile(io.BytesIO(resp.read())).read("facility.dat")
    out = {}
    for line in data.decode("latin-1").splitlines():
        f = line.split("|")
        if len(f) < 18 or f[16] != "LICEN" or f[1] not in STATES:
            continue
        out[f[5]] = {
            "call": f[5], "service": f[10], "status": "LIC", "community": f[0],
            "state": f[1], "facility_id": f[14], "tx_lat": "", "tx_lon": "",
            "licensee": "",
        }
    return out


def main():
    today = datetime.date.today().isoformat()
    rows = []
    cdbs = None
    for host, calls in CALLS.items():
        for rank, call in enumerate(calls):
            record, url = lookup(call)
            if record is None:
                cdbs = cdbs if cdbs is not None else cdbs_facilities()
                record = cdbs.get(call) or cdbs.get(call.split("-")[0])
                url = CDBS if record else ""
            rows.append({
                "host": host, "call_sign": call, "primary": "yes" if rank == 0 else "no",
                **(record or {"call": call}), "source_url": url, "fetched": today,
            })
            print(host, call, (record or {}).get("community"), (record or {}).get("tx_lat"),
                  (record or {}).get("tx_lon"))
    fields = ["host", "call_sign", "primary", "service", "facility_id", "community",
              "state", "tx_lat", "tx_lon", "licensee", "status", "source_url", "fetched"]
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
