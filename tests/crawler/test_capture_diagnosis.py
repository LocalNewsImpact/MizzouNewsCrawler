"""Zero links must say WHY: a wall, an unrendered shell, or a quiet day.

Discovery recorded all three as NO_ARTICLES_FOUND, so a blocked source was
indistinguishable from one that simply published nothing. The three need
different responses -- credentials, a browser, nothing -- and the telemetry
has to tell them apart before anyone can choose.
"""

import pytest

from src.utils.capture_diagnosis import (
    MAX_ANCHORS_FOR_SHELL,
    CaptureDiagnosis,
    diagnose_capture,
    visible_text,
)
from src.utils.discovery_outcomes import DiscoveryOutcome

PAYWALL_HOMEPAGE = """<html><body>
<nav>Home News Sports Obituaries</nav>
<h1>Martin Crowned Homecoming Queen</h1><p>by Krista Guy</p>
<p>This content is for subscribers only. Click here to start your Free Trial</p>
</body></html>"""

JS_SHELL = (
    '<html><head><script src="/app.js"></script></head>'
    '<body><div id="__next"></div><script>window.__DATA__={}</script></body></html>'
)

REAL_HOMEPAGE = (
    "<html><body>"
    + "".join(
        f'<a href="/story-{i}">Council approves budget item {i}</a>'
        f"<p>Reporting text for story {i} goes here.</p>"
        for i in range(30)
    )
    + "</body></html>"
)


class TestDiagnosis:
    def test_paywall_wall_is_named(self):
        d = diagnose_capture(PAYWALL_HOMEPAGE)
        assert d.reason == "paywall"
        assert d.is_blocked is True
        assert d.signals["paywall_marker"] == "this content is for subscribers only"

    def test_js_shell_is_render_required(self):
        d = diagnose_capture(JS_SHELL)
        assert d.reason == "render_required"
        assert d.is_blocked is True
        assert d.signals["spa_root"] is True

    def test_real_homepage_with_no_new_links_is_not_blocked(self):
        """The case that must NOT be confused with a block."""
        d = diagnose_capture(REAL_HOMEPAGE, links_found=0)
        assert d.reason == "no_new_links"
        assert d.is_blocked is False
        assert d.signals["anchors"] == 30

    def test_empty_capture(self):
        for empty in (None, "", "   "):
            d = diagnose_capture(empty)
            assert d.reason == "empty"

    def test_paywall_wins_over_shell(self):
        """A wall is often also thin; being refused is the more useful fact."""
        walled_shell = (
            '<html><body><div id="root"></div>'
            "<p>This content is for subscribers only.</p></body></html>"
        )
        assert diagnose_capture(walled_shell).reason == "paywall"

    def test_thin_page_without_spa_marker_is_not_a_shell(self):
        """A small but genuinely rendered page is not a render failure."""
        thin = (
            "<html><body><p>"
            + ("The council met on Tuesday to review the budget. " * 40)
            + '</p><a href="/one">One</a></body></html>'
        )
        d = diagnose_capture(thin)
        assert d.reason == "no_new_links"
        assert d.signals["anchors"] <= MAX_ANCHORS_FOR_SHELL

    def test_signals_recorded_for_every_verdict(self):
        """Evaluable, not trusted: the evidence travels with the verdict."""
        for html in (PAYWALL_HOMEPAGE, JS_SHELL, REAL_HOMEPAGE):
            s = diagnose_capture(html).signals
            for key in ("chars", "text_chars", "text_ratio", "anchors", "scripts"):
                assert key in s

    def test_visible_text_drops_scripts_and_styles(self):
        html = (
            "<html><head><style>.a{color:red}</style></head>"
            "<body><script>var x=1</script><p>Real words here</p></body></html>"
        )
        text = visible_text(html)
        assert "Real words here" in text
        assert "var x" not in text
        assert "color:red" not in text


class TestOutcomeMapping:
    """The diagnosis has to reach the recorded outcome, or it changes nothing."""

    @pytest.fixture
    def processor(self):
        from src.crawler.source_processing import SourceProcessor

        return SourceProcessor.__new__(SourceProcessor)

    def _stats(self, **over):
        base = {
            "articles_new": 0,
            "articles_duplicate": 0,
            "articles_expired": 0,
            "articles_found_total": 0,
        }
        base.update(over)
        return base

    def test_paywall_diagnosis_maps_to_paywall_blocked(self, processor):
        out = processor._determine_outcome(self._stats(capture_diagnosis="paywall"))
        assert out == DiscoveryOutcome.PAYWALL_BLOCKED

    def test_render_diagnosis_maps_to_render_required(self, processor):
        out = processor._determine_outcome(
            self._stats(capture_diagnosis="render_required")
        )
        assert out == DiscoveryOutcome.RENDER_REQUIRED

    def test_no_diagnosis_keeps_the_old_outcome(self, processor):
        """Absent a diagnosis, behaviour is unchanged -- no silent reclassification."""
        assert processor._determine_outcome(self._stats()) == (
            DiscoveryOutcome.NO_ARTICLES_FOUND
        )

    def test_diagnosis_ignored_when_articles_were_found(self, processor):
        """A block recorded earlier must not override a successful result."""
        out = processor._determine_outcome(
            self._stats(articles_new=3, capture_diagnosis="paywall")
        )
        assert out == DiscoveryOutcome.NEW_ARTICLES_FOUND


class TestDiagnosisNeverBreaksFetching:
    def test_helper_swallows_failures(self):
        """A diagnostic must never be able to fail a fetch."""
        from src.crawler.discovery import NewsDiscovery

        d = NewsDiscovery.__new__(NewsDiscovery)
        # Passing a non-string is enough to blow up the regex path.
        d._note_capture_diagnosis("https://example.com", object())  # must not raise

    def test_dataclass_default_signals(self):
        assert CaptureDiagnosis("empty").signals == {}
