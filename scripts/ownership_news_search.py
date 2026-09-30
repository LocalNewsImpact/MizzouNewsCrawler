"""Find news of sales, purchases, closures and mergers of Missouri outlets.

One web search per term -- each publication and each owner in the outlet
registry -- through OpenRouter's web search, with a model reading the results
and keeping only articles about that paper or owner changing hands, merging
or closing. Each kept article is fetched to check that the paragraph it was
given is really on the page. The result is a CSV to review; rows kept go into
datadesk's stories table with `manage.py import_outlet_stories`.

    OPENROUTER_API_KEY=... python scripts/ownership_news_search.py \\
        --out ~/Downloads/ownership_stories.csv --limit 10

Terms come from src/lookups/mo_outlet_registry.csv. Outlets the registry says
are not newsrooms (legal, business, shopper, magazine, not local news) are
left out; so is any URL already in --skip-urls.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "src" / "lookups" / "mo_outlet_registry.csv"

OPENROUTER = "https://openrouter.ai/api/v1/chat/completions"
#: Cheap, and searched by Exa through OpenRouter at $0.007 a request.
MODEL = "deepseek/deepseek-v3.2"

#: Registry statuses that are not newsrooms, so nobody reports their sale.
NOT_NEWSROOMS = {"legal", "business", "shopper", "magazine", "not_local_news"}

#: Owner values that name nobody.
NO_OWNER = {"", "unknown", "independent", "n/a", "none"}

#: Reference and social sites: a Wikipedia summary or a LinkedIn company page
#: is not a news report, and the pilot returned both (2026-09-29).
NOT_NEWS_SITES = (
    "wikipedia.org",
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "crunchbase.com",
    "youtube.com",
    "muckrack.com",
    "zoominfo.com",
    # National reprints and aggregators: a local story copied onto them is
    # still a local story, found at its source (aol.com in the pilot).
    "aol.com",
    "yahoo.com",
    "msn.com",
    "newsbreak.com",
    "ground.news",
    "flipboard.com",
)

EVENTS = ("sale", "purchase", "closure", "merger", "ownership change", "launch")

COLUMNS = (
    "date",
    "headline",
    "url",
    "excerpt",
    "event",
    "publications",
    "owners",
    "term",
    "term_kind",
    "missouri_source",
    "verified",
    "keep",
)

#: Missouri news and press sources the registry does not hold as outlets.
MISSOURI_PRESS = (
    "mopress.com",
    "missouriindependent.com",
    "missourinet.com",
    "missouripressfoundation.org",
    "stlpr.org",
    "kcur.org",
    "kbia.org",
    "ksmu.org",
)

PROMPT = """You are helping a researcher track the ownership and survival of \
Missouri local news outlets.

Search the web for: {query}

From the search results, list every news article that reports {term} \
(a Missouri {kind}) being sold, bought, acquired, merged, closed, ceasing \
publication, ending print, or changing owner. Ignore articles that only \
mention {term} in passing, obituaries, and anything not about that event.

Prefer reports from Missouri local news outlets and Missouri publications --
the paper itself, its neighbours, regional TV and radio newsrooms, the
Missouri Press Association, the Springfield Business Journal, the Missouri
Independent. Use a national or out-of-state source only when no Missouri
source reports the event. Never use Wikipedia, LinkedIn, social media,
company directories or press-release aggregators.

For each article return:
- "date": its publication date as YYYY-MM-DD ("" if the result does not show it)
- "headline": its headline, exactly
- "url": its URL, exactly as in the results
- "excerpt": the one or two sentences that report the event, copied word for \
word from the result text -- never reworded, never summarised
- "event": one of {events}
- "publications": the outlets it names, separated by "; "
- "owners": the owners, buyers and sellers it names, separated by "; "

Answer with JSON only: {{"articles": [...]}}. If nothing qualifies, \
{{"articles": []}}."""


@dataclass
class Term:
    text: str
    kind: str  # "publication" or "owner"


@dataclass
class Found:
    date: str
    headline: str
    url: str
    excerpt: str
    event: str
    publications: str
    owners: str
    term: str
    term_kind: str
    missouri_source: str = ""
    verified: str = ""
    keep: str = ""

    def row(self) -> dict:
        return {c: getattr(self, c) for c in COLUMNS}


@dataclass
class Spend:
    ceiling: float
    total: float = 0.0
    calls: int = 0
    by_term: dict = field(default_factory=dict)

    def add(self, term: str, cost: float) -> None:
        self.total += cost
        self.calls += 1
        self.by_term[term] = self.by_term.get(term, 0.0) + cost

    @property
    def spent(self) -> bool:
        return self.total >= self.ceiling


def terms_from(registry: Path = REGISTRY) -> list[Term]:
    """Each newsroom publication once, then each owner once.

    A publication's other names (`aka`) are searched too: a sale is reported
    under the name the paper had then.
    """
    rows = list(csv.DictReader(open(registry, encoding="utf-8")))
    seen, out = set(), []

    def add(text: str, kind: str) -> None:
        text = re.sub(r"\s+", " ", (text or "").strip())
        key = (text.lower(), kind)
        if len(text) < 4 or key in seen:
            return
        seen.add(key)
        out.append(Term(text, kind))

    for r in rows:
        if (r.get("status") or "").strip() in NOT_NEWSROOMS:
            continue
        add(r.get("outlet"), "publication")
        for other in re.split(r"[;|]", r.get("aka") or ""):
            add(other, "publication")
    for r in rows:
        if (r.get("status") or "").strip() in NOT_NEWSROOMS:
            continue
        owner = (r.get("owner") or "").strip()
        if owner.lower() not in NO_OWNER:
            add(owner, "owner")
    return out


def query_for(term: Term) -> str:
    words = "sold OR purchased OR acquired OR closed OR merged OR \"new owner\""
    thing = "newspaper" if term.kind == "publication" else "newspapers"
    return f'"{term.text}" Missouri {thing} {words}'


def parse_articles(content: str) -> list[dict]:
    """The model's JSON, forgiving a code fence or a sentence around it."""
    text = (content or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return []
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    articles = data.get("articles") if isinstance(data, dict) else None
    return [a for a in articles or [] if isinstance(a, dict) and a.get("url")]


def search(term: Term, key: str, model: str = MODEL, timeout: int = 120):
    """(articles, cost in dollars) for one term."""
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": PROMPT.format(
                    query=query_for(term),
                    term=term.text,
                    kind=term.kind,
                    events=", ".join(EVENTS),
                ),
            }
        ],
        "plugins": [{"id": "web", "engine": "exa", "max_results": 10}],
        "usage": {"include": True},
        "temperature": 0,
    }
    resp = requests.post(
        OPENROUTER,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"].get("content") or ""
    cost = float((data.get("usage") or {}).get("cost") or 0.0)
    return parse_articles(content), cost


def _plain(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def excerpt_on_page(excerpt: str, page: str) -> bool:
    """Whether the excerpt's words are on the page, in order.

    Checked on its longest sentence rather than the whole: a model joining
    two sentences with an ellipsis has still quoted, not invented.
    """
    pieces = [p for p in re.split(r"(?<=[.!?])\s+|\s*(?:\.\.\.|…)\s*", excerpt) if p]
    if not pieces:
        return False
    longest = _plain(max(pieces, key=len))
    return len(longest) >= 20 and longest in _plain(page)


def verify(found: Found, timeout: int = 30) -> str:
    """"yes", "no", or why the page could not be read."""
    try:
        resp = requests.get(
            found.url,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
                )
            },
        )
    except requests.RequestException as exc:
        return f"unfetched: {type(exc).__name__}"
    if resp.status_code != 200:
        return f"blocked: {resp.status_code}"
    return "yes" if excerpt_on_page(found.excerpt, resp.text) else "no"


def known_urls(path: str | None) -> set[str]:
    if not path:
        return set()
    urls = set()
    for line in open(os.path.expanduser(path), encoding="utf-8"):
        line = line.strip()
        if line.startswith("http"):
            urls.add(normal_url(line))
    return urls


def missouri_hosts(registry: Path = REGISTRY) -> set[str]:
    """Websites of Missouri outlets in the registry, and Missouri press."""
    hosts = set(MISSOURI_PRESS)
    for r in csv.DictReader(open(registry, encoding="utf-8")):
        host = normal_url(r.get("host") or "").split("/")[0]
        if host and (r.get("state") or "MO") == "MO":
            hosts.add(host)
    return hosts


def from_missouri(url: str, hosts: set[str]) -> bool:
    host = normal_url(url).split("/")[0]
    return any(host == h or host.endswith("." + h) for h in hosts)


def not_news(url: str) -> bool:
    host = normal_url(url).split("/")[0]
    return any(host == d or host.endswith("." + d) for d in NOT_NEWS_SITES)


def normal_url(url: str) -> str:
    url = re.sub(r"^https?://(www\.)?", "", (url or "").strip().lower())
    return url.split("#")[0].rstrip("/")


def done_terms(out: str) -> set[str]:
    """Terms a previous run of this CSV finished, from its `.done` file."""
    path = out + ".done"
    if not os.path.exists(path):
        return set()
    return {line.rstrip("\n") for line in open(path, encoding="utf-8") if line.strip()}


def urls_in(out: str) -> set[str]:
    if not os.path.exists(out):
        return set()
    return {normal_url(r["url"]) for r in csv.DictReader(open(out, encoding="utf-8"))}


def run(
    terms,
    key,
    out,
    skip,
    spend,
    model=MODEL,
    pause=1.0,
    log=print,
    missouri=(),
    workers=1,
):
    """Search each term, writing every article to `out` as it is found.

    Nothing is held back until the end: each row is written and flushed the
    moment it is checked, and each finished term is recorded in `out.done`.
    A run stopped anywhere -- the spend ceiling, a network failure, ^C --
    loses nothing, and the next run with the same --out appends, skipping
    the terms and URLs already there.

    `workers` terms are searched at once. A term is a web search and then a
    page fetch per article, several of which wait out a timeout, so one at a
    time took minutes a term; the file writes stay one at a time.
    """
    seen = set(skip) | urls_in(out)
    finished = done_terms(out)
    missouri = set(missouri)
    rows = []
    lock = threading.Lock()
    fresh = not os.path.exists(out)
    todo = [
        (i, t)
        for i, t in enumerate(terms, start=1)
        if f"{t.kind}\t{t.text}" not in finished
    ]
    with open(out, "a", newline="", encoding="utf-8") as fh, open(
        out + ".done", "a", encoding="utf-8"
    ) as done:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        if fresh:
            writer.writeheader()
            fh.flush()

        def one(i, term):
            with lock:
                if spend.spent:
                    return
            try:
                articles, cost = search(term, key, model)
            except requests.RequestException as exc:
                log(f"[{i}/{len(terms)}] {term.text}: search failed ({exc})")
                return
            with lock:
                spend.add(term.text, cost)
            kept = 0
            for a in articles:
                url = (a.get("url") or "").strip()
                with lock:
                    if normal_url(url) in seen or not_news(url):
                        continue
                    seen.add(normal_url(url))
                found = Found(
                    date=(a.get("date") or "").strip()[:10],
                    headline=re.sub(r"\s+", " ", a.get("headline") or "").strip(),
                    url=url,
                    excerpt=re.sub(r"\s+", " ", a.get("excerpt") or "").strip(),
                    event=(a.get("event") or "").strip(),
                    publications=(a.get("publications") or "").strip(),
                    owners=(a.get("owners") or "").strip(),
                    term=term.text,
                    term_kind=term.kind,
                    missouri_source="yes" if from_missouri(url, missouri) else "",
                )
                found.verified = verify(found)
                with lock:
                    writer.writerow(found.row())
                    fh.flush()
                    rows.append(found)
                kept += 1
            with lock:
                done.write(f"{term.kind}\t{term.text}\n")
                done.flush()
                log(
                    f"[{i}/{len(terms)}] {term.kind}: {term.text}: {kept} new "
                    f"(${cost:.4f}, total ${spend.total:.2f})"
                )
            time.sleep(pause)

        if workers <= 1:
            for i, term in todo:
                if spend.spent:
                    break
                one(i, term)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for future in [pool.submit(one, i, t) for i, t in todo]:
                    future.result()
        if spend.spent:
            log(f"spend ceiling ${spend.ceiling:.2f} reached after {spend.calls} terms")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--registry", default=str(REGISTRY))
    ap.add_argument("--skip-urls", help="file of URLs already in the stories table")
    ap.add_argument("--limit", type=int, help="first N terms only")
    ap.add_argument("--start", type=int, default=0, help="skip the first N terms")
    ap.add_argument("--only", action="append", help="just this term (repeatable)")
    ap.add_argument("--kind", choices=("publication", "owner"))
    ap.add_argument("--max-usd", type=float, default=20.0)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--workers", type=int, default=6, help="terms searched at once")
    args = ap.parse_args(argv)

    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY is not set", file=sys.stderr)
        return 2
    terms = terms_from(Path(args.registry))
    if args.kind:
        terms = [t for t in terms if t.kind == args.kind]
    if args.only:
        wanted = {o.lower() for o in args.only}
        terms = [t for t in terms if t.text.lower() in wanted] or [
            Term(o, args.kind or "publication") for o in args.only
        ]
    terms = terms[args.start :]
    if args.limit:
        terms = terms[: args.limit]
    spend = Spend(args.max_usd)
    out = os.path.expanduser(args.out)
    rows = run(
        terms,
        key,
        out,
        known_urls(args.skip_urls),
        spend,
        model=args.model,
        missouri=missouri_hosts(Path(args.registry)),
        workers=args.workers,
    )
    verified = sum(1 for r in rows if r.verified == "yes")
    print(
        f"{len(rows)} articles from {spend.calls} terms, {verified} verified on the "
        f"page; ${spend.total:.2f} spent -> {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
