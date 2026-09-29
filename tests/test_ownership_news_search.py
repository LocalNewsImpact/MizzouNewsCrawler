"""The ownership story finder: what it searches, what it keeps, and that a
stopped run loses nothing (scripts/ownership_news_search.py)."""

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ownership_news_search.py"


@pytest.fixture(scope="module")
def finder():
    spec = importlib.util.spec_from_file_location("ownership_news_search", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _registry(tmp_path, rows):
    path = tmp_path / "registry.csv"
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["outlet", "owner", "status", "aka"])
        w.writeheader()
        w.writerows(rows)
    return path


def test_newsrooms_and_their_owners_are_the_terms(finder, tmp_path):
    path = _registry(
        tmp_path,
        [
            {
                "outlet": "The Monett Times",
                "owner": "Squibb Media",
                "status": "merged",
                "aka": "",
            },
            {
                "outlet": "Monroe | Ralls",
                "owner": "Reaves & Williams",
                "status": "active",
                "aka": "Ralls County Herald-Enterprise; Monroe County Appeal",
            },
            {
                "outlet": "St. Louis Daily Record",
                "owner": "Dolan",
                "status": "legal",
                "aka": "",
            },
            {
                "outlet": "Another Paper",
                "owner": "Squibb Media",
                "status": "active",
                "aka": "",
            },
            {"outlet": "Solo", "owner": "Independent", "status": "active", "aka": ""},
        ],
    )
    terms = [(t.text, t.kind) for t in finder.terms_from(path)]
    assert ("The Monett Times", "publication") in terms
    assert ("Monroe County Appeal", "publication") in terms
    assert ("St. Louis Daily Record", "publication") not in terms
    assert ("Dolan", "owner") not in terms
    assert terms.count(("Squibb Media", "owner")) == 1
    assert ("Independent", "owner") not in terms


def test_the_query_names_the_term_and_missouri(finder):
    q = finder.query_for(finder.Term("The Monett Times", "publication"))
    assert q.startswith('"The Monett Times" Missouri newspaper')
    assert "sold" in q and "closed" in q


@pytest.mark.parametrize(
    "content",
    [
        '{"articles": [{"url": "https://a.example/x", "headline": "H"}]}',
        'Here you go:\n```json\n{"articles": [{"url": "https://a.example/x"}]}\n```',
        'Sure. {"articles": [{"url": "https://a.example/x"}]} Done.',
    ],
)
def test_the_answer_is_read_however_it_is_wrapped(finder, content):
    assert [a["url"] for a in finder.parse_articles(content)] == ["https://a.example/x"]


@pytest.mark.parametrize(
    "content", ["", "no json here", '{"articles": [{"headline": "no url"}]}', "{bad"]
)
def test_an_answer_without_articles_is_empty(finder, content):
    assert finder.parse_articles(content) == []


def test_a_quoted_excerpt_is_found_on_the_page(finder):
    page = "<p>Squibb Media has purchased The Monett Times newspaper, effective July 1, 2024.</p>"
    assert finder.excerpt_on_page(
        "Squibb Media has purchased The Monett Times newspaper, effective July 1, 2024.",
        page,
    )
    assert finder.excerpt_on_page(
        "Squibb Media has purchased The Monett Times newspaper, effective July 1, 2024. … More.",
        page,
    )
    assert not finder.excerpt_on_page(
        "CherryRoad Media bought the Monett Times in 2022.", page
    )


def test_curly_quotes_are_the_same_quotes(finder):
    page = "“We bought the name,” Cooper said, “and the intangible assets.”"
    assert finder.excerpt_on_page(
        '"We bought the name," Cooper said, "and the intangible assets."', page
    )


def test_reference_and_social_sites_are_not_news(finder):
    assert finder.not_news("https://en.wikipedia.org/wiki/Monett_Times")
    assert finder.not_news("https://linkedin.com/company/monett-times")
    assert finder.not_news("https://www.aol.com/articles/branson-papers-closure")
    assert finder.not_news("https://news.yahoo.com/x")
    assert not finder.not_news("https://www.ky3.com/2026/08/05/story")


def _answer(
    url, excerpt="Squibb Media has purchased The Monett Times newspaper today."
):
    return [
        {
            "url": url,
            "headline": "H",
            "date": "2024-06-26",
            "excerpt": excerpt,
            "event": "purchase",
            "publications": "Monett Times",
            "owners": "Squibb Media",
        }
    ]


def test_each_article_is_written_as_it_is_found_and_a_rerun_resumes(
    finder, tmp_path, monkeypatch
):
    """Nothing waits for the end of the run: a second run with the same
    output appends, and skips the terms and URLs the first one wrote."""
    calls = []

    def search(term, key, model=None):
        calls.append(term.text)
        return _answer(f"https://news.example/{term.text}"), 0.01

    monkeypatch.setattr(finder, "search", search)
    monkeypatch.setattr(finder, "verify", lambda found: "yes")
    out = str(tmp_path / "found.csv")
    terms = [
        finder.Term("A Paper", "publication"),
        finder.Term("B Paper", "publication"),
    ]

    finder.run(
        terms[:1], "k", out, set(), finder.Spend(10), pause=0, log=lambda *_: None
    )
    assert [r["url"] for r in csv.DictReader(open(out))] == [
        "https://news.example/A Paper"
    ]

    finder.run(terms, "k", out, set(), finder.Spend(10), pause=0, log=lambda *_: None)
    assert calls == ["A Paper", "B Paper"]
    assert [r["url"] for r in csv.DictReader(open(out))] == [
        "https://news.example/A Paper",
        "https://news.example/B Paper",
    ]


def test_known_urls_and_non_news_sites_are_skipped(finder, tmp_path, monkeypatch):
    monkeypatch.setattr(
        finder,
        "search",
        lambda term, key, model=None: (
            _answer("https://www.known.example/story/")
            + _answer("https://en.wikipedia.org/wiki/X")
            + _answer("https://new.example/story"),
            0.01,
        ),
    )
    monkeypatch.setattr(finder, "verify", lambda found: "yes")
    out = str(tmp_path / "found.csv")
    skip = {finder.normal_url("https://known.example/story")}
    finder.run(
        [finder.Term("A", "publication")],
        "k",
        out,
        skip,
        finder.Spend(10),
        pause=0,
        log=lambda *_: None,
    )
    assert [r["url"] for r in csv.DictReader(open(out))] == [
        "https://new.example/story"
    ]


def test_the_run_stops_at_the_spend_ceiling(finder, tmp_path, monkeypatch):
    monkeypatch.setattr(finder, "search", lambda term, key, model=None: ([], 0.6))
    out = str(tmp_path / "found.csv")
    spend = finder.Spend(1.0)
    terms = [finder.Term(t, "publication") for t in ("A", "B", "C")]
    finder.run(terms, "k", out, set(), spend, pause=0, log=lambda *_: None)
    assert spend.calls == 2


def test_a_page_that_refuses_is_recorded_as_blocked(finder, monkeypatch):
    class Refused:
        status_code = 403
        text = ""

    monkeypatch.setattr(finder.requests, "get", lambda *a, **k: Refused())
    found = finder.Found(
        "", "H", "https://x.example", "text", "sale", "", "", "t", "publication"
    )
    assert finder.verify(found) == "blocked: 403"


def test_missouri_outlets_and_press_are_marked(finder, tmp_path):
    path = tmp_path / "registry.csv"
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["outlet", "host", "state"])
        w.writeheader()
        w.writerow({"outlet": "KY3", "host": "ky3.com", "state": "MO"})
        w.writerow({"outlet": "KCMO", "host": "949kcmo.com", "state": "KS"})
    hosts = finder.missouri_hosts(path)
    assert finder.from_missouri("https://www.ky3.com/2026/08/05/story", hosts)
    assert finder.from_missouri("https://mopress.com/stories/x", hosts)
    assert not finder.from_missouri("https://949kcmo.com/x", hosts)
    assert not finder.from_missouri("https://www.aol.com/articles/x", hosts)


def test_the_model_is_told_to_prefer_missouri_sources(finder):
    assert "Prefer reports from Missouri local news outlets" in finder.PROMPT
    assert "Never use Wikipedia, LinkedIn" in finder.PROMPT


def test_several_terms_at_once_write_every_article_once(finder, tmp_path, monkeypatch):
    def search(term, key, model=None):
        return (
            _answer(f"https://news.example/{term.text}")
            + _answer("https://news.example/shared"),
            0.01,
        )

    monkeypatch.setattr(finder, "search", search)
    monkeypatch.setattr(finder, "verify", lambda found: "yes")
    out = str(tmp_path / "found.csv")
    terms = [finder.Term(f"Paper {n}", "publication") for n in range(12)]
    finder.run(
        terms,
        "k",
        out,
        set(),
        finder.Spend(10),
        pause=0,
        log=lambda *_: None,
        workers=4,
    )
    urls = [r["url"] for r in csv.DictReader(open(out))]
    assert len(urls) == len(set(urls)) == 13
    assert len(open(out + ".done").read().splitlines()) == 12
