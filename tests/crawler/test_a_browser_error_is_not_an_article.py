"""The browser's own error page must not be stored as content.

thebannerpress.com let its certificate expire on 2024-07-15. Chrome showed
its SSL interstitial, `driver.page_source` returned that page, and the
extractor stored it: 22 articles whose body is a PEM certificate chain and
whose headline is "Privacy error". Twenty were CIN-classified on that
basis.

No interstitial check existed anywhere in the project -- `net::ERR`,
`chrome-error` and `main-frame-error` appeared nowhere -- so every
browser-level failure had been stored as an article since the beginning.
"""

from __future__ import annotations

from src.crawler.browser_errors import interstitial_error

#: Chrome's SSL interstitial, trimmed to its load-bearing parts. The real
#: capture runs to 7,031 characters, most of it base64 certificate.
SSL_INTERSTITIAL = """<html><head><title>Privacy error</title></head>
<body id="ssl"><div id="main-frame-error" class="interstitial-wrapper">
<h1>Your connection is not private</h1>
<p>Attackers might be trying to steal your information from
thebannerpress.com</p>
<div id="details-button">Advanced</div>
<p>net::ERR_CERT_DATE_INVALID</p>
<p>Subject: www.thebannerpress.com Issuer: R3 Expires on: Jul 15, 2024</p>
<p>-----BEGIN CERTIFICATE-----MIIGDjCCBPag-----END CERTIFICATE-----</p>
<a id="proceed-link">Proceed to thebannerpress.com (unsafe)</a>
</div></body></html>"""

#: A real story that quotes the error it saw. This is why the code alone
#: cannot be the test.
STORY_ABOUT_AN_OUTAGE = """<html><body><article>
<h1>County website down for three days after certificate lapse</h1>
<p>Visitors to the county clerk's site saw a browser warning reading
net::ERR_CERT_DATE_INVALID beginning Tuesday morning, after the
certificate expired over the weekend, the clerk said.</p>
<p>The county's IT contractor renewed it Thursday.</p>
</article></body></html>"""

ORDINARY_PAGE = """<html><body><article>
<h1>Council approves water main work</h1>
<p>The council met Tuesday and approved the replacement.</p>
</article></body></html>"""


class TestAnInterstitialIsRecognised:
    def test_the_expired_certificate_page_is_a_failure(self):
        assert interstitial_error(SSL_INTERSTITIAL) == "ERR_CERT_DATE_INVALID"

    def test_it_returns_which_failure_not_just_that_there_was_one(self):
        """The code is the evidence, so telemetry can tell an expired
        certificate from a DNS failure and a fix can be aimed at one."""
        assert interstitial_error(SSL_INTERSTITIAL).startswith("ERR_")

    def test_every_browser_level_failure_is_caught_not_only_certificates(self):
        for code in (
            "ERR_NAME_NOT_RESOLVED",
            "ERR_CONNECTION_REFUSED",
            "ERR_CONNECTION_TIMED_OUT",
            "ERR_SSL_PROTOCOL_ERROR",
            "ERR_CERT_COMMON_NAME_INVALID",
            "ERR_TOO_MANY_REDIRECTS",
        ):
            page = (
                '<html><body><div id="main-frame-error" '
                f'class="interstitial-wrapper">net::{code}</div></body></html>'
            )
            assert interstitial_error(page) == code, code

    def test_a_chrome_error_url_settles_it_alone(self):
        """`current_url` is `chrome-error://chromewebdata/` when no document
        from the site loaded at all. Whatever the body holds, the publisher
        did not serve it."""
        assert interstitial_error("<html></html>", "chrome-error://chromewebdata/")

    def test_a_chrome_error_url_still_reports_the_code_when_it_has_one(self):
        got = interstitial_error(
            '<html><body><div id="main-frame-error">net::ERR_NAME_NOT_RESOLVED'
            "</div></body></html>",
            "chrome-error://chromewebdata/",
        )
        assert got == "ERR_NAME_NOT_RESOLVED"


class TestAPageIsNotCondemnedForMentioningAnError:
    def test_a_real_story_about_a_certificate_outage_survives(self):
        """THE FALSE POSITIVE THAT MATTERS. A local paper covering its own
        county's outage quotes the code. Matching the code alone would
        delete the story and file it as a fetch failure."""
        assert interstitial_error(STORY_ABOUT_AN_OUTAGE) is None

    def test_an_ordinary_article_survives(self):
        assert interstitial_error(ORDINARY_PAGE) is None

    def test_scaffolding_without_a_code_is_not_enough_either(self):
        """Both halves are required. A site whose own markup happens to use
        the id `details-button` is not an error page."""
        page = (
            '<html><body><div id="details-button">More</div>'
            "<article><p>The council met.</p></article></body></html>"
        )
        assert interstitial_error(page) is None

    def test_an_empty_or_missing_body_is_not_an_error_page(self):
        """An empty capture is its own failure, reported elsewhere. Calling
        it a browser error would mislabel the cause."""
        assert interstitial_error("") is None
        assert interstitial_error(None) is None


class TestTheTitleIsDeliberatelyNotTheTest:
    def test_a_localised_interstitial_is_still_caught(self):
        """ "Privacy error" is a translated string. A title check stops
        working the first time a driver runs under another locale, which is
        the same class of bug as matching an ASCII marker list against a
        publisher's curly apostrophes -- silent, and invisible to any
        English-only fixture."""
        german = """<html><head><title>Datenschutzfehler</title></head>
        <body><div id="main-frame-error" class="interstitial-wrapper">
        <h1>Die Verbindung ist nicht sicher</h1>
        <p>net::ERR_CERT_DATE_INVALID</p></div></body></html>"""
        assert interstitial_error(german) == "ERR_CERT_DATE_INVALID"

    def test_an_article_titled_privacy_error_is_not_a_failure(self):
        """And the inverse: a story about privacy legislation is not an
        interstitial because of its headline."""
        page = (
            "<html><head><title>Privacy error in state database "
            "exposed 400 records</title></head><body><article><p>The state "
            "acknowledged the lapse Monday.</p></article></body></html>"
        )
        assert interstitial_error(page) is None


# ---------------------------------------------------------------------------
# The detector passing proves nothing about the wiring. This calls the real
# Selenium path with a driver that serves the interstitial.
# ---------------------------------------------------------------------------


class _Driver:
    """The little of a webdriver that `_extract_with_selenium` reads."""

    def __init__(self, page_source, current_url):
        self.page_source = page_source
        self.current_url = current_url

    def execute_script(self, _script):
        return None


def _extractor_serving(page_source, current_url="https://thebannerpress.com/a"):
    from unittest.mock import patch

    from src.crawler import ContentExtractor

    extractor = ContentExtractor()
    driver = _Driver(page_source, current_url)
    archived = []
    return (
        extractor,
        archived,
        patch.multiple(
            extractor,
            get_persistent_driver=lambda: driver,
            # True: "this driver may fetch". The method used to return None
            # and the caller ignored it; it now decides whether the fetch
            # happens at all, so a stub returning None refuses every page.
            _ensure_authenticated=lambda *a, **k: True,
            _navigate_with_human_behavior=lambda *a, **k: True,
            _record_raw_html=lambda html, source: archived.append((source, html)),
        ),
    )


class TestTheSeleniumPathReportsAFailure:
    URL = "https://www.thebannerpress.com/news/anita-borchelt-df3e3851"

    def test_no_article_comes_back(self):
        extractor, _, patched = _extractor_serving(SSL_INTERSTITIAL)
        with patched:
            result = extractor._extract_with_selenium(self.URL)
        assert result["success"] is False
        assert result["extraction_method"] == "error"
        assert result["title"] == ""
        assert result["content"] == ""

    def test_the_failure_names_the_code(self):
        """So telemetry records an expired certificate rather than "an
        extraction failed", which is what a fix gets aimed at."""
        extractor, _, patched = _extractor_serving(SSL_INTERSTITIAL)
        with patched:
            result = extractor._extract_with_selenium(self.URL)
        assert "ERR_CERT_DATE_INVALID" in result["error"]
        assert result["metadata"]["browser_error"] == "ERR_CERT_DATE_INVALID"

    def test_the_certificate_chain_never_becomes_a_body(self):
        """The 22 stored rows hold a PEM chain as the article text. Asserted
        directly, because that is the artefact this exists to prevent."""
        extractor, _, patched = _extractor_serving(SSL_INTERSTITIAL)
        with patched:
            result = extractor._extract_with_selenium(self.URL)
        assert "BEGIN CERTIFICATE" not in (result.get("content") or "")
        assert "Privacy error" not in (result.get("title") or "")

    def test_the_interstitial_is_still_archived(self):
        """It is the evidence for why this URL failed. Discarding it would
        make the failure unexplainable a month later."""
        extractor, archived, patched = _extractor_serving(SSL_INTERSTITIAL)
        with patched:
            extractor._extract_with_selenium(self.URL)
        assert archived and archived[0][0] == "selenium"
        assert "ERR_CERT_DATE_INVALID" in archived[0][1]

    def test_a_real_page_still_extracts_normally(self):
        """The guard must not stand between the crawler and a working
        site."""
        extractor, _, patched = _extractor_serving(ORDINARY_PAGE)
        with patched:
            result = extractor._extract_with_selenium(
                "https://example.com/news/water-main"
            )
        assert result.get("extraction_method") != "error"
        assert "Council approves water main work" in (result.get("title") or "")

    def test_a_story_about_an_outage_still_extracts(self):
        extractor, _, patched = _extractor_serving(STORY_ABOUT_AN_OUTAGE)
        with patched:
            result = extractor._extract_with_selenium("https://example.com/news/cert")
        assert result.get("extraction_method") != "error"
        assert "certificate lapse" in (result.get("title") or "")


class TestTheCurrentUrlIsReadDefensively:
    def test_a_non_string_current_url_decides_nothing(self):
        """`driver.current_url` is whatever the driver hands back. Anything
        non-string answers `.startswith()` with something truthy of its own
        -- a Mock does exactly that -- and a truthiness check condemned
        every page as a browser error, emptying the title of a working
        extraction. Caught by an existing Selenium test, not by this file."""
        from unittest.mock import Mock

        for odd in (Mock(), object(), 3, None, b"https://example.com/"):
            assert interstitial_error(ORDINARY_PAGE, odd) is None, repr(odd)

    def test_a_real_chrome_error_url_is_still_caught(self):
        """And the guard did not cost the thing it guards."""
        assert interstitial_error("<html></html>", "chrome-error://chromewebdata/")
