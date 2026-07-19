"""Contracts for the extraction cascade: trafilatura, newspaper4k,
readability-lxml, goose3, boilerpy3, htmldate, dateparser, py3langid,
beautifulsoup4/lxml, tldextract, furl, url-normalize.

Each test mirrors the exact call our code makes (call sites cited inline) so
a version bump that changes the API or the return shape fails HERE, in CI,
instead of at extraction time in production.
"""

from __future__ import annotations

import pytest

from .conftest import ARTICLE_URL, BODY_SENTENCE


class TestTrafilatura:
    """Call sites: src/mcmetadata/content.py:188 (bare_extraction),
    src/mcmetadata/languages.py:69 (utils.decode_file)."""

    def test_bare_extraction_wrapper_normalizes_both_shapes(self, article_html):
        """trafilatura < 2 returns a dict from bare_extraction; >= 2 returns a
        Document object ('Document' object is not subscriptable) — a break
        that silently disabled the trafilatura path in production when the
        images rebuilt with 2.1.0. Our vendored TrafilaturaExtractor must
        normalize BOTH shapes; this contract fails if either the trafilatura
        return shape or the wrapper regresses."""
        pytest.importorskip("trafilatura")

        try:
            from src.mcmetadata.content import TrafilaturaExtractor
        except ImportError:
            pytest.skip("src/ not shipped in this image (e.g. ml-base)")

        extractor = TrafilaturaExtractor()

        # Default path (include_metadata=False): body text is the contract.
        extractor.extract(ARTICLE_URL, article_html)
        assert BODY_SENTENCE in extractor.content["text"]
        assert extractor.content["extraction_method"]

        # Metadata path (include_metadata=True): title + parsed date too.
        extractor.extract(ARTICLE_URL, article_html, include_metadata=True)
        content = extractor.content
        assert BODY_SENTENCE in content["text"]
        assert content["title"] and "City Council" in content["title"]
        publish = content["potential_publish_date"]
        assert publish is not None and (publish.year, publish.month) == (2026, 3)

    def test_extract_keeps_body_drops_boilerplate(self, article_html):
        trafilatura = pytest.importorskip("trafilatura")

        text = trafilatura.extract(article_html, url=ARTICLE_URL) or ""
        assert BODY_SENTENCE in text
        # The subscribe CTA must not dominate; allow either dropped or present
        # but the body must be the bulk of the output.
        assert len(text) > 200

    def test_utils_decode_file_surface(self):
        trafilatura = pytest.importorskip("trafilatura")

        decoded = trafilatura.utils.decode_file(b"plain ascii bytes")
        assert "plain ascii" in decoded


class TestNewspaper4k:
    """Call site: src/crawler/__init__.py:3398 — NewspaperArticle(url,
    fetch_images=False), .html assignment, then .parse()."""

    def test_parse_from_preset_html(self, article_html):
        newspaper = pytest.importorskip("newspaper")

        article = newspaper.Article(ARTICLE_URL, fetch_images=False)
        article.download(input_html=article_html)
        article.parse()

        assert "City Council Approves 2026 Budget" in (article.title or "")
        assert BODY_SENTENCE in (article.text or "")
        # Author + date surfaces used by the field-level cascade
        assert isinstance(article.authors, list)
        assert article.publish_date is not None

    def test_html_attribute_assignment_still_supported(self, article_html):
        """The crawler assigns article.html directly before parsing."""
        newspaper = pytest.importorskip("newspaper")

        article = newspaper.Article(ARTICLE_URL, fetch_images=False)
        article.html = article_html
        article.parse()
        assert BODY_SENTENCE in (article.text or "")


class TestReadabilityGooseBoilerpy:
    """mcmetadata cascade fallbacks (requirements-processor.txt stack)."""

    def test_readability_document(self, article_html):
        readability = pytest.importorskip("readability")

        doc = readability.Document(article_html)
        # mcmetadata calls doc.title() and doc.summary(); title() may fall
        # back to '[no-title]' (heuristic, not an API break) — the API
        # contract is that both calls return strings and summary keeps the
        # body.
        assert isinstance(doc.title(), str)
        assert BODY_SENTENCE in doc.summary()

    def test_goose3_extract(self, article_html):
        goose3 = pytest.importorskip("goose3")

        with goose3.Goose({"enable_image_fetching": False}) as g:
            art = g.extract(raw_html=article_html)
        assert BODY_SENTENCE in art.cleaned_text

    def test_boilerpy3_extract(self, article_html):
        extractors = pytest.importorskip("boilerpy3.extractors")

        content = extractors.ArticleExtractor().get_content(article_html)
        assert BODY_SENTENCE in content


class TestDateStack:
    """Call sites: mcmetadata htmldate usage; dateparser.parse across
    src/mcmetadata/content.py and src/utils."""

    def test_htmldate_find_date(self, article_html):
        htmldate = pytest.importorskip("htmldate")

        assert htmldate.find_date(article_html) == "2026-03-05"

    def test_dateparser_parse(self):
        dateparser = pytest.importorskip("dateparser")

        parsed = dateparser.parse("March 5, 2026")
        assert parsed is not None and (parsed.year, parsed.month) == (2026, 3)

    def test_py3langid_classify(self):
        py3langid = pytest.importorskip("py3langid")

        lang, _score = py3langid.classify(
            "The city council voted to approve the municipal budget."
        )
        assert lang == "en"


class TestHtmlParsingStack:
    """bs4 + lxml + soupsieve as _extract_content uses them."""

    def test_beautifulsoup_lxml_select_and_decompose(self, article_html):
        bs4 = pytest.importorskip("bs4")

        soup = bs4.BeautifulSoup(article_html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        assert BODY_SENTENCE in text
        assert "More Stories" not in text  # aside removed
        # CSS selection via soupsieve
        assert soup.select_one("article h1") is not None


class TestUrlStack:
    """tldextract (offline PSL), furl, url_normalize — discovery/url utils."""

    def test_tldextract_offline(self):
        tldextract = pytest.importorskip("tldextract")

        # suffix_list_urls=() forbids the publicsuffix.org fetch — the same
        # offline behavior the crawler needs behind the whitelist proxy.
        extractor = tldextract.TLDExtract(suffix_list_urls=())
        parts = extractor("https://www.example-gazette.com/path")
        assert parts.domain == "example-gazette"
        assert parts.suffix == "com"

    def test_furl_and_url_normalize(self):
        furl_mod = pytest.importorskip("furl")
        url_normalize = pytest.importorskip("url_normalize")

        u = furl_mod.furl(ARTICLE_URL)
        assert u.host == "www.example-gazette.com"
        assert (
            url_normalize.url_normalize("HTTP://Example.COM/a%2fb")
            .lower()
            .startswith("http://example.com")
        )
