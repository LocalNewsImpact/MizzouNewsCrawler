"""Parse the Newspapers of Missouri listing out of the Blue Book text.

    pdftotext -layout -f 7 -l 21 -x 0   -W 213 -H 648 9_Information.pdf L.txt
    pdftotext -layout -f 7 -l 21 -x 218 -W 214 -H 648 9_Information.pdf R.txt
    python tools/parse_mo_bluebook.py listing.txt newspapers.json

The crop is 218pt, not the half-width 216: at 216 one character of the left
column bleeds into the right on four pages, and a city line starting with that
stray character stops being a city.

See docs/THE_BLUE_BOOK_LISTS_THE_NEWSPAPERS.md.

One record per newspaper. The listing is two columns per page, already
separated into reading order by the caller.

An entry looks like:

    Belle/Vienna                 <- the city or cities it serves
    MARIES COUNTY ADVOCATE       <- the name, in capitals
    www.mariescountyadvocate.com <- the site, where there is one
    Editorial email: news@wardpub.com
    1110 Hwy. 28, Unit B, PO Box 540, Belle 65013
    Telephone: (573) 437-2323 (Belle); (573) 422-6323 (Vienna)
    Publisher: Dennis Warden
    Editor: Dave Marner
    Wed. (Rep)                   <- publishing day and political affiliation
"""

import json
import re
import sys

# The running header, and the two halves the column split leaves of it:
# "MISSOURI INFORMA" on the left of the cut and "ATION — NEWSPAPERS ..." on the
# right. Matched as halves because neither is a whole header any more.
RUNNING_HEADER = re.compile(
    r"^\s*(\d+\s+)?("
    r"OFFICIAL MANUAL"
    r"|MISSOURI INFORMA(TION\b.*)?"
    r"|[A-Z]*TION\s*[—–-]\s*NEWSPAPERS OF MISSOURI.*"
    r"|.*NEWSPAPERS OF MISSOURI\s*\d*"
    r")\s*(\d+)?\s*$"
)
# The name is set in capitals. Lower-case letters appear only in a few
# names carrying a small word, so a line is a name when it has no run of
# lower-case letters outside parentheses.
NAME = re.compile(r"^[A-Z0-9][A-Z0-9 .,&'’\-–—/()!]{3,}$")
CITY = re.compile(r"^[A-Z][A-Za-z.'’\- ]+(/[A-Z][A-Za-z.'’\- ]+)*$")
ROLE = re.compile(r"^([A-Z][A-Za-z /&.\-]{2,40}?):\s*(.+)$")
# One entry prints "Publisher Donald Suggs" with the colon missing. Only the
# known role words, so an address like "Main St. Joseph" is not read as a role.
ROLE_NO_COLON = re.compile(
    r"^(Publisher/Editor|Publisher|Editor|General Manager|Managing Editor)"
    r"\s+([A-Z][A-Za-z.'’\- ]+)$"
)
URL = re.compile(r"^(www\.|https?://)\S+$")
PHONE = re.compile(r"^Telephone:\s*(.+)$")
# "Thurs. (Rep)", "Wed. & Sat. (Rep)", "Fri (NP)", "Daily (Ind)"
SCHEDULE = re.compile(r"^[A-Z][A-Za-z.&,\- ]*\((Rep|Dem|Lib|Ind|NP)\)\s*$")
ZIP = re.compile(r"\b(\d{5})(-\d{4})?\s*$")
#: A ZIP alone on a continuation line, all that fit of the address above it.
ORPHAN_ZIP = re.compile(r"^\d{5}(-\d{4})?$")

NOT_A_NAME = {
    "PO BOX",
    "OFFICIAL MANUAL",
}


def _dehyphenate(lines):
    """Rejoin a value the column break split across two lines.

    Two shapes, both indented continuations:

    `Telephone: (573) 422-6323 (Vi-` / `    enna)` -- the line before ends in a
    hyphen, so the halves join with nothing between them.

    `106 E. Washington Ave., PO Box 540, Owensville` / `    65066` -- an address
    whose ZIP would not fit. Left alone it reads as a record named "65066",
    which is how Owensville and Palmyra came out.
    """
    out = []
    for line in lines:
        indented = line.startswith("    ") and line.strip()
        if out and indented and out[-1].rstrip().endswith("-"):
            out[-1] = out[-1].rstrip()[:-1] + line.strip()
            continue
        if out and indented and ORPHAN_ZIP.match(line.strip()):
            out[-1] = out[-1].rstrip() + " " + line.strip()
            continue
        out.append(line)
    return out


def parse(text):
    lines = _dehyphenate([line.rstrip() for line in text.splitlines()])
    records = []
    current = None
    city = None
    for raw in lines:
        line = raw.strip()
        if not line or RUNNING_HEADER.match(raw):
            continue

        role = ROLE.match(line)
        is_name = (
            NAME.match(line)
            and not role
            and line.upper() not in NOT_A_NAME
            and not URL.match(line)
        )

        if is_name:
            # A name too long for the column runs on to a second line, e.g.
            # "CRANE CHRONICLE/STONE COUNTY" + "REPUBLICAN". It is a
            # continuation while the record has collected nothing else.
            if current and not any(
                (
                    current["url"],
                    current["editorial_email"],
                    current["address"],
                    current["people"],
                    current["schedule"],
                )
            ):
                current["name"] = f"{current['name']} {line}"
                continue
            if current:
                records.append(current)
            current = {
                "name": line,
                "city_line": city or "",
                "url": "",
                "editorial_email": "",
                "address": [],
                "telephone": "",
                "fax": "",
                "people": {},
                "schedule": "",
                "affiliation": "",
            }
            continue

        if current is None:
            if CITY.match(line):
                city = line
            continue

        if URL.match(line):
            if not current["url"]:
                current["url"] = line
            continue

        if role:
            label, value = role.group(1).strip(), role.group(2).strip()
            if label == "Editorial email":
                current["editorial_email"] = value
            elif label == "Telephone":
                phone, _, fax = value.partition("/ FAX:")
                current["telephone"] = phone.strip()
                current["fax"] = fax.strip()
            else:
                current["people"][label] = value
            continue

        loose = ROLE_NO_COLON.match(line)
        if loose:
            current["people"][loose.group(1)] = loose.group(2).strip()
            continue

        if SCHEDULE.match(line):
            schedule, _, affiliation = line.rpartition("(")
            current["schedule"] = schedule.strip()
            current["affiliation"] = affiliation.rstrip(")").strip()
            continue

        # A city heading only starts a new entry; inside one it is an address.
        if ZIP.search(line) or "," in line or line.startswith("PO Box"):
            current["address"].append(line)
            continue

        if CITY.match(line):
            city = line
            continue

        current["address"].append(line)

    if current:
        records.append(current)
    return records


def main():
    records = parse(open(sys.argv[1]).read())
    for record in records:
        record["address"] = ", ".join(record["address"])
        cities = [c.strip() for c in record.pop("city_line").split("/") if c.strip()]
        record["cities"] = cities
        record["city"] = cities[0] if cities else ""
    json.dump(records, open(sys.argv[2], "w"), indent=2, ensure_ascii=False)
    print(f"{len(records)} records -> {sys.argv[2]}")


if __name__ == "__main__":
    main()
