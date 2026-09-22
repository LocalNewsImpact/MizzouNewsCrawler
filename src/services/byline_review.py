"""What a byline string is, and which ones a person should look at.

`articles.author` is what a parser made of a page. Across the Mizzou corpus --
98,210 local articles, 200 hosts, every one with an owner recorded -- that is
7,921 distinct strings, and a count of them is a count of spellings rather than
of people:

    2,854  several names in one string   "Aamer Madhani, Regina Garcia Cano"
      936  one person, several spellings "Nate Sanford" / "Nate Sandford"
      649  same name, unrelated owners   a syndication or a parse, not a person
      527  a list literal                `["Stanley Schwartz"]`, `[]`
      148  a single token                "Admin" (700 articles, 6 hosts)
       84  a publication suffix          "Abby Volz - Southeast Arrow"
       66  a job title                   "Amanda Barnes, Komu 8 Wellness Coach"
       43  digits                        "ABC 17 News Team"

Nobody reads 7,921 rows. The signals below are what a review queue is ordered
by: each one names a specific defect, carries what it would propose, and can be
accepted in one gesture.

TWO THINGS THIS MODULE DOES NOT DECIDE.

A name on hosts with different owners is *reported*, never resolved here: it can
be one reporter filing for two papers, a syndicated story the wire check missed,
or a parser reading a wire byline as local. Which it is takes a person, and the
answer is a disposition on the ARTICLE, not on the byline.

And a decision is per dataset. The same string can be a person in one corpus and
a desk in another.
"""

from __future__ import annotations

import ast
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

#: Statuses that are "a local story we kept". The pipeline files wire, opinion,
#: obituaries, weather and the rest under their own statuses, so a byline report
#: over these is a report about local reporting.
LOCAL_STATUSES = ("enriched", "labeled", "cleaned", "enrichment_skipped")

#: Job titles and desk words that ride along after a name. Matched as whole
#: words: "Fellows" is a surname, "fellow" after a comma is a title.
TITLE_WORDS = (
    "reporter",
    "reporters",
    "editor",
    "editors",
    "staff writer",
    "staff",
    "correspondent",
    "columnist",
    "photographer",
    "photojournalist",
    "intern",
    # Before "fellow", so the phrase wins the alternation and "Murrow" does
    # not survive as a name: the WSU Murrow College's students carry it.
    "murrow fellow",
    "fellow",
    "publisher",
    "contributor",
    "freelancer",
    "producer",
    "anchor",
    "director",
    "coach",
    "officer",
    "outgoing",
    "incoming",
    "meteorologist",
    "administrator",
    "president",
    "chief",
    "spokesman",
    "spokeswoman",
    "special to",
    "contributed",
    "newsroom",
    "news team",
    "team",
)
_TITLE_RE = re.compile(
    r"(?i)(?:^|[\s,;/|-])(" + "|".join(TITLE_WORDS) + r")(?:$|[\s,;/|-])"
)
_SEPARATORS = re.compile(r"\s*(?:,|;|&| and )\s*", re.I)
_PUBLICATION_RE = re.compile(r"[/|]|\s-\s")
_CONTACT_RE = re.compile(r"(?i)@|\bwww\.|\.com\b|\.net\b|\.org\b")
_DIGIT_RE = re.compile(r"\d")

#: Signal keys. The order is the order a queue works them in: a mechanical
#: defect with an obvious repair first, a judgement call last.
LIST_LITERAL = "list_literal"
SPELLING_VARIANT = "spelling_variant"
STRAY_TITLE = "stray_title"
PUBLICATION_SUFFIX = "publication_suffix"
CONTACT_FRAGMENT = "contact_fragment"
NOT_A_PERSON = "not_a_person"
MULTIPLE_NAMES = "multiple_names"
CROSS_OWNER = "cross_owner"

SIGNAL_ORDER = (
    LIST_LITERAL,
    SPELLING_VARIANT,
    STRAY_TITLE,
    PUBLICATION_SUFFIX,
    CONTACT_FRAGMENT,
    NOT_A_PERSON,
    MULTIPLE_NAMES,
    CROSS_OWNER,
)

SIGNAL_LABELS = {
    LIST_LITERAL: "Stored as a list literal",
    SPELLING_VARIANT: "One person, several spellings",
    STRAY_TITLE: "Carries a job title",
    PUBLICATION_SUFFIX: "Carries a publication name",
    CONTACT_FRAGMENT: "Carries an address or domain",
    NOT_A_PERSON: "Does not look like a person",
    MULTIPLE_NAMES: "Several names in one string",
    CROSS_OWNER: "Same name, unrelated owners",
}


@dataclass
class BylineRow:
    """One raw byline string in one dataset, with what is known about it."""

    raw: str
    articles: int
    hosts: tuple[str, ...]
    owners: tuple[str, ...]
    signals: tuple[str, ...] = ()
    proposed: tuple[str, ...] = ()
    #: The other spellings of the same normalised name, when there are any.
    variants: tuple[str, ...] = ()

    @property
    def top_signal(self) -> str | None:
        for signal in SIGNAL_ORDER:
            if signal in self.signals:
                return signal
        return None

    @property
    def needs_review(self) -> bool:
        return bool(self.signals)

    @property
    def unchanged(self) -> bool:
        """The proposal is the string itself -- nothing to write."""
        return tuple(self.proposed) == (self.raw.strip(),)


def unwrap_list_literal(raw: str) -> list[str] | None:
    """The names inside `["A", "B"]`, or None when it is not one.

    A September 2025 defect stored the cleaner's OUTPUT LIST rather than its
    names: 1,716 Mizzou articles read `["Stanley Schwartz"]` and 188 read `[]`.
    `ast.literal_eval` rather than `json.loads` because the value was written by
    `str(list)` and carries single quotes.
    """
    text = (raw or "").strip()
    if not (text.startswith("[") and text.endswith("]")):
        return None
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(value, (list, tuple)):
        return None
    return [str(item).strip() for item in value if str(item).strip()]


def split_names(raw: str) -> list[str]:
    """The people a byline string names, in order.

    Separators only -- this does not repair a name, and never invents one.
    A part that is a title or a publication is dropped; a part that is neither
    is kept exactly as written, because a reviewer is the one who decides
    whether "Nate Sandford" is a typo or a different person.
    """
    unwrapped = unwrap_list_literal(raw)
    if unwrapped is not None:
        return [name for part in unwrapped for name in split_names(part)]
    names = []
    for index, part in enumerate(_SEPARATORS.split(raw or "")):
        part = part.strip().strip("-–—|/ ").strip()
        if not part or _looks_like_contact(part):
            continue
        # "Abby Volz - Southeast Arrow": the name is what comes first.
        part = _PUBLICATION_RE.split(part)[0].strip()
        if not part:
            continue
        if _looks_like_a_title(part):
            # A TITLE AFTER A NAME IS A PART OF ITS OWN and is dropped:
            # "Patrick Fudally, Officer", "Amanda Barnes, Komu 8 Wellness
            # Coach". A title INSIDE the first part is riding along with the
            # name -- "Henry Brannan Murrow Fellow Sarah Wolf" -- and dropping
            # the part there loses both people, so the title comes out and
            # what is left stands for a reviewer to split.
            if index > 0:
                continue
            part = _strip_titles(part)
            if not part:
                continue
        names.append(part)
    return names


def _strip_titles(part: str) -> str:
    """The part with its title words removed, spaces collapsed."""
    previous = None
    text = f" {part} "
    while previous != text:
        previous = text
        text = _TITLE_RE.sub(" ", text)
    return " ".join(text.split()).strip(" ,;/|-")


def _looks_like_a_title(part: str) -> bool:
    stripped = part.strip()
    if not stripped:
        return False
    return bool(_TITLE_RE.search(f" {stripped} "))


def _looks_like_contact(part: str) -> bool:
    return bool(_CONTACT_RE.search(part or ""))


def normalised_name(name: str) -> str:
    """A name reduced to what two spellings of it share.

    Accents, case and punctuation go: "Reneé Dìaz", "Renee-Diaz" and
    "renee diaz" are one key. Word ORDER is kept -- "Smith John" is not
    "John Smith", and treating them as one would merge two people.
    """
    decomposed = unicodedata.normalize("NFKD", name or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", stripped.lower()).split())


def signals_for(row: BylineRow) -> tuple[str, ...]:
    """Every defect this string shows. A string can show several."""
    raw = row.raw or ""
    found: list[str] = []
    if unwrap_list_literal(raw) is not None:
        found.append(LIST_LITERAL)
    if _TITLE_RE.search(f" {raw} "):
        found.append(STRAY_TITLE)
    if _PUBLICATION_RE.search(raw):
        found.append(PUBLICATION_SUFFIX)
    if _CONTACT_RE.search(raw):
        found.append(CONTACT_FRAGMENT)
    names = split_names(raw)
    if len(names) > 1:
        found.append(MULTIPLE_NAMES)
    if not names or (len(names) == 1 and len(normalised_name(names[0]).split()) < 2):
        # One word is a desk, a bot or a stub: "Admin", "AbbVie", "Aber".
        found.append(NOT_A_PERSON)
    if _DIGIT_RE.search(raw) and NOT_A_PERSON not in found:
        found.append(NOT_A_PERSON)
    if len(row.owners) > 1:
        found.append(CROSS_OWNER)
    return tuple(found)


def review_rows(
    rows: Iterable[tuple[str, str, str, int]],
) -> list[BylineRow]:
    """Build the reviewable rows from `(byline, host, owner, articles)`.

    One row per distinct raw string, carrying every host and owner it appears
    under, the defects it shows, and what would be written if the proposal were
    accepted.
    """
    grouped: dict[str, dict] = defaultdict(
        lambda: {"articles": 0, "hosts": set(), "owners": set()}
    )
    for raw, host, owner, articles in rows:
        entry = grouped[raw]
        entry["articles"] += int(articles or 0)
        if host:
            entry["hosts"].add(host)
        if owner:
            entry["owners"].add(owner)

    built = [
        BylineRow(
            raw=raw,
            articles=entry["articles"],
            hosts=tuple(sorted(entry["hosts"])),
            owners=tuple(sorted(entry["owners"])),
        )
        for raw, entry in grouped.items()
    ]

    # Spellings of one name. Computed across the dataset rather than per row,
    # because a variant is a relationship: the same key, or near enough to it.
    single: dict[str, BylineRow] = {}
    by_key: dict[str, list[BylineRow]] = defaultdict(list)
    for row in built:
        names = split_names(row.raw)
        if len(names) == 1:
            single[row.raw] = row
            by_key[normalised_name(names[0])].append(row)

    variants: dict[str, set[str]] = defaultdict(set)
    for siblings in by_key.values():
        # Same key: accents, case and punctuation differ and nothing else.
        for row in siblings:
            for other in siblings:
                if other.raw != row.raw:
                    variants[row.raw].add(other.raw)
    for a_raw, b_raw in _near_pairs(single):
        variants[a_raw].add(b_raw)
        variants[b_raw].add(a_raw)

    for row in built:
        found = list(signals_for(row))
        names = split_names(row.raw)
        if variants.get(row.raw):
            found.append(SPELLING_VARIANT)
            row.variants = tuple(sorted(variants[row.raw]))
        row.signals = tuple(dict.fromkeys(found))
        row.proposed = tuple(names)
    return built


#: How alike two spellings must be to be OFFERED as the same person. 0.88 pairs
#: "Nate Sanford"/"Nate Sandford" (0.96), "Sarah Wolf"/"Sarah Wolfe" (0.95) and
#: also "Alex Frick"/"Alex Brick" (0.90), who are two people. That is the
#: intended behaviour: this proposes a pair and never merges one. A reviewer
#: says which it is, and the cost of a wrong pair is a glance.
NEAR_MATCH = 0.88


def _near_pairs(single: dict[str, BylineRow]):
    """Pairs of one-name strings close enough to be the same person.

    Blocked on the OWNER and on the first letter of the name: two reporters at
    unrelated publishers with similar names are two reporters, and comparing
    every string with every other is quadratic over 7,921 of them.
    """
    from difflib import SequenceMatcher

    blocks: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for raw, row in single.items():
        key = normalised_name(split_names(raw)[0]) if split_names(raw) else ""
        if not key:
            continue
        for owner in row.owners or ("(unknown)",):
            blocks[(owner, key[:1])].append((raw, key))
    seen: set[tuple[str, str]] = set()
    for members in blocks.values():
        for index, (a_raw, a_key) in enumerate(members):
            for b_raw, b_key in members[index + 1 :]:
                if a_key == b_key:
                    continue  # already paired by key
                pair = (a_raw, b_raw) if a_raw < b_raw else (b_raw, a_raw)
                if pair in seen:
                    continue
                seen.add(pair)
                if SequenceMatcher(None, a_key, b_key).ratio() >= NEAR_MATCH:
                    yield pair


def candidates(rows: Iterable[tuple[str, str, str, int]]) -> list[BylineRow]:
    """The rows a person should look at, worst first.

    Ordered by which defect, then by how many articles carry it: a mechanical
    repair that clears 700 rows is worth more of a reviewer's attention than
    one that clears one.
    """
    ranked = [row for row in review_rows(rows) if row.needs_review]
    order = {signal: index for index, signal in enumerate(SIGNAL_ORDER)}

    def rank(row: BylineRow) -> tuple[int, int, str]:
        # `needs_review` is what put the row here, so `top_signal` is set --
        # but it is `str | None` in general and the default keeps it honest.
        signal = row.top_signal
        return (order[signal] if signal else 99, -row.articles, row.raw)

    ranked.sort(key=rank)
    return ranked


#: The rows a dataset's byline review reads. One row per (byline, host, owner).
_ROWS_SQL = """
    SELECT a.author AS byline, s.host_norm AS host,
           coalesce(nullif(trim(s.owner), ''), '(unknown)') AS owner,
           count(*) AS articles
      FROM articles a
      JOIN candidate_links cl ON cl.id = a.candidate_link_id
      JOIN sources s ON s.id = cl.source_id
     WHERE cl.dataset_id = :dataset_id
       AND a.status = ANY(:statuses)
       AND coalesce(trim(a.author), '') <> ''
     GROUP BY 1, 2, 3
"""

#: A decision reaches only the dataset it was made in, and only the rows that
#: still carry the string it was made about.
_APPLY_SQL = """
    UPDATE articles a
       SET author = :author
      FROM candidate_links cl
     WHERE cl.id = a.candidate_link_id
       AND cl.dataset_id = :dataset_id
       AND a.author = :raw_byline
       AND a.status = ANY(:statuses)
"""


def dataset_rows(session, dataset_id: str, statuses=LOCAL_STATUSES):
    """`(byline, host, owner, articles)` for one dataset's local stories."""
    from sqlalchemy import text

    result = session.execute(
        text(_ROWS_SQL), {"dataset_id": dataset_id, "statuses": list(statuses)}
    )
    return [(row[0], row[1], row[2], row[3]) for row in result]


def apply_decision(
    session, dataset_id: str, raw_byline: str, names, statuses=LOCAL_STATUSES
) -> int:
    """Write a decision's names onto every article still carrying the string.

    Returns the number of rows written. The article's byline is the permanent
    record, so a decision is not finished until it is here -- the table keeps
    it so a later extraction writing the raw form again can be corrected
    without a person deciding twice.
    """
    from sqlalchemy import text

    result = session.execute(
        text(_APPLY_SQL),
        {
            "author": rendered(names),
            "dataset_id": dataset_id,
            "raw_byline": raw_byline,
            "statuses": list(statuses),
        },
    )
    return int(getattr(result, "rowcount", 0) or 0)


def bylines_with_hosts(rows) -> list[dict]:
    """REPORT ONE: every unique local byline and the hosts it appears on.

    The unit is the PERSON, not the string: a byline naming three reporters
    counts for each of them, and two spellings a reviewer has resolved count
    once. `hosts` is why a reviewer looks twice -- a person on hosts with
    different owners is either filing for both or is not a local byline at all.
    """
    people: dict[str, dict] = {}
    for row in review_rows(rows):
        for name in row.proposed:
            entry = people.setdefault(
                name,
                {
                    "byline": name,
                    "articles": 0,
                    "hosts": set(),
                    "owners": set(),
                    "raw_forms": set(),
                },
            )
            entry["articles"] += row.articles
            entry["hosts"].update(row.hosts)
            entry["owners"].update(row.owners)
            entry["raw_forms"].add(row.raw)
    out = []
    for entry in people.values():
        out.append(
            {
                "byline": entry["byline"],
                "articles": entry["articles"],
                "hosts": len(entry["hosts"]),
                "host_list": ", ".join(sorted(entry["hosts"])),
                "owners": len(entry["owners"]),
                "owner_list": ", ".join(sorted(entry["owners"])),
                "raw_forms": len(entry["raw_forms"]),
            }
        )
    out.sort(key=lambda e: (-e["articles"], e["byline"]))
    return out


def hosts_with_bylines(rows) -> list[dict]:
    """REPORT TWO: every host and how many unique bylines it carries.

    Counted over people, so a host that files "A, B" and "A" has two bylines
    rather than three strings.

    PER HOST, from the rows themselves. Built from the byline's own totals it
    was wrong twice over: a byline appearing on four hosts gave each of them
    all four hosts' articles, and every owner those hosts belong to -- which
    on Mizzou printed all 50 owners against every host.
    """
    names_for: dict[str, tuple[str, ...]] = {}
    hosts: dict[str, dict] = {}
    for raw, host, owner, articles in rows:
        if not host:
            continue
        if raw not in names_for:
            names_for[raw] = tuple(split_names(raw))
        entry = hosts.setdefault(
            host, {"host": host, "articles": 0, "bylines": set(), "owners": set()}
        )
        entry["articles"] += int(articles or 0)
        entry["bylines"].update(names_for[raw])
        if owner:
            entry["owners"].add(owner)
    out = [
        {
            "host": entry["host"],
            "unique_bylines": len(entry["bylines"]),
            "articles": entry["articles"],
            "owner": ", ".join(sorted(entry["owners"])),
        }
        for entry in hosts.values()
    ]
    out.sort(key=lambda e: (-e["unique_bylines"], e["host"]))
    return out


def rendered(names: Iterable[str]) -> str:
    """What goes into `articles.author` for a decision's names.

    Comma-separated, which is what the byline cleaner writes and what every
    reader of the column already expects. No names is an empty byline, not the
    string "[]".
    """
    return ", ".join(name.strip() for name in names if name and name.strip())
