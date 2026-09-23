"""What a byline string is, and which ones a person should look at.

`articles.author` is what a parser made of a page. Across the Mizzou corpus --
98,210 local articles, 200 hosts, every one with an owner recorded -- that is
7,921 distinct strings, and a count of them is a count of spellings rather than
of people:

      936  one person, several spellings "Nate Sanford" / "Nate Sandford"
      649  same name, unrelated owners   a syndication or a parse, not a person
      527  a list literal                `["Stanley Schwartz"]`, `[]`
      148  a single token                "Admin" (700 articles, 6 hosts)
       84  a publication suffix          "Abby Volz - Southeast Arrow"
       66  a job title                   "Amanda Barnes, Komu 8 Wellness Coach"
       43  digits                        "ABC 17 News Team"

SEVERAL NAMES IN ONE STRING IS NOT A DEFECT. Stories have co-authors, and the
byline is their list -- `", ".join(names)` is what extraction writes, and the
`["A", "B"]` rows are a September 2025 serialisation of the same list. The work
is to parse it into one record per person, aligned to the article and the host
it ran on, which is what the reports below do. It is never a queue row.

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
import json
import logging
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

logger = logging.getLogger(__name__)

#: The local stories that reached the export. `labeled` is NOT here: those are
#: classified and not enriched, so they are not in BigQuery and not in anything
#: anybody has read -- 81,786 of Mizzou's 98,210, carrying 7,156 byline strings
#: of their own. Reviewing them is reviewing a backlog nobody has published.
#:
#: The CLI takes `--statuses` for the other question.
LOCAL_STATUSES = ("enriched", "enrichment_skipped")

#: Job titles and desk words that ride along after a name.
#:
#: MOST OF THESE ARE ALSO SURNAMES. Marcus Officer files for fox4kc; there are
#: people called President, Chief and Coach. So a word from this list never
#: removes a name on its own -- see `_looks_like_a_title` for the two tests
#: that do.
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
#: Only the phrases. A single ambiguous word is never cut out of a name --
#: "Marcus Officer" would become "Marcus" -- but "Murrow Fellow" between two
#: names is a title whatever surrounds it.
_MULTIWORD_TITLE_RE = re.compile(
    r"(?i)(?:^|[\s,;/|-])("
    + "|".join(word for word in TITLE_WORDS if " " in word)
    + r")(?:$|[\s,;/|-])"
)
#: Words that are not names but are not titles either: what is left of a part
#: once the titles are out is only a name if something is left.
_TITLE_TOKENS = frozenset(
    token for word in TITLE_WORDS for token in word.lower().split()
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
CROSS_OWNER = "cross_owner"

#: NOT in `SIGNAL_ORDER`: a list literal is a storage form, not a judgement.
#: `repair_list_literals` rewrites those rows to the current form, and nobody
#: is asked about them.
SIGNAL_ORDER = (
    SPELLING_VARIANT,
    STRAY_TITLE,
    PUBLICATION_SUFFIX,
    CONTACT_FRAGMENT,
    NOT_A_PERSON,
    CROSS_OWNER,
)

SIGNAL_LABELS = {
    SPELLING_VARIANT: "One person, several spellings",
    STRAY_TITLE: "Carries a job title",
    PUBLICATION_SUFFIX: "Carries a publication name",
    CONTACT_FRAGMENT: "Carries an address or domain",
    NOT_A_PERSON: "Does not look like a person",
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
    #: A reviewer has said what this string is; it carries their answer.
    decided: bool = False
    #: The other spellings of the same normalised name, when there are any.
    variants: tuple[str, ...] = ()
    #: The byline strings this name was read out of. Usually one, and exactly
    #: the name itself; more when the name shares a byline with a co-author.
    sources: tuple[str, ...] = ()
    #: Every spelling of this name, when there is more than one: each with its
    #: own article count, hosts and how it differs from this row's spelling. The
    #: CLUSTER is the review unit -- one question about one person -- and this is
    #: what a reviewer compares to decide which spelling is right.
    group: tuple[dict, ...] = ()

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
        if _looks_like_a_title(part) and index > 0:
            # A TITLE AFTER A NAME IS A PART OF ITS OWN and is dropped:
            # "Patrick Fudally, Officer", "Amanda Barnes, Komu 8 Wellness
            # Coach".
            continue
        # A PHRASE INSIDE A NAME comes out wherever it sits: "Henry Brannan
        # Murrow Fellow Sarah Wolf" is two people and a title. Single words do
        # not -- "Marcus Officer" is a person, and cutting the word leaves
        # "Marcus", who is not him.
        part = _strip_titles(part)
        if not part:
            continue
        names.append(part)
    return names


def _strip_titles(part: str) -> str:
    """The part with its MULTI-WORD titles removed, spaces collapsed.

    Phrases only: "Henry Brannan Murrow Fellow Sarah Wolf" gives up its title
    and keeps both people. A single word does not come out of a name, because
    "Marcus Officer" is a person and "Marcus" is not him.
    """
    previous = None
    text = f" {part} "
    while previous != text:
        previous = text
        text = _MULTIWORD_TITLE_RE.sub(" ", text)
    return " ".join(text.split()).strip(" ,;/|-")


def _looks_like_a_title(part: str) -> bool:
    """Whether a part is a job title rather than a person.

    Two tests, and a word from the list alone satisfies neither:

      every word is a title      "Officer", "Staff Writer", "News Team"
      a title and a number       "Komu 8 Wellness Coach"

    So "Marcus Officer" and "Dana President" are people, which they are: the
    first files for fox4kc, and the old rule turned him into "Marcus".
    """
    stripped = (part or "").strip()
    if not stripped:
        return False
    if not _TITLE_RE.search(f" {stripped} "):
        return False
    words = [w for w in re.split(r"[^A-Za-z0-9]+", stripped.lower()) if w]
    if words and all(word in _TITLE_TOKENS or word.isdigit() for word in words):
        return True
    return bool(_DIGIT_RE.search(stripped))


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


#: What separates two spellings of one name, most mechanical first. A reviewer
#: reading "Nick McNeal" beside "Nick Mcneal" cannot see the difference without
#: being told which it is -- 66 of Mizzou's 645 variant rows differ by case
#: alone, and 357 of its list-literal rows differ from a plain string only by
#: the brackets around it.
DIFF_BRACKETS = "brackets only"
DIFF_CASE = "case only"
DIFF_ACCENTS = "accents only"
DIFF_PUNCTUATION = "punctuation or spacing only"
DIFF_SPELLING = "spelling"
DIFF_NONE = "identical"


def difference_kind(left: str, right: str) -> str:
    """How two byline strings differ, in words."""
    left = (left or "").strip()
    right = (right or "").strip()
    if left == right:
        return DIFF_NONE
    unwrapped_left = unwrap_list_literal(left)
    unwrapped_right = unwrap_list_literal(right)
    if (unwrapped_left is None) != (unwrapped_right is None):
        inner = ", ".join(unwrapped_left or unwrapped_right or [])
        if inner.strip() == (right if unwrapped_left is not None else left).strip():
            return DIFF_BRACKETS
    if left.casefold() == right.casefold():
        return DIFF_CASE
    strip = lambda text: "".join(  # noqa: E731 - one expression, read in place
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    if strip(left).casefold() == strip(right).casefold():
        return DIFF_ACCENTS
    if normalised_name(left) == normalised_name(right):
        return DIFF_PUNCTUATION
    return DIFF_SPELLING


#: Words that say what KIND of company an owner is, not which one. Removed
#: before two owner strings are compared: "Lancaster Management Inc" and
#: "Lancaster Management Inc." are one owner, and so are "News-Press & Gazette
#: Company" and "Newspress and Gazette Company".
_OWNER_NOISE = frozenset(
    {
        "inc",
        "llc",
        "llp",
        "lle",
        "co",
        "company",
        "corp",
        "corporation",
        "group",
        "media",
        "communications",
        "publishing",
        "publishers",
        "publications",
        "newspapers",
        "newspaper",
        "holdings",
        "the",
        "of",
        "and",
        "television",
        "tv",
        "broadcasting",
        "enterprises",
    }
)


def normalised_owner(owner: str) -> str:
    """An owner string reduced to what two spellings of it share.

    Case, punctuation, "&" against "and", and the company-kind words above all
    go. What is left is the name: `gray`, `lancaster`, `newspress gazette`.

    NOT a claim that two owners are the same company -- it is a claim that two
    STRINGS are the same owner. A parent and its subsidiary have different
    names and are joined by `owner_groups`, which a person writes.
    """
    text = unicodedata.normalize("NFKD", owner or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.replace("&", " and ").lower()
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w]
    kept = [w for w in words if w not in _OWNER_NOISE]
    return " ".join(kept or words)


def owner_key(owner: str) -> str:
    """`normalised_owner` with the spaces out, which is what two spellings of
    one owner share when the difference is inside a word: "News-Press &
    Gazette" against "Newspress and Gazette", "South East Missouri State"
    against "Southeast Missouri State".
    """
    return normalised_owner(owner).replace(" ", "")


def owner_group(owner: str, groups: dict[str, str] | None = None) -> str:
    """The ultimate owner of a publication, for the cross-owner test.

    `groups` maps a normalised owner to the group it belongs to -- Missourian
    Publishing and the University of Missouri are one ownership, and Boone
    County Journals is now Missourian Publishing. Absent a mapping, an owner is
    its own group.
    """
    key = owner_key(owner)
    if groups:
        return groups.get(key, key)
    return key


def signals_for(
    row: BylineRow, owner_groups: dict[str, str] | None = None
) -> tuple[str, ...]:
    """Every defect this string shows. A string can show several.

    A list literal is not among them: it is how September 2025 wrote a list of
    co-authors, the current form is `", ".join(names)`, and turning one into
    the other takes no judgement. `repair_list_literals` does it.
    """
    raw = row.raw or ""
    found: list[str] = []
    # `_looks_like_a_title`, not the bare pattern. The pattern matches a title
    # word anywhere in the string, and the review unit is one name -- so
    # "Marcus Officer", a reporter whose surname is Officer, was offered as a
    # byline carrying a job title, in a row that also named his co-author and
    # was therefore unanswerable.
    if _looks_like_a_title(raw):
        found.append(STRAY_TITLE)
    if _PUBLICATION_RE.search(raw):
        found.append(PUBLICATION_SUFFIX)
    if _CONTACT_RE.search(raw):
        found.append(CONTACT_FRAGMENT)
    # One word is a desk, a bot or a stub: "Admin", "AbbVie", "Aber".
    if len(normalised_name(raw).split()) < 2:
        found.append(NOT_A_PERSON)
    if _DIGIT_RE.search(raw) and NOT_A_PERSON not in found:
        found.append(NOT_A_PERSON)
    # Ultimate owners, not owner strings: "Gray Media" and "Gray Television"
    # are one company, and so are Missourian Publishing and the University of
    # Missouri once somebody has said so.
    if len({owner_group(owner, owner_groups) for owner in row.owners}) > 1:
        found.append(CROSS_OWNER)
    return tuple(found)


def review_rows(
    rows: Iterable[tuple[str, str, str, int]],
    owner_groups: dict[str, str] | None = None,
    decisions: dict[str, list[str]] | None = None,
) -> list[BylineRow]:
    """Build the reviewable rows from `(byline, host, owner, articles)`.

    ONE ROW PER NAME, not per byline string. "Alyssa Mueller, Marcus Officer" is
    a co-authored story, and offering it as one row asked an unanswerable
    question: both names are correct, and a reviewer cannot accept, fix or drop
    two people at once. So the string is split and each name is asked about on
    its own -- which is also what makes the answer applicable, since the same
    name appears alone on other stories and beside a different co-author on
    others again.

    Each row carries every host and owner the NAME appears under, the strings it
    was read out of, the defects it shows, and what would be written if the
    proposal were accepted.
    """
    grouped: dict[str, dict] = defaultdict(
        lambda: {
            "articles": 0,
            "hosts": set(),
            "owners": set(),
            "sources": set(),
        }
    )
    for raw, host, owner, articles in rows:
        for name in split_names(raw) or [raw]:
            entry = grouped[name]
            # The article count is of stories carrying this NAME. A co-authored
            # story counts once for each of its names, which is what "how many
            # stories does this byline have" means.
            entry["articles"] += int(articles or 0)
            entry["sources"].add(raw)
            if host:
                entry["hosts"].add(host)
            if owner:
                entry["owners"].add(owner)

    built = [
        BylineRow(
            raw=name,
            articles=entry["articles"],
            hosts=tuple(sorted(entry["hosts"])),
            owners=tuple(sorted(entry["owners"])),
            sources=tuple(sorted(entry["sources"])),
        )
        for name, entry in grouped.items()
    ]

    # Spellings of one name. Computed across the dataset rather than per row,
    # because a variant is a relationship: the same key, or near enough to it.
    single: dict[str, BylineRow] = {}
    by_key: dict[str, list[BylineRow]] = defaultdict(list)
    for row in built:
        single[row.raw] = row
        by_key[normalised_name(row.raw)].append(row)

    variants: dict[str, set[str]] = defaultdict(set)
    for siblings in by_key.values():
        # Same key: accents, case and punctuation differ and nothing else.
        for row in siblings:
            for other in siblings:
                if other.raw != row.raw:
                    variants[row.raw].add(other.raw)
    for a_raw, b_raw in _near_pairs(single, owner_groups):
        variants[a_raw].add(b_raw)
        variants[b_raw].add(a_raw)

    for row in built:
        decided = (decisions or {}).get(row.raw)
        if decided is not None:
            # SOMEBODY HAS ANSWERED THIS ONE. It carries the names they gave
            # and no signals: a queue that keeps asking about a decided string
            # is a queue nobody finishes.
            row.signals = ()
            row.proposed = tuple(decided)
            row.decided = True
            continue
        found = list(signals_for(row, owner_groups))
        # The row IS the name, so the proposal is the name as it stands unless a
        # signal changes it. `split_names` still runs it: a name carrying a
        # trailing title or publication is trimmed by the same rules that split
        # the string, and a name it rejects outright proposes nothing.
        names = split_names(row.raw) or []
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


def _near_pairs(single: dict[str, BylineRow], groups: dict[str, str] | None = None):
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
            blocks[(owner_group(owner, groups), key[:1])].append((raw, key))
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


def group_spellings(rows: list[BylineRow]) -> list[BylineRow]:
    """Collapse the spellings of one name into ONE row to review.

    A variant is a relationship, and it was being offered as two questions:
    "Bruce E Stidham" and "Bruce E. Stidham" were separate rows, each asking
    about one spelling with the other listed beside it, and a reviewer had to
    answer the same person twice and hope the two answers agreed. "J Mcgraw" and
    "Joe Mcgraw" the same, and "Nate Sanford" and "Nate Sandford".

    So the cluster is the row. Its name is the spelling with the most stories --
    the one most likely to be right, and the default a reviewer would pick -- and
    `group` carries every spelling with its own count and hosts, because which
    spelling is correct is a judgement made by comparing those.

    The signals of every member travel with the cluster: a spelling that also
    carries a job title must not lose that question by being folded in.
    """
    by_name = {row.raw: row for row in rows}

    # Union-find over the variant relation. A relation, not a pair: "Nate
    # Sanford" near "Nate Sandford" near "Nate Sandforde" is one person in three
    # spellings, and pairing them would ask two questions about three rows.
    parent: dict[str, str] = {name: name for name in by_name}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for row in rows:
        for variant in row.variants:
            if variant in parent:
                union(row.raw, variant)

    clusters: dict[str, list[BylineRow]] = defaultdict(list)
    for row in rows:
        clusters[find(row.raw)].append(row)

    out: list[BylineRow] = []
    for members in clusters.values():
        if len(members) == 1:
            out.append(members[0])
            continue
        # Most stories first: the spelling that carries the most is the one a
        # reviewer is most likely to keep, so it leads and is the proposal.
        members.sort(key=lambda row: (-row.articles, row.raw))
        head = members[0]
        others = members[1:]
        head.group = tuple(
            {
                "name": member.raw,
                "articles": member.articles,
                "hosts": list(member.hosts),
                "differs_by": difference_kind(head.raw, member.raw),
            }
            for member in members
        )
        head.variants = tuple(member.raw for member in others)
        # Every member's defects, so folding a row in cannot lose its question.
        head.signals = tuple(
            dict.fromkeys(signal for member in members for signal in member.signals)
        )
        head.articles = sum(member.articles for member in members)
        head.hosts = tuple(sorted({host for m in members for host in m.hosts}))
        head.owners = tuple(sorted({owner for m in members for owner in m.owners}))
        out.append(head)
    return out


def candidates(
    rows: Iterable[tuple[str, str, str, int]],
    owner_groups: dict[str, str] | None = None,
    decisions: dict[str, list[str]] | None = None,
) -> list[BylineRow]:
    """The rows a person should look at, worst first.

    Ordered by which defect, then by how many articles carry it: a mechanical
    repair that clears 700 rows is worth more of a reviewer's attention than
    one that clears one.
    """
    ranked = group_spellings(
        [row for row in review_rows(rows, owner_groups, decisions) if row.needs_review]
    )
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
"""

#: Added when the caller names statuses. The literal repair does not: it fixes
#: a storage form wherever it is, and all 1,716 Mizzou rows sit outside the
#: export at `labeled`.
_APPLY_STATUS_CLAUSE = "       AND a.status = ANY(:statuses)\n"

#: Articles whose byline CONTAINS the name beside somebody else. The exact match
#: above has already taken the rows where the name is the whole field, so this
#: excludes them rather than writing them twice.
_SHARED_SQL = """
    SELECT a.id, a.author
      FROM articles a
      JOIN candidate_links cl ON cl.id = a.candidate_link_id
     WHERE cl.dataset_id = :dataset_id
       AND a.author LIKE :like
       AND a.author <> :raw_byline
"""


def dataset_rows(session, dataset_id: str, statuses=LOCAL_STATUSES):
    """`(byline, host, owner, articles)` for one dataset's local stories."""
    from sqlalchemy import text

    result = session.execute(
        text(_ROWS_SQL), {"dataset_id": dataset_id, "statuses": list(statuses)}
    )
    return [(row[0], row[1], row[2], row[3]) for row in result]


def replace_name(author: str | None, name: str, names) -> str | None:
    """`author` with `name` replaced by `names`, keeping the co-authors.

    The review unit is one name, so a decision about "Marcus Officer" has to
    reach "Alyssa Mueller, Marcus Officer" without touching Alyssa Mueller.
    Returns None when the string does not carry the name, so the caller can skip
    the row rather than write it back unchanged.

    A decision naming nobody removes the name and leaves the rest: a co-authored
    story keeps the co-author who is real.
    """
    if not author:
        return None
    parts = [part.strip() for part in _SEPARATORS.split(author) if part.strip()]
    target = normalised_name(name)
    if not any(normalised_name(part) == target for part in parts):
        return None
    out: list[str] = []
    for part in parts:
        if normalised_name(part) == target:
            out.extend(n for n in names if n and n.strip())
        else:
            out.append(part)
    # Deduplicated in order: fixing a misspelling on a co-authored story can
    # name somebody already in the string -- "Nate Sandford, Nate Sanford" --
    # and writing the name twice is a new defect.
    seen: set[str] = set()
    unique = []
    for part in out:
        key = normalised_name(part)
        if key in seen:
            continue
        seen.add(key)
        unique.append(part.strip())
    return rendered(unique)


def apply_decision(
    session, dataset_id: str, raw_byline: str, names, statuses=LOCAL_STATUSES
) -> int:
    """Write a decision's names onto every article carrying the name.

    Returns the number of rows written. The article's byline is the permanent
    record, so a decision is not finished until it is here -- the table keeps it
    so a later extraction writing the raw form again can be corrected without a
    person deciding twice.

    TWO WRITES, because the review unit is a name and the column holds a string.
    The exact match is one statement and covers the great majority. A name
    sharing its byline with a co-author cannot be: the string has to be taken
    apart, the one name replaced and the rest kept, which is per row.
    """
    from sqlalchemy import text

    sql = _APPLY_SQL
    params: dict = {
        "author": rendered(names),
        "dataset_id": dataset_id,
        "raw_byline": raw_byline,
    }
    if statuses:
        sql = sql.rstrip() + "\n" + _APPLY_STATUS_CLAUSE
        params["statuses"] = list(statuses)
    result = session.execute(text(sql), params)
    written = int(getattr(result, "rowcount", 0) or 0)

    # The co-authored ones. Selected by a LIKE on the name so the scan is narrow,
    # then checked properly in Python: a LIKE cannot tell "Marcus Officer" from
    # "Marcus Officerson", and normalised comparison can.
    shared_sql = _SHARED_SQL
    shared_params: dict = {
        "dataset_id": dataset_id,
        "like": f"%{raw_byline}%",
        "raw_byline": raw_byline,
    }
    if statuses:
        shared_sql = shared_sql.rstrip() + "\n" + _APPLY_STATUS_CLAUSE
        shared_params["statuses"] = list(statuses)
    for article_id, author in session.execute(text(shared_sql), shared_params).all():
        rewritten = replace_name(author, raw_byline, list(names))
        if rewritten is None or rewritten == author:
            continue
        session.execute(
            text("UPDATE articles SET author = :author WHERE id = :id"),
            {"author": rewritten, "id": article_id},
        )
        written += 1
    return written


#: One row per article, so a co-authored story can become one record per
#: person. `dataset_rows` groups; this does not.
_ARTICLE_ROWS_SQL = """
    SELECT a.id AS article_id, a.author AS byline, s.host_norm AS host,
           coalesce(nullif(trim(s.owner), ''), '(unknown)') AS owner,
           a.publish_date, a.title
      FROM articles a
      JOIN candidate_links cl ON cl.id = a.candidate_link_id
      JOIN sources s ON s.id = cl.source_id
     WHERE cl.dataset_id = :dataset_id
       AND a.status = ANY(:statuses)
       AND coalesce(trim(a.author), '') <> ''
"""


def article_rows(session, dataset_id: str, statuses=LOCAL_STATUSES):
    """One row per local article: id, byline, host, owner, date, title."""
    from sqlalchemy import text

    result = session.execute(
        text(_ARTICLE_ROWS_SQL),
        {"dataset_id": dataset_id, "statuses": list(statuses)},
    )
    return [tuple(row) for row in result]


def author_records(
    article_rows_, decisions: dict[str, list[str]] | None = None
) -> list[dict]:
    """ONE RECORD PER PERSON PER ARTICLE.

    A co-authored byline is a list of people, and each of them wrote that
    article on that host: "Loryn Kykendall, Julia Eastham, Kate Smith" is three
    records, not one string. This is the table a per-author count, a per-host
    count and any later author identity is built from -- every other report
    here is an aggregate of it.

    The raw string is kept on every record, so a record can always be traced
    back to what the page carried.
    """
    out = []
    names_for: dict[str, tuple[str, ...]] = {}
    for article_id, raw, host, owner, publish_date, title in article_rows_:
        if raw not in names_for:
            decided = (decisions or {}).get(raw)
            names_for[raw] = (
                tuple(decided) if decided is not None else tuple(split_names(raw))
            )
        names = names_for[raw]
        for position, name in enumerate(names, start=1):
            out.append(
                {
                    "article_id": article_id,
                    "byline": name,
                    # Where the name sat in the byline: first is the lead.
                    "position": position,
                    "of_authors": len(names),
                    "host": host,
                    "owner": owner,
                    "publish_date": publish_date,
                    "title": title,
                    "raw_byline": raw,
                }
            )
    return out


def load_decisions(session, dataset_id: str) -> dict[str, list[str]]:
    """`{raw_byline: canonical_names}` for one dataset's decided strings.

    A decided string is not asked about again and is counted as the people it
    names, whatever the article still says: the decision is the answer, and
    applying it to `articles.author` is how the record catches up.
    """
    from sqlalchemy import text

    try:
        rows = session.execute(
            text(
                "SELECT raw_byline, canonical_names FROM byline_normalizations"
                " WHERE dataset_id = :dataset_id"
            ),
            {"dataset_id": dataset_id},
        ).fetchall()
    except Exception:  # pragma: no cover - table absent on an old database
        return {}
    decided: dict[str, list[str]] = {}
    for raw, names in rows:
        if isinstance(names, str):
            try:
                names = json.loads(names)
            except ValueError:
                continue
        decided[raw] = [str(name) for name in (names or [])]
    return decided


def load_owner_groups(session) -> dict[str, str]:
    """`{owner_key: group_key}` from `owner_groups`, or {} when there are none.

    Soft on purpose: a review that cannot read the table asks about a few more
    cross-owner rows, which is a worse report and not a broken one.
    """
    from sqlalchemy import text

    try:
        rows = session.execute(
            text("SELECT owner_key, group_key FROM owner_groups")
        ).fetchall()
    except Exception:  # pragma: no cover - table absent on an old database
        return {}
    return {row[0]: row[1] for row in rows}


def repair_list_literals(
    session, dataset_id: str, statuses=None, dry_run: bool = False
) -> dict:
    """Rewrite `["A", "B"]` bylines to the current form.

    A schema artefact, not a decision: extraction writes co-authors as
    `", ".join(names)` and a September 2025 path wrote `str(list)` instead.
    1,716 Mizzou articles carry it. `[]` names nobody and becomes an empty
    byline rather than the two characters.

    EVERY STATUS by default, unlike the reports. The reports read what reached
    the export; this repairs a storage form, and all 1,716 of those rows are at
    `labeled` -- outside the export and still wrong.
    """
    from sqlalchemy import text

    status_clause = " AND a.status = ANY(:statuses)" if statuses else ""
    params: dict = {"dataset_id": dataset_id}
    if statuses:
        params["statuses"] = list(statuses)
    found = session.execute(
        text(
            "SELECT a.author, count(*) FROM articles a"
            " JOIN candidate_links cl ON cl.id = a.candidate_link_id"
            " WHERE cl.dataset_id = :dataset_id"
            f"{status_clause}"
            " AND a.author LIKE '[%]' GROUP BY 1 ORDER BY 2 DESC"
        ),
        params,
    ).fetchall()

    strings = 0
    articles = 0
    examples: list[tuple[str, str, int]] = []
    for raw, count in found:
        if unwrap_list_literal(raw) is None:
            continue  # "[Not a list" is a name, oddly punctuated
        after = rendered(split_names(raw))
        strings += 1
        articles += int(count)
        if len(examples) < 5:
            examples.append((raw, after, int(count)))
        if not dry_run:
            apply_decision(session, dataset_id, raw, split_names(raw), statuses)

    return {"strings": strings, "articles": articles, "examples": examples}


def refresh_candidates(
    session, dataset_id: str, statuses=LOCAL_STATUSES, dry_run: bool = False
) -> dict:
    """Recompute one dataset's queue into `byline_review_candidates`.

    Wholesale: the table says what needs review NOW, so a string somebody has
    decided, or a literal that has been repaired, stops being written rather
    than lingering as a row nobody can act on.

    Runs as a batch -- 7,921 strings scored in under a second here, and never
    inside a web request.
    """
    from sqlalchemy import text

    rows = dataset_rows(session, dataset_id, statuses)
    groups = load_owner_groups(session)
    decided = load_decisions(session, dataset_id)
    found = candidates(rows, groups, decided)

    if dry_run:
        return {"candidates": len(found), "written": 0}

    session.execute(
        text("DELETE FROM byline_review_candidates WHERE dataset_id = :dataset_id"),
        {"dataset_id": dataset_id},
    )
    for row in found:
        session.execute(
            text(
                "INSERT INTO byline_review_candidates (id, dataset_id, raw_byline,"
                " signal, signal_label, signals, proposed, variants, differs_by,"
                ' articles, hosts, owners, sources, "group", computed_at)'
                " VALUES (gen_random_uuid()::text, :dataset_id, :raw, :signal,"
                " :label, :signals, :proposed, :variants, :differs_by, :articles,"
                " :hosts, :owners, :sources, :group, CURRENT_TIMESTAMP)"
            ),
            {
                "dataset_id": dataset_id,
                "raw": row.raw,
                "signal": row.top_signal or "",
                "label": SIGNAL_LABELS.get(row.top_signal or "", ""),
                "signals": json.dumps(list(row.signals)),
                "proposed": json.dumps(list(row.proposed)),
                "variants": json.dumps(list(row.variants)),
                "differs_by": json.dumps(
                    [difference_kind(row.raw, variant) for variant in row.variants]
                ),
                "articles": row.articles,
                "hosts": json.dumps(list(row.hosts)),
                "owners": json.dumps(list(row.owners)),
                # The byline strings this name was read out of. One row is one
                # name; this is how the reviewer sees that the name shares a
                # byline with a co-author, which changes what an answer means.
                "sources": json.dumps(list(row.sources)),
                # Every spelling of this name with its own count and hosts. The
                # cluster is one review, so this is what the reviewer compares
                # rather than answering the same person once per spelling.
                "group": json.dumps(list(row.group)),
            },
        )
    return {"candidates": len(found), "written": len(found)}


def owner_grouping(rows, groups: dict[str, str] | None = None) -> list[dict]:
    """Every owner string in a dataset and the ultimate owner it lands under.

    The review surface for ownership: a row whose `group_name` is its own name
    is ungrouped, and two rows sharing a `group_key` are treated as one company
    by the cross-owner test. Spelling variants arrive already merged -- what is
    left for a person is the parents.
    """
    seen: dict[str, dict] = {}
    for _raw, host, owner, articles in rows:
        if not owner:
            continue
        key = owner_key(owner)
        entry = seen.setdefault(
            key,
            {
                "owner_key": key,
                "owner_forms": set(),
                "hosts": set(),
                "articles": 0,
                "group_key": owner_group(owner, groups),
            },
        )
        entry["owner_forms"].add(owner)
        entry["articles"] += int(articles or 0)
        if host:
            entry["hosts"].add(host)
    out = [
        {
            "owner": sorted(entry["owner_forms"])[0],
            "owner_forms": " | ".join(sorted(entry["owner_forms"])),
            "spellings": len(entry["owner_forms"]),
            "hosts": len(entry["hosts"]),
            "host_list": " | ".join(sorted(entry["hosts"])),
            "articles": entry["articles"],
            "owner_key": entry["owner_key"],
            "group_key": entry["group_key"],
            "grouped": entry["group_key"] != entry["owner_key"],
        }
        for entry in seen.values()
    ]
    out.sort(key=lambda e: (-e["articles"], e["owner"]))
    return out


def bylines_with_hosts(
    rows, decisions: dict[str, list[str]] | None = None
) -> list[dict]:
    """REPORT ONE: every unique local byline and the hosts it appears on.

    The unit is the PERSON, not the string: a byline naming three reporters
    counts for each of them, and two spellings a reviewer has resolved count
    once. `hosts` is why a reviewer looks twice -- a person on hosts with
    different owners is either filing for both or is not a local byline at all.
    """
    people: dict[str, dict] = {}
    for row in review_rows(rows, decisions=decisions):
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
            # The STRINGS the name was read out of, not the row's own name --
            # a row is one name now, so `row.raw` would count 1 for everybody
            # and the report would stop showing that "Conor Wilson" reaches the
            # corpus both alone and beside Moe Clark.
            entry["raw_forms"].update(row.sources or (row.raw,))
    out = []
    for entry in people.values():
        out.append(
            {
                "byline": entry["byline"],
                "articles": entry["articles"],
                "hosts": len(entry["hosts"]),
                "host_list": " | ".join(sorted(entry["hosts"])),
                "owners": len(entry["owners"]),
                "owner_list": " | ".join(sorted(entry["owners"])),
                "raw_forms": len(entry["raw_forms"]),
            }
        )
    out.sort(key=lambda e: (-e["articles"], e["byline"]))
    return out


def hosts_with_bylines(
    rows, decisions: dict[str, list[str]] | None = None
) -> list[dict]:
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
            decided = (decisions or {}).get(raw)
            names_for[raw] = (
                tuple(decided) if decided is not None else tuple(split_names(raw))
            )
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
            "owner": " | ".join(sorted(entry["owners"])),
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


def apply_pending(session, dataset_id: str, dry_run: bool = False) -> dict:
    """Write every undecided-but-unapplied decision onto the dataset's articles.

    A decision is not finished when it is recorded. `articles.author` is the
    permanent record, and until the names reach it the correction exists only in
    a table nothing downstream reads -- the BigQuery export, the byline reports
    and anybody querying the corpus all still see the parser's string.

    `applied_at IS NULL` is the whole selector, so this is safe to run every
    night: a decision applied last night is not written again, and a decision
    re-made in the console (which clears `applied_at`) is picked up the next
    night without anybody asking for it.

    Returns `{"decisions": n, "articles": n}`. Commits nothing -- the caller
    owns the transaction, because the workflow step applies every dataset and a
    commit per dataset is what keeps one dataset's failure from discarding the
    ones before it.
    """
    from sqlalchemy import text

    pending = session.execute(
        text(
            "SELECT id, raw_byline, canonical_names FROM byline_normalizations"
            " WHERE dataset_id = :dataset_id AND applied_at IS NULL"
        ),
        {"dataset_id": dataset_id},
    ).fetchall()

    written = 0
    for row in pending:
        names = row[2]
        if isinstance(names, str):
            names = json.loads(names)
        if dry_run:
            logger.info("would write %r over %r", rendered(names), row[1])
            continue
        count = apply_decision(session, dataset_id, row[1], names)
        # Stamped even when it wrote nothing. Zero articles is the normal
        # outcome for a string whose articles a previous run already fixed, and
        # leaving `applied_at` null would re-run it every night forever.
        session.execute(
            text(
                "UPDATE byline_normalizations SET applied_at = CURRENT_TIMESTAMP,"
                " articles_updated = :n WHERE id = :id"
            ),
            {"n": count, "id": row[0]},
        )
        written += count
    return {"decisions": len(pending), "articles": written}
